import base64
import collections
import copy
import hashlib
import threading
from concurrent.futures import Future
from typing import Optional

from sdk.audience_matcher import AudienceMatcher
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_publisher import ContextPublisher
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
        self.variables: Optional[dict] = None
        self.exposed = AtomicBool()
        self.exposedAt: Optional[int] = None
        self.attrs_seq: Optional[int] = 0


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
                 event_handler: ContextPublisher,
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
        self.historic = config.historic

        self.units = {}
        self.index = {}
        self.index_variables = {}
        self.context_custom_fields = {}
        self.assignment_cache = {}
        self.custom_assignments = {}
        self.overrides = {}

        self.exposures = []
        self.achievements = []

        self.data: Optional[ContextData] = None

        self.failed = False
        self.close_error = None
        self.ready_error = None

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
        self._attrs_seq = 0

        if config.attributes is not None:
            self.set_attributes(config.attributes)

        if config.overrides is not None:
            self.overrides = dict(config.overrides)
        else:
            self.overrides = {}

        cassignments = config.custom_assignments
        if cassignments is not None:
            self.custom_assignments = dict(cassignments)
        else:
            self.custom_assignments = {}

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
                    raise RuntimeError(
                        "Failed to initialize ABSmartly Context"
                    ) from data.exception()

            data_future.add_done_callback(when_finished)
        else:
            self.ready_future = Future()

            def when_finished(data: Future):
                if data.done() and data.cancelled() is False and \
                        data.exception() is None:
                    self.set_data(data.result())
                    self.ready_future.set_result(None)
                    self.log_event(EventType.READY, data.result())

                    if self.get_pending_count() > 0:
                        self.set_timeout()
                elif data.cancelled() is False and \
                        data.exception() is not None:
                    self.set_data_failed(data.exception())
                    self.ready_future.set_result(None)
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
                raise ValueError(f"Unit '{unit_type}' UID already set.")

            trimmed = uid.strip()
            if len(trimmed) == 0:
                raise ValueError(f"Unit '{unit_type}' UID must not be blank.")

            self.units[unit_type] = trimmed
        finally:
            self.context_lock.release_write()

    def get_unit(self, unit_type: str):
        return Concurrency.get_rw(self.context_lock, self.units, unit_type)

    def get_units(self):
        try:
            self.context_lock.acquire_read()
            return dict(self.units)
        finally:
            self.context_lock.release_read()

    def set_attributes(self, attributes: dict):
        for key, value in attributes.items():
            self.set_attribute(key, value)

    def get_attribute(self, name: str):
        try:
            self.context_lock.acquire_read()
            result = None
            for attr in self.attributes:
                if attr.name == name:
                    result = attr.value
            return copy.deepcopy(result) if isinstance(result, (dict, list)) else result
        finally:
            self.context_lock.release_read()

    def get_attributes(self):
        try:
            self.context_lock.acquire_read()
            result = {}
            for attr in self.attributes:
                value = attr.value
                result[attr.name] = copy.deepcopy(value) if isinstance(value, (dict, list)) else value
            return result
        finally:
            self.context_lock.release_read()

    def set_attribute(self, name: str, value: object):
        self.check_not_closed()
        attribute = Attribute()
        attribute.name = name
        attribute.value = value
        attribute.setAt = self.clock.millis()
        try:
            self.context_lock.acquire_write()
            self.attributes.append(attribute)
            self._attrs_seq += 1
        finally:
            self.context_lock.release_write()

    def check_not_closed(self):
        if self.closed.value:
            raise RuntimeError('ABsmartly Context is finalized.')
        elif self.closing.value:
            raise RuntimeError('ABsmartly Context is finalizing.')

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
                    try:
                        variables = self.variable_parser.parse(
                            self,
                            experiment.name,
                            variant.name,
                            variant.config)

                        if variables is None:
                            self.log_event(
                                EventType.ERROR,
                                f"Failed to parse variant config for {experiment.name}/{variant.name}"
                            )
                            experiment_variables.variables.append({})
                            continue

                        for key, value in variables.items():
                            if key in index_variables:
                                if experiment_variables not in index_variables[key]:
                                    index_variables[key].append(experiment_variables)
                            else:
                                index_variables[key] = [experiment_variables]
                        experiment_variables.variables.append(variables)
                    except Exception as e:
                        self.log_event(
                            EventType.ERROR,
                            f"Error parsing variant {experiment.name}/{variant.name}: {e}"
                        )
                        experiment_variables.variables.append({})
                else:
                    experiment_variables.variables.append({})
            index[experiment.name] = experiment_variables

            if experiment.customFieldValues is not None:
                experimentCustomFields = {}
                for customFieldValue in experiment.customFieldValues:
                    # Store the raw type/value and parse lazily on access (see
                    # _get_custom_field). Eagerly parsing here would emit a
                    # spurious ERROR event at ready-time for fields that are
                    # never accessed (e.g. an intentionally-invalid json field),
                    # which diverges from the canonical SDKs (JS/dart) that
                    # parse only when the value is requested.
                    value = ContextCustomFieldValue()
                    value.type = customFieldValue.type
                    value.value = customFieldValue.value

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
                if not self.is_closed() and not self.is_closing():
                    self.refresh_async()
                    if not self.is_closed() and not self.is_closing():
                        self.refresh_timer = threading.Timer(
                            self.refresh_interval,
                            ref)
                        self.refresh_timer.start()

            self.refresh_timer = threading.Timer(
                self.refresh_interval,
                ref)
            self.refresh_timer.start()

    def set_timeout(self):
        if self.is_ready() and self.publish_delay >= 0:
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

    def is_finalized(self):
        return self.is_closed()

    def is_closing(self):
        return not self.closed.value and self.closing.value

    def is_finalizing(self):
        return self.is_closing()

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
            self.ready_error = exception
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

                        self.pending_count.set(
                            self.pending_count.get() - event_count
                        )
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
                    event.historic = self.historic

                    result = Future()

                    def run(data):
                        if data.done() and \
                                data.cancelled() is False and \
                                data.exception() is None:
                            self.log_event(EventType.PUBLISH, event)
                            result.set_result(None)
                        elif data.cancelled() is False and \
                                data.exception() is not None:
                            try:
                                self.event_lock.acquire_write()
                                if exposures:
                                    self.exposures = exposures + self.exposures
                                if achievements:
                                    self.achievements = achievements + self.achievements
                                self.pending_count.set(
                                    self.pending_count.get() + event_count
                                )
                            finally:
                                self.event_lock.release_write()
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
        try:
            self.close_async().result()
        except Exception as e:
            self.close_error = e
            self.log_error(e)
            raise

    def finalize(self):
        return self.close()

    def finalize_async(self):
        return self.close_async()

    def refresh(self):
        self.refresh_async().result()

    def publish(self):
        self.publish_async().result()

    def publish_async(self):
        self.check_not_closed()
        return self.flush()

    def track(self, goal_name: str, properties: dict, achieved_at: int = None):
        self.check_not_closed()

        achievement = GoalAchievement()
        achievement.achievedAt = achieved_at or self.clock.millis()
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
        try:
            self.timeout_lock.acquire_write()
            if self.refresh_timer is not None:
                self.refresh_timer.cancel()
                self.refresh_timer = None
        finally:
            self.timeout_lock.release_write()

    def get_variable_value(self, key: str, default_value: object):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return default_value

        assignment = self.get_variable_assignment(key)
        if assignment is not None:
            if assignment.variables is not None:
                if not assignment.exposed.value:
                    self.queue_exposure(assignment)

                if key in assignment.variables:
                    return assignment.variables[key]
        return default_value

    def peek_variable_value(self, key: str, default_value: object):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return default_value

        assignment = self.get_variable_assignment(key)
        if assignment is not None:
            if assignment.variables is not None:
                if key in assignment.variables:
                    return assignment.variables[key]
        return default_value

    def peek_treatment(self, experiment_name: str):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return 0

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

    def get_treatment(self, experiment_name: str, exposed_at: int = None):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return 0
        assignment = self.get_assignment(experiment_name, exposed_at=exposed_at)
        if not assignment.exposed.value:
            self.queue_exposure(assignment)
        return assignment.variant

    def get_variable_keys(self):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return {}

        variable_keys = {}
        try:
            self.data_lock.acquire_read()
            for key, experiments in self.index_variables.items():
                variable_keys[key] = [expr_var.data.name for expr_var in experiments]
        finally:
            self.data_lock.release_read()

        return variable_keys

    def get_custom_field_keys(self):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return []

        keys = []
        try:
            self.data_lock.acquire_read()

            for experiment in self.data.experiments:
                customFieldValues = experiment.customFieldValues

                if customFieldValues is not None:
                    for customFieldValue in customFieldValues:
                        keys.append(customFieldValue.name)
        finally:
            self.data_lock.release_read()

        keys = list(set(keys))
        keys.sort()

        return keys

    def _get_custom_field(self, experiment_name: str, key: str, field_attr: str):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return None

        result = None
        try:
            self.data_lock.acquire_read()

            if experiment_name in self.context_custom_fields:
                custom_field_value = self.context_custom_fields[experiment_name]
                if key in custom_field_value:
                    field = custom_field_value[key]
                    if field_attr == 'value':
                        result = self._coerce_custom_field_value(
                            experiment_name, key, field.type, field.value
                        )
                    else:
                        result = getattr(field, field_attr)

        finally:
            self.data_lock.release_read()

        return result

    def _coerce_custom_field_value(self, experiment_name, key, field_type, raw_value):
        # Parse the stored raw value lazily, matching the canonical JS SDK:
        # text/string pass through, number -> int, boolean -> == "true",
        # json -> json.loads (with "null"/"" special-cases). Only here can a
        # malformed value produce an ERROR event, and only when accessed.
        if raw_value is None:
            return None

        if field_type is None:
            return raw_value

        if field_type.startswith("text") or field_type.startswith("string"):
            return raw_value

        if field_type.startswith("number"):
            try:
                return int(raw_value)
            except (ValueError, TypeError) as e:
                self.log_event(
                    EventType.ERROR,
                    f"Failed to parse number custom field {key}: {e}"
                )
                return None

        if field_type.startswith("boolean"):
            return raw_value == "true"

        if field_type.startswith("json"):
            if raw_value == "null":
                return None
            if raw_value == "":
                return ""
            try:
                import json as _json
                parsed = _json.loads(raw_value)
                if isinstance(parsed, (dict, list)):
                    return copy.deepcopy(parsed)
                return parsed
            except (ValueError, TypeError):
                self.log_event(
                    EventType.ERROR,
                    f"Failed to parse JSON custom field value '{key}' for experiment '{experiment_name}'"
                )
                return None

        self.log_event(
            EventType.ERROR,
            f"Unknown custom field type '{field_type}' for experiment '{experiment_name}' and key '{key}'"
        )
        return None

    def get_custom_field_value(self, experiment_name: str, key: str):
        return self._get_custom_field(experiment_name, key, 'value')

    def get_custom_field_value_type(self, experiment_name: str, key: str):
        return self._get_custom_field(experiment_name, key, 'type')

    def get_custom_field_type(self, experiment_name: str, key: str):
        return self.get_custom_field_value_type(experiment_name, key)

    def _build_audience_attributes(self):
        """Helper method to build audience attributes map from current attributes."""
        attrs = {}
        for attr in self.attributes:
            attrs[attr.name] = attr.value
        return attrs

    def _audience_matches(self, experiment: Experiment, assignment: Assignment):
        if experiment.audience is not None and len(experiment.audience) > 0:
            if self._attrs_seq > (assignment.attrs_seq or 0):
                attrs = self._build_audience_attributes()
                match = self.audience_matcher.evaluate(experiment.audience, attrs)
                new_audience_mismatch = not match.result if match is not None else False

                if new_audience_mismatch != assignment.audience_mismatch:
                    return False
        return True

    def get_assignment(self, experiment_name: str, exposed_at: int = None):
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
                elif experiment_name not in self.custom_assignments or \
                        self.custom_assignments[experiment_name] == \
                        assignment.variant:
                    if experiment_matches(experiment.data, assignment):
                        if self._audience_matches(experiment.data, assignment):
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

            if exposed_at:
                assignment.exposedAt = exposed_at

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
                        attrs = self._build_audience_attributes()
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
                                if experiment_name in self.custom_assignments:
                                    custom = self.custom_assignments[experiment_name]
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
                    assignment.attrs_seq = self._attrs_seq

            if experiment is not None and \
                    assignment.variant >= 0 and \
                    (assignment.variant < len(experiment.data.variants)):
                assignment.variables = experiment.variables[assignment.variant]

            self.assignment_cache[experiment_name] = assignment
            return assignment
        finally:
            self.context_lock.release_write()

    def check_ready(self, expect_not_closed: bool):
        if not self.is_ready():
            raise RuntimeError('ABsmartly Context is not yet ready.')
        elif expect_not_closed:
            self.check_not_closed()

    def get_experiment(self, experiment_name: str):
        try:
            self.data_lock.acquire_read()
            return self.index.get(experiment_name, None)
        finally:
            self.data_lock.release_read()

    def get_experiments(self):
        if not self.is_ready() or self.is_closed() or self.is_closing():
            return []

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
                           self.custom_assignments,
                           experiment_name, variant)

    def get_custom_assignment(self, experiment_name: str):
        return Concurrency.get_rw(self.context_lock,
                                  self.custom_assignments,
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
        experiments = Concurrency.get_rw(self.data_lock, self.index_variables, key)
        if experiments:
            return experiments[0]
        return None

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
                            self.closing_future.set_exception(res.exception())

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
            exposure.exposedAt = assignment.exposedAt or self.clock.millis()
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
