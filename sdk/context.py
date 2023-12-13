import base64
import collections
import hashlib
import threading
from concurrent.futures import Future
from typing import Optional

from sdk.audience_matcher import AudienceMatcher
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_event_handler import ContextEventHandler
from sdk.context_event_logger import ContextEventLogger, EventType
from sdk.internal.lock.atomic_bool import AtomicBool
from sdk.internal.lock.atomic_int import AtomicInt
from sdk.internal.lock.concurrency import Concurrency
from sdk.internal.lock.read_write_lock import ReadWriteLock
from sdk.internal.variant_assigner import VariantAssigner
from sdk.json.attribute import Attribute
from sdk.json.context_data import ContextData
from sdk.json.experiment import Experiment
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.publish_event import PublishEvent
from sdk.json.unit import Unit
from sdk.time.clock import Clock
from sdk.variable_parser import VariableParser


class Assignment:
    def __init__(self):
        self.id: Optional[int] = 0
        self.iteration: Optional[int] = 0
        self.full_on_variant: Optional[int] = 0
        self.name: Optional[str] = None
        self.unit_type: Optional[str] = None
        self.traffic_split: list[int] = []
        self.variant: Optional[int] = 0
        self.assigned: Optional[bool] = False
        self.overridden: Optional[bool] = False
        self.eligible: Optional[bool] = False
        self.full_on: Optional[bool] = False
        self.custom: Optional[bool] = False
        self.audience_mismatch: Optional[bool] = False
        self.variables: dict = {}
        self.exposed = AtomicBool()


class ExperimentVariables:
    data: Optional[Experiment]
    variables: Optional[list[dict]]

class ContextCustomFieldValue:
    type: Optional[str]
    value: Optional[any]

def experiment_matches(experiment: Experiment, assignment: Assignment):
    return experiment.id == assignment.id and \
           experiment.unitType == assignment.unit_type and \
           experiment.iteration == assignment.iteration and \
           experiment.fullOnVariant == assignment.full_on_variant and \
           collections.Counter(experiment.trafficSplit) == \
           collections.Counter(assignment.traffic_split)


class Context:
    def __init__(self,
                 clock: Clock, config: ContextConfig,
                 data_future: Future, data_provider: ContextDataProvider,
                 event_handler: ContextEventHandler,
                 event_logger: ContextEventLogger,
                 variable_parser: VariableParser,
                 audience_matcher: AudienceMatcher):
        self.clock = clock
        self.publish_delay = config.publish_delay
        self.refresh_interval = config.refresh_interval
        self.event_handler = event_handler
        self.event_logger = event_logger
        self.data_provider = data_provider
        self.variable_parser = variable_parser
        self.audience_matcher = audience_matcher

        self.units = {}
        self.index = {}
        self.index_variables = {}
        self.context_custom_fields = {}
        self.assignment_cache = {}
        self.cassignments = {}
        self.overrides = {}

        self.exposures = []
        self.achievements = []

        self.data: Optional[ContextData] = None

        self.failed = False

        self.closed = AtomicBool()
        self.closing = AtomicBool()
        self.refreshing = AtomicBool()
        self.pending_count = AtomicInt()

        self.context_lock = ReadWriteLock()
        self.data_lock = ReadWriteLock()
        self.timeout_lock = ReadWriteLock()
        self.event_lock = ReadWriteLock()

        self.refresh_future: Optional[Future] = None
        self.closing_future: Optional[Future] = None

        self.refresh_timer: Optional[threading.Timer] = None
        self.timeout: Optional[threading.Timer] = None

        if config.units is not None:
            self.set_units(config.units)

        self.assigners = dict.fromkeys((range(len(self.units))))
        self.hashed_units = dict.fromkeys((range(len(self.units))))

        self.attributes: list[Attribute] = []

        if config.attributes is not None:
            self.set_attributes(config.attributes)

        if config.overrides is not None:
            self.overrides = dict(config.overrides)
        else:
            self.overrides = {}

        if config.cassigmnents is not None:
            self.cassignments = dict(config.cassigmnents)
        else:
            self.cassignments = {}

        if data_future.done():
            def when_finished(data: Future):
                if data.done() and data.cancelled() is False and \
                        data.exception() is None:
                    self.set_data(data.result())
                    self.log_event(EventType.READY, data.result())
                elif data.cancelled() is False and \
                        data.exception() is not None:
                    self.set_data_failed(data.exception())
                    self.log_error(data.exception())

            data_future.add_done_callback(when_finished)
        else:
            self.ready_future = Future()

            def when_finished(data: Future):
                if data.done() and data.cancelled() is False and \
                        data.exception() is None:
                    self.set_data(data.result())
                    self.ready_future.set_result(None)
                    self.ready_future = None
                    self.log_event(EventType.READY, data.result())

                    if self.get_pending_count() > 0:
                        self.set_timeout()
                elif data.cancelled() is False and \
                        data.exception() is not None:
                    self.set_data_failed(data.exception())
                    self.ready_future.set_result(None)
                    self.ready_future = None
                    self.log_error(data.exception())

            data_future.add_done_callback(when_finished)

    def set_units(self, units: dict):
        for key, value in units.items():
            self.set_unit(key, value)

    def set_unit(self, unit_type: str, uid: str):
        self.check_not_closed()

        try:
            self.context_lock.acquire_write()

            if unit_type in self.units.keys() and self.units[unit_type] != uid:
                raise ValueError("Unit already set.")

            trimmed = uid.strip()
            if len(trimmed) == 0:
                raise ValueError("Unit UID must not be blank.")

            self.units[unit_type] = trimmed
        finally:
            self.context_lock.release_write()

    def set_attributes(self, attributes: dict):
        for key, value in attributes.items():
            self.set_attribute(key, value)

    def set_attribute(self, name: str, value: object):
        self.check_not_closed()
        attribute = Attribute()
        attribute.name = name
        attribute.value = value
        attribute.setAt = self.clock.millis()
        Concurrency.add_rw(self.context_lock, self.attributes, attribute)

    def check_not_closed(self):
        if self.closed.value:
            raise RuntimeError('ABSmartly Context is closed')
        elif self.closing.value:
            raise RuntimeError('ABSmartly Context is closing')

    def set_data(self, data: ContextData):
        index = {}
        index_variables = {}
        context_custom_fields = {}

        for experiment in data.experiments:
            experiment_variables = ExperimentVariables()
            experiment_variables.data = experiment
            experiment_variables.variables = []

            for variant in experiment.variants:
                if variant.config is not None and len(variant.config) > 0:
                    variables = self.variable_parser.parse(
                        self,
                        experiment.name,
                        variant.name,
                        variant.config)
                    for key, value in variables.items():
                        index_variables[key] = experiment_variables
                    experiment_variables.variables.append(variables)
                else:
                    experiment_variables.variables.append({})
            index[experiment.name] = experiment_variables

            if experiment.customFieldValues is not None:
                experimentCustomFields = {}
                for customFieldValue in experiment.customFieldValues:
                    value = ContextCustomFieldValue()
                    value.type = customFieldValue.type

                    if customFieldValue.value is not None:
                        customValue = customFieldValue.value

                        if customFieldValue.type.startswith("json"):
                            value.value = self.variable_parser.parse(
                                self,
                                experiment.name,
                                customFieldValue.name,
                                customValue)

                        elif customFieldValue.type.startswith("boolean"):
                            value.value = bool(customValue)

                        elif customFieldValue.type.startswith("number"):
                            value.value = int(customValue)


                        else:
                            value.value = customValue

                    experimentCustomFields[customFieldValue.name] = value

                context_custom_fields[experiment.name] = experimentCustomFields

        try:
            self.data_lock.acquire_write()

            self.index = index
            self.index_variables = index_variables
            self.context_custom_fields = context_custom_fields
            self.data = data

            self.set_refresh_timer()
        finally:
            self.data_lock.release_write()

    def set_refresh_timer(self):
        if self.refresh_interval > 0 and self.refresh_timer is None and not self.is_closing() and not self.is_closed():
            def ref():
                self.refresh_async()
                self.refresh_timer = threading.Timer(
                    self.refresh_interval,
                    ref)
                self.refresh_timer.start()

            self.refresh_timer = threading.Timer(
                self.refresh_interval,
                ref)
            self.refresh_timer.start()

    def set_timeout(self):
        if self.is_ready():
            if self.timeout is None:
                try:
                    self.timeout_lock.acquire_write()

                    def flush():
                        self.flush()

                    self.timeout = threading.Timer(self.publish_delay, flush)
                    self.timeout.start()
                finally:
                    self.timeout_lock.release_write()

    def is_ready(self):
        return self.data is not None

    def is_failed(self):
        return self.failed

    def is_closed(self):
        return self.closed.value

    def is_closing(self):
        return not self.closed.value and self.closing.value

    def refresh_async(self):
        self.check_not_closed()

        if self.refreshing.compare_and_set(False, True):
            self.refresh_future = Future()

            def when_ready(data):
                if data.done() and data.cancelled() is False and \
                        data.exception() is None:
                    self.set_data(data.result())
                    self.refreshing.set(False)
                    self.refresh_future.set_result(None)
                    self.log_event(EventType.REFRESH, data.result())
                elif data.cancelled() is False and \
                        data.exception() is not None:
                    self.refreshing.set(False)
                    self.refresh_future.set_exception(data.exception())
                    self.log_error(data.exception())

            self.data_provider\
                .get_context_data()\
                .add_done_callback(when_ready)

        if self.refresh_future is not None:
            return self.refresh_future
        else:
            result = Future()
            result.set_result(None)
            return result

    def set_data_failed(self, exception):
        try:
            self.data_lock.acquire_write()
            self.index = {}
            self.index_variables = {}
            self.data = ContextData()
            self.failed = True
        finally:
            self.data_lock.release_write()

    def log_error(self, exception):
        if self.event_logger is not None:
            self.event_logger.handle_event(EventType.ERROR, exception)

    def log_event(self, event: EventType, data: object):
        if self.event_logger is not None:
            self.event_logger.handle_event(event, data)

    def get_pending_count(self):
        return self.pending_count.get()

    def flush(self):
        self.clear_timeout()

        if self.failed is False:
            if self.pending_count.get() > 0:
                exposures = None
                achievements = None
                event_count = 0
                try:
                    self.event_lock.acquire_write()
                    event_count = self.pending_count.get()

                    if event_count > 0:
                        if len(self.exposures) > 0:
                            exposures = list(self.exposures)
                            self.exposures.clear()

                        if len(self.achievements) > 0:
                            achievements = list(self.achievements)
                            self.achievements.clear()
                        self.pending_count.set(0)
                finally:
                    self.event_lock.release_write()

                if event_count > 0:
                    event = PublishEvent()
                    event.hashed = True
                    event.publishedAt = self.clock.millis()
                    event.units = []
                    for key, value in self.units.items():
                        unit = Unit()
                        unit.type = key
                        unit.uid = str(
                            self.get_unit_hash(key, value),
                            encoding='ascii')\
                            .encode('ascii', errors='ignore')\
                            .decode()
                        event.units.append(unit)
                    if len(self.attributes) > 0:
                        event.attributes = list(self.attributes)
                    else:
                        event.attributes = None
                    event.exposures = exposures
                    event.goals = achievements

                    result = Future()

                    def run(data):
                        if data.done() and \
                                data.cancelled() is False and \
                                data.exception() is None:
                            self.log_event(EventType.PUBLISH, event)
                            result.set_result(None)
                        elif data.cancelled() is False and \
                                data.exception() is not None:
                            self.log_error(data.exception())
                            result.set_exception(data.exception())

                    self.event_handler\
                        .publish(self, event)\
                        .add_done_callback(run)
                    return result
        else:
            try:
                self.event_lock.acquire_write()
                self.exposures.clear()
                self.achievements.clear()
                self.pending_count.set(0)
            finally:
                self.event_lock.release_write()

        result = Future()
        result.set_result(None)
        return result

    def close(self):
        self.close_async().result()

    def refresh(self):
        self.refresh_async().result()

    def publish(self):
        self.publish_async().result()

    def publish_async(self):
        self.check_not_closed()
        return self.flush()

    def track(self, goal_name: str, properties: dict):
        self.check_not_closed()

        achievement = GoalAchievement()
        achievement.achievedAt = self.clock.millis()
        achievement.name = goal_name
        if properties is None:
            achievement.properties = None
        else:
            achievement.properties = dict(properties)

        try:
            self.event_lock.acquire_write()
            self.pending_count.increment_and_get()
            self.achievements.append(achievement)
        finally:
            self.event_lock.release_write()

        self.log_event(EventType.GOAL, achievement)
        self.set_timeout()

    def wait_until_ready(self):
        if self.data is None:
            if self.ready_future is not None and not self.ready_future.done():
                self.ready_future.result()
        return self

    def wait_until_ready_async(self):
        if self.data is not None:
            result = Future()
            result.set_result(self)
            return result
        else:
            def apply(fut: Future):
                return self

            self.ready_future.add_done_callback(apply)
            return self.ready_future

    def clear_timeout(self):
        if self.timeout is not None:
            try:
                self.timeout_lock.acquire_write()
                if self.timeout is not None:
                    self.timeout.cancel()
                    self.timeout = None
            finally:
                self.timeout_lock.release_write()

    def clear_refresh_timer(self):
        if self.refresh_timer is not None:
            self.refresh_timer.cancel()
            self.refresh_timer = None

    def get_variable_value(self, key: str, default_value: object):
        self.check_ready(True)

        assignment = self.get_variable_assignment(key)
        if assignment is not None:
            if assignment.variables is not None:
                if not assignment.exposed.value:
                    self.queue_exposure(assignment)

                if key in assignment.variables:
                    return assignment.variables[key]
        return default_value

    def peek_variable_value(self, key: str, default_value: object):
        self.check_ready(True)

        assignment = self.get_variable_assignment(key)
        if assignment is not None:
            if assignment.variables is not None:
                if key in assignment.variables:
                    return assignment.variables[key]
        return default_value

    def peek_treatment(self, experiment_name: str):
        self.check_ready(True)

        return self.get_assignment(experiment_name).variant

    def get_unit_hash(self, unit_type: str, unit_uid: str):
        def computer(key: str):
            dig = hashlib.md5(unit_uid.encode('utf-8')).digest()
            unithash = base64.urlsafe_b64encode(dig).rstrip(b'=')
            return unithash

        return Concurrency.compute_if_absent_rw(
            self.context_lock,
            self.hashed_units,
            unit_type,
            computer)

    def get_treatment(self, experiment_name: str):
        self.check_ready(True)
        assignment = self.get_assignment(experiment_name)
        if not assignment.exposed.value:
            self.queue_exposure(assignment)
        return assignment.variant

    def get_variable_keys(self):
        self.check_ready(True)

        variable_keys = {}
        try:
            self.data_lock.acquire_read()
            for key, value in self.index_variables.items():
                expr_var: ExperimentVariables = value
                variable_keys[key] = expr_var.data.name
        finally:
            self.data_lock.release_write()

        return variable_keys

    def get_custom_field_keys(self):
        self.check_ready(True)

        keys = []
        try:
            self.data_lock.acquire_read()

            for experiment in self.data.experiments:
                customFieldValues = experiment.customFieldValues

                if customFieldValues is not None:
                    for customFieldValue in customFieldValues:
                        keys.append(customFieldValue.name)
        finally:
            self.data_lock.release_write()

        keys = list(set(keys))
        keys.sort()

        return keys

    def get_custom_field_value(self, experiment_name: str, key: str):
        self.check_ready(True)

        value: any = None
        try:
            self.data_lock.acquire_read()

            if experiment_name in self.context_custom_fields:
                custom_field_value = self.context_custom_fields[experiment_name]
                if key in custom_field_value:
                    value = custom_field_value[key].value

        finally:
            self.data_lock.release_read()

        return value

    def get_custom_field_type(self, experiment_name: str, key: str):
        self.check_ready(True)

        type = None
        try:
            self.data_lock.acquire_read()

            if experiment_name in self.context_custom_fields:
                customFieldValue = self.context_custom_fields[experiment_name]
                if key in customFieldValue:
                    type = customFieldValue[key].type

        finally:
            self.data_lock.release_read()

        return type

    def get_assignment(self, experiment_name: str):
        try:
            self.context_lock.acquire_read()

            if experiment_name in self.assignment_cache:
                assignment: Assignment = self.assignment_cache[experiment_name]

                experiment: ExperimentVariables = \
                    self.get_experiment(experiment_name)

                if experiment_name in self.overrides:
                    override = self.overrides[experiment_name]
                    if assignment.overridden and \
                            assignment.variant == override:
                        return assignment
                elif experiment is None:
                    if assignment.assigned is False:
                        return assignment
                elif experiment_name not in self.cassignments or \
                        self.cassignments[experiment_name] == \
                        assignment.variant:
                    if experiment_matches(experiment.data, assignment):
                        return assignment
        finally:
            self.context_lock.release_read()

        try:
            self.context_lock.acquire_write()
            experiment: ExperimentVariables = \
                self.get_experiment(experiment_name)
            assignment = Assignment()
            assignment.name = experiment_name
            assignment.eligible = True

            if experiment_name in self.overrides:
                if experiment is not None:
                    assignment.id = experiment.data.id
                    assignment.unit_type = experiment.data.unitType

                assignment.overridden = True
                assignment.variant = self.overrides[experiment_name]
            else:
                if experiment is not None:
                    unit_type = experiment.data.unitType

                    if experiment.data.audience is not None and \
                            len(experiment.data.audience) > 0:
                        attrs = {}
                        for attr in self.attributes:
                            attrs[attr.name] = attr.value
                        match = self.audience_matcher.evaluate(
                            experiment.data.audience,
                            attrs)
                        if match is not None:
                            assignment.audience_mismatch = not match.result
                    if experiment.data.audienceStrict and \
                            assignment.audience_mismatch:
                        assignment.variant = 0
                    elif experiment.data.fullOnVariant == 0:
                        if experiment.data.unitType in self.units:
                            uid = self.units[experiment.data.unitType]
                            unit_hash = self.get_unit_hash(unit_type, uid)
                            assigner: VariantAssigner = \
                                self.get_variant_assigner(unit_type,
                                                          unit_hash)
                            eligible = \
                                assigner.assign(
                                    experiment.data.trafficSplit,
                                    experiment.data.trafficSeedHi,
                                    experiment.data.trafficSeedLo) == 1
                            if eligible:
                                if experiment_name in self.cassignments:
                                    custom = self.cassignments[experiment_name]
                                    assignment.variant = custom
                                    assignment.custom = True
                                else:
                                    assignment.variant = \
                                        assigner.assign(experiment.data.split,
                                                        experiment.data.seedHi,
                                                        experiment.data.seedLo)
                            else:
                                assignment.eligible = False
                                assignment.variant = 0

                            assignment.assigned = True

                    else:
                        assignment.assigned = True
                        assignment.variant = experiment.data.fullOnVariant
                        assignment.full_on = True

                    assignment.unit_type = unit_type
                    assignment.id = experiment.data.id
                    assignment.iteration = experiment.data.iteration
                    assignment.traffic_split = experiment.data.trafficSplit
                    assignment.full_on_variant = experiment.data.fullOnVariant

            if experiment is not None and \
                    (assignment.variant < len(experiment.data.variants)):
                assignment.variables = experiment.variables[assignment.variant]

            self.assignment_cache[experiment_name] = assignment
            return assignment
        finally:
            self.context_lock.release_write()

    def check_ready(self, expect_not_closed: bool):
        if not self.is_ready():
            raise RuntimeError('ABSmartly Context is not yet ready')
        elif expect_not_closed:
            self.check_not_closed()

    def get_experiment(self, experiment_name: str):
        try:
            self.data_lock.acquire_read()
            return self.index.get(experiment_name, None)
        finally:
            self.data_lock.release_read()

    def get_experiments(self):
        self.check_ready(True)

        try:
            self.data_lock.acquire_read()
            experiment_names = []
            for experiment in self.data.experiments:
                experiment_names.append(experiment.name)

            return experiment_names
        finally:
            self.data_lock.release_read()

    def get_data(self):
        self.check_ready(True)

        try:
            self.data_lock.acquire_read()
            return self.data
        finally:
            self.data_lock.release_read()

    def set_override(self, experiment_name: str, variant: int):
        self.check_not_closed()

        return Concurrency.put_rw(self.context_lock,
                                  self.overrides,
                                  experiment_name, variant)

    def get_override(self, experiment_name: str):
        return Concurrency.get_rw(self.context_lock,
                                  self.overrides,
                                  experiment_name)

    def set_overrides(self, overrides: dict):
        for key, value in overrides.items():
            self.set_override(key, value)

    def set_custom_assignment(self, experiment_name: str, variant: int):
        self.check_not_closed()

        Concurrency.put_rw(self.context_lock,
                           self.cassignments,
                           experiment_name, variant)

    def get_custom_assignment(self, experiment_name: str):
        return Concurrency.get_rw(self.context_lock,
                                  self.cassignments,
                                  experiment_name)

    def set_custom_assignments(self, custom_assignments: dict):
        for key, value in custom_assignments.items():
            self.set_custom_assignment(key, value)

    def get_variant_assigner(self, unit_type: str, unit_hash: bytes):
        def apply(key: str):
            return VariantAssigner(bytearray(unit_hash))

        return Concurrency.compute_if_absent_rw(self.context_lock,
                                                self.assigners,
                                                unit_type, apply)

    def get_variable_experiment(self, key: str):
        return Concurrency.get_rw(self.data_lock, self.index_variables, key)

    def get_variable_assignment(self, key: str):
        experiment: ExperimentVariables = self.get_variable_experiment(key)
        if experiment is not None:
            return self.get_assignment(experiment.data.name)
        return None

    def close_async(self):
        if not self.closed.value:
            if self.closing.compare_and_set(False, True):
                self.clear_refresh_timer()

                if self.pending_count.get() > 0:
                    self.closing_future = Future()

                    def accept(res: Future):
                        if res.done() and res.cancelled() is False \
                                and res.exception() is None:
                            self.closed.set(True)
                            self.closing.set(False)
                            self.closing_future.set_result(None)
                            self.log_event(EventType.CLOSE, None)
                        elif res.cancelled() is False \
                                and res.exception() is not None:
                            self.closed.set(True)
                            self.closing.set(False)
                            self.closing_future.exception(res.exception())

                    self.flush().add_done_callback(accept)
                    return self.closing_future

                else:
                    self.closed.set(True)
                    self.closing.set(False)
                    self.log_event(EventType.CLOSE, None)

            if self.closing_future is not None:
                return self.closing_future

        result = Future()
        result.set_result(None)
        return result

    def queue_exposure(self, assignment: Assignment):
        if assignment.exposed.compare_and_set(False, True):
            exposure = Exposure()
            exposure.id = assignment.id
            exposure.name = assignment.name
            exposure.unit = assignment.unit_type
            exposure.variant = assignment.variant
            exposure.exposedAt = self.clock.millis()
            exposure.assigned = assignment.assigned
            exposure.eligible = assignment.eligible
            exposure.overridden = assignment.overridden
            exposure.fullOn = assignment.full_on
            exposure.custom = assignment.custom
            exposure.audienceMismatch = assignment.audience_mismatch

            try:
                self.event_lock.acquire_write()
                self.pending_count.increment_and_get()
                self.exposures.append(exposure)
            finally:
                self.event_lock.release_write()

            self.log_event(EventType.EXPOSURE, exposure)
            self.set_timeout()
