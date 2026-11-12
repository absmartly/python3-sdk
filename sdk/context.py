import copy
import logging
import math
import threading
import warnings
from concurrent.futures import CancelledError, Future, InvalidStateError
from typing import Optional

from sdk.audience_matcher import AudienceMatcher
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_error import ContextError, ContextValueError
from sdk.context_event_handler import ContextEventHandler  # noqa: F401
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
from sdk.utils import hash_unit, is_numeric
from sdk.variable_parser import VariableParser

logger = logging.getLogger(__name__)


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
        # Computed while the context's data had failed to load: a placeholder
        # that is recomputed once a refresh recovers the context.
        self.data_failed: bool = False
        self.rule_override: bool = False
        self.rule_variant = None
        self.rule_key = None


class ExperimentVariables:
    data: Optional[Experiment]
    variables: Optional[list[dict]]

class ContextCustomFieldValue:
    type: Optional[str]
    value: Optional[any]

def experiment_matches(experiment: Experiment, assignment: Assignment):
    # Same fields and ordered comparison as the JS SDK's experimentMatches
    # (context.ts _assign / arrayEqualsShallow): seeds, the variant split,
    # variant configs and the audience text are deliberately not compared, so
    # a cached assignment stays sticky across a refresh.
    return experiment.id == assignment.id and \
           experiment.unitType == assignment.unit_type and \
           experiment.iteration == assignment.iteration and \
           experiment.fullOnVariant == assignment.full_on_variant and \
           list(experiment.trafficSplit or []) == \
           list(assignment.traffic_split or [])


def _js_number(value):
    # JS Number(string): surrounding whitespace is ignored, an empty string is
    # 0, hex/octal/binary prefixes are accepted, and anything unparseable is
    # NaN, which this SDK reports as None (JSON.stringify(NaN) is null).
    text = str(value).strip()
    if text == "":
        return 0
    try:
        if text[:2].lower() in ("0x", "0o", "0b"):
            return int(text, 0)
        if "_" in text or any(c.isalpha() and c not in "eE" for c in text):
            if text.lstrip("+-") != "Infinity":
                return None
            return -math.inf if text.startswith("-") else math.inf
        number = float(text)
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number


def _chain(source: Future, target: Future):
    def copy_result(done: Future):
        if target.done():
            return
        error = _future_error(done)
        if error is None:
            target.set_result(None)
        else:
            target.set_exception(error)

    source.add_done_callback(copy_result)


def _future_error(future: Future):
    if future.cancelled():
        return CancelledError()
    return future.exception()


def _data_future_error(future: Future):
    error = _future_error(future)
    if error is None and future.result() is None:
        # DefaultContextDataDeserializer returns None for an invalid
        # response (as in v0.2.4); treat it as a failed load rather than
        # crashing in set_data and leaving readiness waiters hanging.
        return RuntimeError("Context data is missing or invalid")
    return error


class Context:
    def __init__(self,
                 clock: Clock, config: ContextConfig,
                 data_future: Future, data_provider: ContextDataProvider,
                 event_handler: ContextPublisher,
                 event_logger: ContextEventLogger,
                 variable_parser: VariableParser,
                 audience_matcher: AudienceMatcher,
                 application: Optional[str] = None,
                 environment: Optional[str] = None):
        self.clock = clock
        self.publish_delay = config.publish_delay
        self.refresh_interval = config.refresh_interval
        self.event_handler = event_handler
        self.event_logger = event_logger
        self.data_provider = data_provider
        self.variable_parser = variable_parser
        self.audience_matcher = audience_matcher
        self.historic = config.historic

        # The application and environment names configured in the SDK. The
        # context always evaluates audiences (and assignment-rule conditions)
        # with these, like the JS SDK; the collector already attaches them to
        # every event server-side, so they are not published here. A user-set
        # attribute with the same name always wins (see
        # _build_audience_attributes).
        self._system_attributes = {}
        if isinstance(application, str) and len(application) > 0:
            self._system_attributes["application"] = application
        if isinstance(environment, str) and len(environment) > 0:
            self._system_attributes["environment"] = environment

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
        self.flush_future: Optional[Future] = None
        self._close_lock = threading.Lock()

        self.refresh_timer: Optional[threading.Timer] = None
        self.refresh_stopped = False
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
                error = None if data.cancelled() else _data_future_error(data)
                if data.done() and data.cancelled() is False and \
                        error is None:
                    self.set_data(data.result())
                    self.log_event(EventType.READY, data.result())
                elif data.cancelled() is False and \
                        error is not None:
                    self.set_data_failed(error)
                    self.log_error(error)

            data_future.add_done_callback(when_finished)
        else:
            self.ready_future = Future()

            def when_finished(data: Future):
                error = None if data.cancelled() else _data_future_error(data)
                if data.done() and data.cancelled() is False and \
                        error is None:
                    # A pre-ready refresh may already have installed newer
                    # data; this older response must not replace it.
                    if self.set_data(data.result(), keep_ready=True):
                        # Log before settling, as the JS SDK does, so a
                        # caller woken by the future already sees the event.
                        self.log_event(EventType.READY, data.result())
                    self._settle_ready()

                    if self.get_pending_count() > 0:
                        self.set_timeout()
                elif data.cancelled() is False and \
                        error is not None:
                    # A refresh may already have made the context ready while
                    # this request was pending; its data and the events
                    # queued against it stay.
                    self.set_data_failed(error, keep_ready=True)
                    self.log_error(error)
                    self._settle_ready()

            data_future.add_done_callback(when_finished)

    def _settle_ready(self):
        ready_future = getattr(self, "ready_future", None)
        if ready_future is None:
            return
        try:
            ready_future.set_result(None)
        except InvalidStateError:
            pass

    @property
    def cassignments(self):
        warnings.warn(
            "'cassignments' is deprecated and will be removed in a future "
            "version. Use 'custom_assignments' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.custom_assignments

    @cassignments.setter
    def cassignments(self, value):
        warnings.warn(
            "'cassignments' is deprecated and will be removed in a future "
            "version. Use 'custom_assignments' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.custom_assignments = value

    def set_units(self, units: dict):
        for key, value in units.items():
            self.set_unit(key, value)

    def set_unit(self, unit_type: str, uid):
        self.check_not_closed()

        # Like the JS SDK (context.ts unit()), a numeric UID is kept as a
        # number and only rendered to text when hashed.
        if isinstance(uid, str):
            uid = uid.strip()
            if len(uid) == 0:
                raise ContextValueError(
                    "Unit UID must not be blank.",
                    f"Unit '{unit_type}' UID must not be blank.")
        elif not is_numeric(uid):
            raise ValueError(
                f"Unit '{unit_type}' must be a string or a number.")

        try:
            self.context_lock.acquire_write()

            if unit_type in self.units.keys() and self.units[unit_type] != uid:
                raise ContextValueError(
                    "Unit already set.",
                    f"Unit '{unit_type}' UID already set.")

            self.units[unit_type] = uid
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
            raise ContextError('ABSmartly Context is closed',
                               'ABsmartly Context is finalized.')
        elif self.closing.value:
            raise ContextError('ABSmartly Context is closing',
                               'ABsmartly Context is finalizing.')

    def set_data(self, data: ContextData, keep_ready=False):
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

                        # v0.2.4's parser contract is Optional[dict]: any
                        # other JSON value would index its characters or
                        # elements as variable keys.
                        if not isinstance(variables, dict):
                            self.log_event(
                                EventType.ERROR,
                                f"Failed to parse variant config for {experiment.name}/{variant.name}"
                            )
                            experiment_variables.variables.append({})
                            continue

                        for key in variables:
                            # Kept sorted by experiment id, like the JS SDK's
                            # insertUniqueSorted, so variable lookups visit
                            # experiments in a stable order.
                            entries = index_variables.setdefault(key, [])
                            if experiment_variables not in entries:
                                position = len(entries)
                                while position > 0 and \
                                        entries[position - 1].data.id > \
                                        experiment.id:
                                    position -= 1
                                entries.insert(position,
                                               experiment_variables)
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
            if keep_ready and self.data is not None and not self.failed:
                return False

            self.index = index
            self.index_variables = index_variables
            self.context_custom_fields = context_custom_fields
            self.data = data
            self.ready_error = None

            if self.failed:
                # Exposures queued while the context had no data are control
                # placeholders for experiments it could not see; drop them,
                # as a failed context would have. Goals are real and stay
                # queued. Done under event_lock in the same step that clears
                # failed, so exposures queued against the recovered data are
                # never dropped, and queue_exposure rejects a placeholder that
                # arrives after the switch.
                try:
                    self.event_lock.acquire_write()
                    self.pending_count.set(
                        self.pending_count.get() - len(self.exposures))
                    self.exposures.clear()
                    self.failed = False
                finally:
                    self.event_lock.release_write()

            self.set_refresh_timer()
            return True
        finally:
            self.data_lock.release_write()

    def set_refresh_timer(self):
        if self.refresh_interval <= 0:
            return

        def arm(timer):
            # Checked under timeout_lock, the lock close() clears the timer
            # under, so a refresh finishing after close cannot re-arm it.
            # refresh_stopped also covers a close whose final publish failed:
            # the context reopens, but a refresh outstanding at close must
            # not restart polling when it completes.
            try:
                self.timeout_lock.acquire_write()
                if timer is not self.refresh_timer or self.refresh_stopped \
                        or self.is_closing() or self.is_closed():
                    return
                self.refresh_timer = threading.Timer(self.refresh_interval, ref)
                self.refresh_timer.daemon = True
                self.refresh_timer.start()
            finally:
                self.timeout_lock.release_write()

        def ref():
            timer = self.refresh_timer
            if self.is_closed() or self.is_closing():
                return
            try:
                self.refresh_async()
            except RuntimeError:
                return
            arm(timer)

        if self.refresh_timer is None:
            arm(None)

    def set_timeout(self):
        if self.is_ready() and self.publish_delay >= 0:
            if self.timeout is None:
                try:
                    self.timeout_lock.acquire_write()

                    def flush():
                        self.flush()

                    self.timeout = threading.Timer(self.publish_delay, flush)
                    self.timeout.daemon = True
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
        # As in v0.2.4, refresh only requires an open context: it works
        # before ready, and a context whose first fetch failed re-fetches and
        # recovers (set_data clears the failed state).
        self.check_not_closed()

        if self.refreshing.compare_and_set(False, True):

            refresh_future = Future()
            self.refresh_future = refresh_future

            def when_ready(data):
                error = _data_future_error(data)
                if error is None:
                    try:
                        self.set_data(data.result())
                    except Exception as e:
                        error = e
                self.refreshing.set(False)
                if error is None:
                    self.log_event(EventType.REFRESH, data.result())
                    # A refresh before the initial fetch settled makes the
                    # context ready: wake its readiness waiters too.
                    self._settle_ready()
                    if self.get_pending_count() > 0:
                        self.set_timeout()
                    refresh_future.set_result(None)
                else:
                    self.log_error(error)
                    refresh_future.set_exception(error)

            try:
                data_future = self.data_provider.get_context_data()
                if data_future is None:
                    raise RuntimeError(
                        "ContextDataProvider.get_context_data() returned None")
            except Exception as e:
                data_future = Future()
                data_future.set_exception(e)
            data_future.add_done_callback(when_ready)

        if self.refresh_future is not None:
            return self.refresh_future
        else:
            result = Future()
            result.set_result(None)
            return result

    def set_data_failed(self, exception, keep_ready=False):
        try:
            self.data_lock.acquire_write()
            if keep_ready and self.data is not None and not self.failed:
                return
            self.index = {}
            self.index_variables = {}
            self.data = ContextData()
            self.failed = True
            self.ready_error = exception
        finally:
            self.data_lock.release_write()

    def log_error(self, exception):
        self.log_event(EventType.ERROR, exception)

    def log_event(self, event: EventType, data: object):
        # A throwing event logger must never change SDK control flow (a
        # successful publish reported as failed, a future left unresolved),
        # the same as the JS SDK's _logEvent/_logError.
        if self.event_logger is not None:
            try:
                self.event_logger.handle_event(event, data)
            except Exception:
                logger.exception("ABsmartly event logger raised on %s", event)

    def get_pending_count(self):
        return self.pending_count.get()

    def flush(self):
        self.clear_timeout()

        result = Future()
        # Internal coordination uses its own future so a caller cancelling
        # the returned one cannot corrupt the in-flight bookkeeping.
        internal = Future()
        discarded = None
        try:
            self.event_lock.acquire_write()

            in_flight = self.flush_future
            if in_flight is not None:
                # A publish is in flight and has already drained the queue.
                # Wait for it to settle (it re-queues its batch on failure)
                # before looking at the queue again, as the JS SDK does with
                # _flushPromise, so close() never acts on a queue that only
                # looks empty.
                def retry(_):
                    _chain(self.flush(), result)

                in_flight.add_done_callback(retry)
                return result

            event_count = self.pending_count.get()
            if event_count == 0:
                result.set_result(None)
                return result

            if self.failed:
                discarded = RuntimeError(
                    f"Discarding {len(self.exposures)} exposures and "
                    f"{len(self.achievements)} goals because context failed "
                    f"to initialize")
                self.exposures.clear()
                self.achievements.clear()
                self.pending_count.set(0)

            if discarded is None:
                exposures = list(self.exposures) if self.exposures else None
                achievements = list(self.achievements) \
                    if self.achievements else None
                self.exposures.clear()
                self.achievements.clear()
                self.pending_count.set(0)
                # Registered in the same critical section as the drain, so a
                # concurrent flush or close always sees this publish in flight.
                self.flush_future = internal
        finally:
            self.event_lock.release_write()

        if discarded is not None:
            self.log_error(discarded)
            result.set_result(None)
            return result

        def restore():
            try:
                self.event_lock.acquire_write()
                if exposures:
                    self.exposures = exposures + self.exposures
                if achievements:
                    self.achievements = achievements + self.achievements
                self.pending_count.set(self.pending_count.get() + event_count)
            finally:
                self.event_lock.release_write()

        def settle(error):
            if error is not None:
                restore()
            try:
                self.event_lock.acquire_write()
                if self.flush_future is internal:
                    self.flush_future = None
            finally:
                self.event_lock.release_write()
            if error is None:
                self.log_event(EventType.PUBLISH, event)
                internal.set_result(None)
            else:
                self.log_error(error)
                internal.set_exception(error)
            _chain(internal, result)

        try:
            event = self._build_publish_event(exposures, achievements)
            publish_future = self.event_handler.publish(self, event)
            if publish_future is None:
                raise RuntimeError("ContextPublisher.publish() returned None")
        except Exception as e:
            event = None
            settle(e)
            return result

        publish_future.add_done_callback(
            lambda data: settle(_future_error(data)))
        return result

    def _build_publish_event(self, exposures, achievements):
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
        return event

    def close(self):
        try:
            self.close_async().result()
        except Exception as e:
            # The failed flush already logged this error; JS logs it once.
            self.close_error = e
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

        # Like v0.2.4, anything dict() accepts (a Mapping, MappingProxyType,
        # a list of pairs) is converted; only unconvertible values raise.
        if properties is not None:
            try:
                if isinstance(properties, (str, bytes)):
                    raise TypeError
                properties = dict(properties)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Goal '{goal_name}' properties must be of type object.")

        achievement = GoalAchievement()
        achievement.achievedAt = achieved_at or self.clock.millis()
        achievement.name = goal_name
        achievement.properties = properties

        try:
            self.event_lock.acquire_write()
            # Re-checked under the lock close() drains the queue under, so a
            # goal cannot be queued after the final flush and be stranded.
            self.check_not_closed()
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
            self.refresh_stopped = True
            if self.refresh_timer is not None:
                self.refresh_timer.cancel()
                self.refresh_timer = None
        finally:
            self.timeout_lock.release_write()

    def get_variable_value(self, key: str, default_value: object):
        self.check_ready(True)
        return self._variable_value(key, default_value, True)

    def peek_variable_value(self, key: str, default_value: object):
        self.check_ready(True)
        return self._variable_value(key, default_value, False)

    def _variable_value(self, key: str, default_value: object, expose: bool):
        # Port of the JS SDK's _variableValue/_peekVariable: walk every
        # experiment defining the key (sorted by id) and return the value from
        # the first one the unit is assigned to or overridden in, queuing an
        # exposure for each experiment visited on the way.
        experiments = Concurrency.get_rw(
            self.data_lock, self.index_variables, key) or []
        for experiment in list(experiments):
            assignment = self.get_assignment(experiment.data.name)
            if assignment.variables is not None:
                if expose and not assignment.exposed.value:
                    self.queue_exposure(assignment)

                if key in assignment.variables and \
                        (assignment.assigned or assignment.overridden):
                    return assignment.variables[key]
        return default_value

    def peek_treatment(self, experiment_name: str):
        self.check_ready(True)

        return self.get_assignment(experiment_name).variant

    def get_unit_hash(self, unit_type: str, unit_uid):
        def computer(key: str):
            return hash_unit(unit_uid).encode('ascii')

        return Concurrency.compute_if_absent_rw(
            self.context_lock,
            self.hashed_units,
            unit_type,
            computer)

    def get_treatment(self, experiment_name: str, exposed_at: int = None):
        self.check_ready(True)
        assignment = self.get_assignment(experiment_name, exposed_at=exposed_at)
        if not assignment.exposed.value:
            self.queue_exposure(assignment)
        return assignment.variant

    def get_variable_keys(self):
        """Map each variable key to the name of one experiment defining it.

        Same shape as v0.2.4. When several experiments define a key, the
        one with the lowest id is returned (the first one variable lookups
        visit); use get_variable_keys_all() for every experiment.
        """
        return {key: experiments[0]
                for key, experiments in self.get_variable_keys_all().items()
                if experiments}

    def get_variable_keys_all(self):
        """Map each variable key to the names of every experiment defining
        it, in experiment id order, like the JS SDK's variableKeys()."""
        self.check_ready(True)

        variable_keys = {}
        try:
            self.data_lock.acquire_read()
            for key, experiments in self.index_variables.items():
                variable_keys[key] = [expr_var.data.name for expr_var in experiments]
        finally:
            self.data_lock.release_read()

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
            self.data_lock.release_read()

        keys = list(set(keys))
        keys.sort()

        return keys

    def _get_custom_field(self, experiment_name: str, key: str, field_attr: str):
        self.check_ready(True)

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
        # text/string pass through, number -> JS Number(), boolean -> == "true",
        # json -> configured variable parser (with "null"/"" special-cases). Only here can a
        # malformed value produce an ERROR event, and only when accessed.
        if raw_value is None:
            return None

        if field_type is None:
            return raw_value

        if field_type.startswith("text") or field_type.startswith("string"):
            return raw_value

        if field_type.startswith("number"):
            return _js_number(raw_value)

        if field_type.startswith("boolean"):
            return raw_value == "true"

        if field_type.startswith("json"):
            if raw_value == "null":
                return None
            if raw_value == "":
                return ""
            try:
                parsed = self.variable_parser.parse(
                    self, experiment_name, key, raw_value)
                if parsed is None:
                    raise ValueError("invalid JSON")
                if isinstance(parsed, (dict, list)):
                    return copy.deepcopy(parsed)
                return parsed
            except Exception:
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
        """Build the attribute map audiences and assignment-rule conditions
        are evaluated against.

        System values (``application`` / ``environment``) go in first, then
        user-set attributes overlay them, so a value the caller sets with the
        same name always wins, even one set after the context was created
        (the ``_attrs_seq`` bump invalidates a cached assignment). These
        system attributes are never published; the collector adds them to
        every event server-side.
        """
        attrs = dict(self._system_attributes)
        for attr in self.attributes:
            attrs[attr.name] = attr.value
        return attrs

    def _audience_matches(self, experiment: Experiment, assignment: Assignment):
        if experiment.audience is not None and len(experiment.audience) > 0:
            attrs_seq = self._attrs_seq
            if attrs_seq > (assignment.attrs_seq or 0):
                attrs = self._build_audience_attributes()
                match = self.audience_matcher.evaluate(experiment.audience, attrs)
                new_audience_mismatch = not match.result if match is not None else False

                if new_audience_mismatch != assignment.audience_mismatch:
                    return False, None
                return True, attrs_seq
        return True, None

    def get_assignment(self, experiment_name: str, exposed_at: int = None):
        checked_seq = None
        try:
            self.context_lock.acquire_read()

            if experiment_name in self.assignment_cache:
                assignment: Assignment = self.assignment_cache[experiment_name]

                experiment, failed = self._get_experiment_state(
                    experiment_name)

                if assignment.data_failed and not failed:
                    # Computed before a refresh recovered the context; its
                    # placeholder exposure was dropped, so recompute.
                    pass
                elif experiment_name in self.overrides:
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
                        rule = experiment.data.assignmentRules
                        rule_current = assignment.rule_key
                        rule_variant = assignment.rule_variant
                        if rule != rule_current or self._attrs_seq > (assignment.attrs_seq or 0):
                            action = self.audience_matcher.evaluate_rules(
                                rule, self._build_audience_attributes()) if rule else None
                            rule_variant = action.get("variant") if action and action["type"] == "assign" else None
                        if rule_variant == assignment.rule_variant:
                            matches, checked_seq = self._audience_matches(
                                experiment.data, assignment)
                            if matches:
                                if checked_seq is None:
                                    return assignment
                        else:
                            checked_seq = None
        finally:
            self.context_lock.release_read()

        if checked_seq is not None:
            # The audience result is unchanged: record the sequence it was
            # checked at (JS sets assignment.attrsSeq), so later reads skip
            # the re-evaluation. Done under the write lock, after releasing
            # the read lock, since concurrent readers cannot all upgrade.
            try:
                self.context_lock.acquire_write()
                if (assignment.attrs_seq or 0) < checked_seq:
                    assignment.attrs_seq = checked_seq
            finally:
                self.context_lock.release_write()
            return assignment

        try:
            self.context_lock.acquire_write()
            experiment, failed = self._get_experiment_state(experiment_name)
            assignment = Assignment()
            assignment.name = experiment_name
            assignment.eligible = True
            assignment.data_failed = failed

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

                    action = self.audience_matcher.evaluate_rules(
                        rule, self._build_audience_attributes()) if rule else None
                    rule_variant = action.get("variant") if action and action["type"] == "assign" else None
                    assignment.rule_key = rule
                    assignment.rule_variant = rule_variant
                    if action is not None and action["type"] == "assign" and \
                            0 <= rule_variant < len(experiment.data.variants):
                        assignment.variant = rule_variant
                        assignment.rule_override = True
                    elif experiment.data.audience is not None and \
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
            raise ContextError('ABSmartly Context is not yet ready',
                               'ABsmartly Context is not yet ready.')
        elif expect_not_closed:
            self.check_not_closed()

    def get_experiment(self, experiment_name: str):
        try:
            self.data_lock.acquire_read()
            return self.index.get(experiment_name, None)
        finally:
            self.data_lock.release_read()

    def _get_experiment_state(self, experiment_name: str):
        # The experiment and the failed flag, read together so an assignment
        # knows whether it was computed against failed data.
        try:
            self.data_lock.acquire_read()
            return self.index.get(experiment_name, None), self.failed
        finally:
            self.data_lock.release_read()

    def get_experiments(self):
        self.check_ready(False)

        try:
            self.data_lock.acquire_read()
            experiment_names = []
            for experiment in self.data.experiments:
                experiment_names.append(experiment.name)

            return experiment_names
        finally:
            self.data_lock.release_read()

    def get_data(self):
        self.check_ready(False)

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
        with self._close_lock:
            if self.closed.value:
                result = Future()
                result.set_result(None)
                return result
            if self.closing_future is not None:
                return self.closing_future
            closing_future = Future()
            self.closing_future = closing_future
            self.closing.set(True)

        self.clear_refresh_timer()

        def accept(res: Future):
            error = _future_error(res)
            with self._close_lock:
                self.closing_future = None
                if error is None:
                    self.closed.set(True)
                # A failed final publish leaves the context open with its
                # events queued so close() can be retried (JS _finalize). The
                # refresh timer stays cleared, as in JS: the caller has moved
                # on and must not be left polling /context.
                self.closing.set(False)
            if error is None:
                # CLOSE is the v0.2.4 event; FINALIZE is the cross-SDK name.
                self.log_event(EventType.CLOSE, None)
                self.log_event(EventType.FINALIZE, None)
                closing_future.set_result(None)
            else:
                closing_future.set_exception(error)

        self.flush().add_done_callback(accept)
        return closing_future

    def queue_exposure(self, assignment: Assignment):
        try:
            self.event_lock.acquire_write()
            # Only mark the assignment exposed once the queue accepts the
            # exposure: a context that started closing rejects it instead.
            self.check_not_closed()
            if assignment.data_failed and not self.failed:
                # A placeholder computed before recovery: its experiment is
                # now known, so the next read recomputes and exposes it.
                return
            if not assignment.exposed.compare_and_set(False, True):
                return
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
            exposure.ruleOverride = assignment.rule_override

            self.pending_count.increment_and_get()
            self.exposures.append(exposure)
        finally:
            self.event_lock.release_write()

        self.log_event(EventType.EXPOSURE, exposure)
        self.set_timeout()
