import copy
import logging
import math
import threading
import warnings
from collections.abc import Mapping
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
from sdk.version import NAME as SDK_NAME, VERSION as SDK_VERSION
from sdk.variable_parser import VariableParser

logger = logging.getLogger(__name__)


# Resolutions get_treatment and variable lookups try when set_unit keeps
# retiring the assignment they resolved, as in the Java SDK.
_MAX_EXPOSURE_ATTEMPTS = 3


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
        self.rule_key: Optional[str] = None
        self.rule_variant: Optional[int] = None
        self.rule_missing_unit: bool = False
        # Holdouts (see Context._resolve_holdouts): the experiment's
        # applicable holdouts when the assignment was resolved, the holdout
        # assignment pinned for each (None while the unit was missing), and
        # whether any of them holds the unit out.
        self.suppressed: bool = False
        self.holdouts: Optional[list] = None
        self.holdout_assignments: Optional[list] = None
        # On a holdout's own assignment: len(split) when `variant` was
        # resolved, which gives the arm its meaning (see _is_held_out_by).
        self.holdout_arm_count: Optional[int] = None
        # Evicted by set_unit before it was exposed: a caller still holding
        # it must not expose it (see Context._expose).
        self.retired: bool = False
        # A holdout exposure a queue_exposure override is handling.
        self.hook_pending: bool = False
        # Set while a queue_exposure override has not yet been offered every
        # holdout exposure of this assignment, so a later read of the same
        # experiment finishes them (e.g. after a failed close reopens).
        self.holdouts_pending: bool = False
        # Set once every pinned arm is exposed; pinned arms never change,
        # so it is never cleared (see Context._expose_holdouts).
        self.holdouts_exposed: bool = False


class ExperimentVariables:
    data: Optional[Experiment]
    variables: Optional[list[dict]]
    # The holdouts covering the experiment, sorted by id; None when it has
    # none (or none of its holdoutIds names a usable holdout).
    holdouts: Optional[list] = None


class _Holdout:
    __slots__ = ("id", "name", "iteration", "seed_hi", "seed_lo", "split")

    def __init__(self, id, name, iteration, seed_hi, seed_lo, split):
        self.id = id
        self.name = name
        self.iteration = iteration
        self.seed_hi = seed_hi
        self.seed_lo = seed_lo
        self.split = split

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


def _field(entry, name, default=None):
    # A holdout entry is a Mapping (how the default deserializer keeps it)
    # or any object with the same attributes, like sdk.json.holdout.Holdout.
    if isinstance(entry, Mapping):
        return entry.get(name, default)
    return getattr(entry, name, default)


def _int_id(value):
    # Ids, seeds: JSON numbers that are integers; booleans are not numbers.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _parse_holdout(entry):
    """A usable _Holdout for a ContextData.holdouts entry, or None.

    Like the JS SDK (context.ts _init), an entry without a non-empty split is
    ignored; so is one whose id, seeds or split are not numbers, which JS
    would hash into garbage. Unknown keys are ignored.
    """
    if entry is None or isinstance(entry, (str, bytes, int, float, list)):
        return None
    holdout_id = _int_id(_field(entry, "id"))
    split = _field(entry, "split")
    if holdout_id is None or not isinstance(split, (list, tuple)) or \
            len(split) == 0 or \
            any(isinstance(x, bool) or not isinstance(x, (int, float))
                for x in split):
        return None
    seed_hi = _field(entry, "seedHi")
    seed_lo = _field(entry, "seedLo")
    seed_hi = 0 if seed_hi is None else _int_id(seed_hi)
    seed_lo = 0 if seed_lo is None else _int_id(seed_lo)
    if seed_hi is None or seed_lo is None:
        return None
    return _Holdout(holdout_id, _field(entry, "name"),
                    _field(entry, "iteration", 0), seed_hi, seed_lo,
                    tuple(split))


def _index_holdouts(holdouts):
    # JS indexes by id with the last entry winning.
    holdouts_by_id = {}
    if isinstance(holdouts, (list, tuple)):
        for entry in holdouts:
            holdout = _parse_holdout(entry)
            if holdout is not None:
                holdouts_by_id[holdout.id] = holdout
    return holdouts_by_id


def _applicable_holdouts(holdout_ids, holdouts_by_id):
    # The experiment's holdouts, deduplicated and sorted by id like the JS
    # SDK's insertUniqueSorted; ids naming no usable holdout are ignored.
    if not isinstance(holdout_ids, (list, tuple)):
        return None
    resolved = {}
    for holdout_id in holdout_ids:
        holdout = holdouts_by_id.get(_int_id(holdout_id))
        if holdout is not None:
            resolved[holdout.id] = holdout
    if not resolved:
        return None
    return [resolved[key] for key in sorted(resolved)]


def _is_held_out_by(holdout_variant, holdout_arm_count, full_on_variant):
    # JS isHeldOutBy: arm 0 always holds the experiment out; in a 3-arm
    # holdout arm 1 holds out only experiments that are not full-on. The
    # arity comes from the split, never from holdoutType.
    if holdout_variant == 0:
        return True
    if holdout_arm_count == 3 and holdout_variant == 1:
        return full_on_variant == 0
    return False


def _holdout_set_matches(experiment, assignment: Assignment):
    # JS holdoutSetMatches: (id, iteration) per holdout, in order. A seed or
    # split edit in the same iteration must not re-resolve (and re-expose).
    fresh = experiment.holdouts
    pinned = assignment.holdouts
    if fresh is None and pinned is None:
        return True
    fresh = fresh or ()
    pinned = pinned or ()
    if len(fresh) != len(pinned):
        return False
    for fresh_holdout, pinned_holdout in zip(fresh, pinned):
        if fresh_holdout.id != pinned_holdout.id or \
                fresh_holdout.iteration != pinned_holdout.iteration:
            return False
    return True


def _same_holdouts(previous, holdouts):
    if previous is None or holdouts is None:
        return previous is holdouts
    return len(previous) == len(holdouts) and all(
        (a.id, a.iteration, a.name) == (b.id, b.iteration, b.name)
        for a, b in zip(previous, holdouts))


def _rule_key(experiment: Experiment):
    # The assignment rules a cached assignment was checked against; no rules
    # (None or "") are the same key, like the JS SDK's ruleKey. The
    # environment is fixed per context, so unlike JS it is not part of it.
    return experiment.assignmentRules or ""


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
        self.include_system_attributes = config.include_system_attributes

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
        # Bumped by set_unit whenever a unit is added (and unexposed
        # assignments for it are retired), so a variable read can tell that
        # a unit arrived during its walk.
        self._units_seq = 0
        self.index = {}
        self.index_variables = {}
        self.context_custom_fields = {}
        self.assignment_cache = {}
        self._parsed_rules = {}
        # Holdouts by id from the installed data, and each holdout's own
        # assignment per (holdout id, unit type), kept across refreshes and
        # valid while the holdout's iteration is unchanged.
        self._holdouts_by_id = {}
        self._holdout_assignments = {}
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

            added = unit_type not in self.units
            self.units[unit_type] = uid
            if added:
                self._units_seq += 1
                # Like the JS SDK's unit(): an unexposed assignment for this
                # unit type was resolved while the unit was missing, so drop
                # it and let the next read resolve it with the unit. Exposed
                # ones are kept, as re-resolving would expose them twice.
                for name, assignment in list(self.assignment_cache.items()):
                    if assignment.unit_type == unit_type and \
                            self._retire(assignment):
                        del self.assignment_cache[name]
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
        holdouts_by_id = _index_holdouts(getattr(data, "holdouts", None))
        previous_index = self.index if holdouts_by_id else None

        for experiment in data.experiments:
            experiment_variables = ExperimentVariables()
            experiment_variables.data = experiment
            experiment_variables.variables = []
            if holdouts_by_id:
                holdouts = _applicable_holdouts(
                    getattr(experiment, "holdoutIds", None), holdouts_by_id)
                previous = previous_index.get(experiment.name)
                if previous is not None and \
                        _same_holdouts(previous.holdouts, holdouts):
                    holdouts = previous.holdouts
                experiment_variables.holdouts = holdouts

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
            self._holdouts_by_id = holdouts_by_id
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
            self._holdouts_by_id = {}
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
        if self.include_system_attributes:
            # Stamped with the earliest event in the batch, like JS: the
            # collector only applies attributes with setAt <= an event's time.
            now = min([event.publishedAt] +
                      [e.exposedAt for e in exposures or []
                       if e.exposedAt is not None] +
                      [a.achievedAt for a in achievements or []
                       if a.achievedAt is not None])
            system = []
            # Only the SDK metadata: application and environment are
            # evaluation-only, the collector adds them server-side.
            for name, value in (("sdk_name", SDK_NAME),
                                ("sdk_version", SDK_VERSION)):
                attr = Attribute()
                attr.name = name
                attr.value = value
                attr.setAt = now
                system.append(attr)
            user_attributes = {attribute.name for attribute in (event.attributes or [])}
            event.attributes = [attribute for attribute in system
                                if attribute.name not in user_attributes] + \
                (event.attributes or [])
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

    def _variable_value(self, key: str, default_value: object, expose: bool,
                        attempt: int = 1, offered=None):
        retry = attempt < _MAX_EXPOSURE_ATTEMPTS
        if offered is None and expose:
            # Holdout arms this public read offered a queue_exposure
            # override, kept across attempts so a declined arm is offered
            # once per read (the next read offers it again).
            offered = set()
        assignment, invalidated, deferred = self._variable_assignment(
            key, expose, retry, offered)
        if invalidated:
            if retry:
                # set_unit added a unit or a refresh replaced the data during
                # the walk, so the key may resolve differently: walk it again
                # before exposing any experiment (peek too, so it never
                # returns a value no single state would give).
                return self._variable_value(key, default_value, expose,
                                            attempt + 1, offered)
            # Out of attempts and still not one coherent state: neither
            # payload alone gave this winner, so return the default and
            # expose nothing.
            return default_value
        if expose and assignment is not None and \
                not assignment.exposed.value and \
                not self._expose_winner(assignment):
            if retry:
                # set_unit retired the winner in between: walk it again.
                return self._variable_value(key, default_value, expose,
                                            attempt + 1, offered)
            # Out of attempts with the winner still retired: like an
            # invalidated walk, return the default rather than the value of
            # a winner that was never exposed.
            return default_value
        for loser in deferred:
            # Losers whose shared arms were left for the winner's section:
            # once those are exposed, later reads skip them.
            if not self._holdouts_unexposed(loser):
                loser.holdouts_exposed = True
                loser.holdouts_pending = False
        if assignment is not None and assignment.variables is not None and \
                key in assignment.variables:
            return assignment.variables[key]
        return default_value

    def _expose_winner(self, assignment: Assignment):
        # The built-in queue accepts the winner and its holdouts in one
        # event_lock section (holdouts first, as on the walk), so a close
        # cannot publish one without the other. A queue_exposure override
        # was already offered the holdouts by the walk.
        if getattr(self.queue_exposure, "__func__", None) is \
                Context.queue_exposure:
            return self._expose(assignment, holdouts_first=True)
        return self._expose(assignment, offer_holdouts=False)

    def _variable_assignment(self, key: str, expose: bool,
                             retry: bool = False, offered=None):
        # Port of the Java SDK's getVariableAssignment: the candidates are
        # the experiments defining the key in any variant, in id order, and
        # the first one the unit is assigned to, overridden in or
        # rule-assigned to wins. Only the winner is exposed, by the caller:
        # a candidate that was checked and lost publishes no exposure of its
        # own, though its holdouts still fire, whether or not anything wins
        # (a held-out unit and a not held-out one fire the same holdouts).
        # The winner's variant decides alone: if it lacks the key, the
        # caller gets the default and later candidates are not consulted. A
        # held-out candidate never wins over another, but when none wins the
        # first held-out one supplies its control variant (and is exposed).
        # A raising queue_exposure hook does not stop the walk: the first
        # error is raised once every visited candidate was offered, as in
        # Java. Returns the winner, whether set_unit added a unit or a
        # refresh replaced the data during the walk (which makes the caller
        # walk again or, out of attempts, return the default; an invalidated
        # walk offers no holdouts), and the losers whose shared holdout arms
        # were left for the winner's exposure.
        units_seq = self._units_seq
        try:
            # The write side, like Concurrency.get_rw: this lock's read side
            # costs more for a single short section.
            self.data_lock.acquire_write()
            index = self.index
            experiments = self.index_variables.get(key) or []
        finally:
            self.data_lock.release_write()
        winner = None
        suppressed_fallback = None
        pending = None
        deferred = ()
        for experiment in list(experiments):
            assignment = self.get_assignment(experiment.data.name)
            # A refresh removed the indexed experiment after the index was
            # read: neither its placeholder (id 0) nor a cached override of it
            # may win. The identity check keeps warm reads lock-free.
            if (assignment.id == 0 or self.index is not index) and \
                    self.get_experiment(experiment.data.name) is None:
                continue
            if expose and assignment.holdout_assignments is not None and \
                    not assignment.holdouts_exposed:
                pending = pending or []
                pending.append(assignment)
            if assignment.assigned or assignment.overridden or \
                    assignment.rule_override:
                winner = assignment
                break
            if assignment.suppressed and suppressed_fallback is None:
                suppressed_fallback = assignment
        else:
            winner = suppressed_fallback
        # A unit added during the walk may have retired a candidate it had
        # already passed (a missing-unit loser that could now win), and a
        # refresh may have removed one that still won from its cached
        # override: either way the caller walks again.
        invalidated = self._units_seq != units_seq or self.index is not index
        if pending and not invalidated:
            native = getattr(self.queue_exposure, "__func__", None) is \
                Context.queue_exposure
            if native and winner is not None and \
                    winner.holdout_assignments is not None:
                # The winner's holdouts, and any arm a loser shares with it,
                # are accepted with the winner (see _expose_winner), so a
                # close a logger starts on a shared arm cannot publish it
                # without the winner. A shared arm is therefore published in
                # the winner's section (still before the winner's own
                # exposure), after the losers' other arms: holdout order
                # within a read is not guaranteed.
                staged = {id(arm) for arm in winner.holdout_assignments
                          if arm is not None}
            else:
                staged = ()
            failure = None
            for candidate in pending:
                try:
                    self._expose_holdouts(candidate, offered, staged)
                except Exception as error:
                    if failure is None:
                        failure = error
                if staged and not candidate.holdouts_exposed:
                    deferred = deferred or []
                    deferred.append(candidate)
            if failure is not None:
                raise failure
            # A queue_exposure override may have added a unit while it was
            # offered the holdouts.
            invalidated = self._units_seq != units_seq or \
                self.index is not index
        return winner, invalidated, deferred

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
        if (not assignment.exposed.value or assignment.holdouts_pending) and \
                not self._expose(assignment):
            for _ in range(_MAX_EXPOSURE_ATTEMPTS - 1):
                assignment = self.get_assignment(experiment_name,
                                                 exposed_at=exposed_at)
                if assignment.exposed.value or self._expose(assignment):
                    break
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

    def _resolve_rule(self, experiment: Experiment,
                      unit_pinned_missing: bool = False):
        """The variant the first matching assignment rule selects and whether
        it is the no-unit result, or (None, False)
        when no rule matches or the matching rule does not fit the
        experiment (a variant out of range or a split of the wrong length).
        Like the JS SDK's _resolveRule, a split whose unit is not set (or is
        pinned as missing) selects the experiment's no-unit result, its
        fullOnVariant."""
        if not experiment.assignmentRules:
            return None, False
        # Parsed once per rules text, like JS's entry.rules; only a refresh
        # that changes the text parses it again.
        cached = self._parsed_rules.get(experiment.name)
        if cached is None or cached[0] != experiment.assignmentRules:
            cached = (experiment.assignmentRules,
                      self.audience_matcher.parse_rules(
                          experiment.assignmentRules))
            self._parsed_rules[experiment.name] = cached
        if cached[1] is None:
            return None, False
        action = self.audience_matcher.evaluate_parsed_rules(
            cached[1],
            self._system_attributes.get("environment"),
            self._build_audience_attributes())
        if action is None:
            return None, False
        variant_count = len(experiment.variants or [])
        if action.variant is not None:
            if 0 <= action.variant < variant_count:
                return action.variant, False
            return None, False
        unit_type = experiment.unitType
        if len(action.split) != variant_count:
            return None, False
        if unit_pinned_missing or unit_type not in self.units:
            return experiment.fullOnVariant, True
        unit_hash = self.get_unit_hash(unit_type, self.units[unit_type])
        assigner = self.get_variant_assigner(unit_type, unit_hash)
        return assigner.assign(action.split, experiment.seedHi,
                               experiment.seedLo), False

    def _rules_and_audience_match(self, experiment: Experiment,
                                  assignment: Assignment):
        # Like the JS SDK's audienceMatches: once attributes change, a cached
        # assignment stays valid only while the rule outcome and (for an
        # assignment no rule selected) the audience result are unchanged.
        if experiment.assignmentRules:
            # An exposed split resolved without its unit keeps resolving as
            # if the unit were still missing, so a unit set afterwards cannot
            # switch the variant the user already saw.
            pinned = assignment.exposed.value and assignment.rule_missing_unit
            rule_variant, missing_unit = self._resolve_rule(
                experiment, pinned)
            if rule_variant != assignment.rule_variant:
                return False
            assignment.rule_missing_unit = missing_unit
        # Like JS audienceMatches, a held-out assignment is checked too: a
        # changed result rebuilds it from the current payload.
        if not assignment.rule_override and \
                experiment.audience is not None and \
                len(experiment.audience) > 0:
            attrs = self._build_audience_attributes()
            match = self.audience_matcher.evaluate(experiment.audience, attrs)
            new_audience_mismatch = not match.result if match is not None else False
            if new_audience_mismatch != assignment.audience_mismatch:
                return False
        return True

    def get_assignment(self, experiment_name: str, exposed_at: int = None):
        checked_seq = None
        fill = None
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
                    # Kept across refreshes, as in JS, so removing, restoring
                    # or re-identifying the experiment does not expose it
                    # again; only a placeholder (id 0) cached while the
                    # experiment was missing is recomputed once a refresh
                    # adds it.
                    if assignment.overridden and \
                            assignment.variant == override and \
                            (experiment is None or assignment.id != 0 or
                             experiment.data.id == 0) and \
                            (experiment is None or
                             experiment.holdouts is assignment.holdouts or
                             _holdout_set_matches(experiment, assignment)):
                        if assignment.variables is None and \
                                experiment is not None and \
                                assignment.id == experiment.data.id and \
                                0 <= assignment.variant < \
                                len(experiment.data.variants):
                            # Filled below, under the write lock.
                            fill = assignment
                        else:
                            return assignment
                elif experiment is None:
                    if assignment.assigned is False and \
                            not assignment.rule_override:
                        return assignment
                elif assignment.rule_override or \
                        experiment_name not in self.custom_assignments or \
                        self.custom_assignments[experiment_name] == \
                        assignment.variant or assignment.suppressed:
                    # A suppressed assignment is forced to control, so a
                    # custom assignment that differs from it is not staleness.
                    if experiment_matches(experiment.data, assignment) and \
                            (experiment.holdouts is assignment.holdouts or
                             _holdout_set_matches(experiment, assignment)):
                        if _rule_key(experiment.data) == \
                                assignment.rule_key and \
                                self._attrs_seq <= (assignment.attrs_seq or 0):
                            return assignment
                        checked_seq = self._attrs_seq
        finally:
            self.context_lock.release_read()

        if fill is not None:
            # A kept override without variables (cached before an id-0
            # experiment was known, or overridden to a variant it did not
            # have yet) takes the variables of the same experiment, as JS
            # followArm does. The experiment is read again and the variables
            # stored under the write lock and data_lock together, so a
            # reader that checked the cache before a refresh cannot store
            # the replaced payload's variables.
            try:
                self.context_lock.acquire_write()
                self.data_lock.acquire_read()
                experiment = self.index.get(experiment_name, None)
                if experiment is not None and \
                        fill.id == experiment.data.id and \
                        0 <= fill.variant < len(experiment.data.variants):
                    fill.variables = experiment.variables[fill.variant]
                return fill
            finally:
                self.data_lock.release_read()
                self.context_lock.release_write()

        if checked_seq is not None:
            # Attributes or the assignment rules changed since the assignment
            # was computed: re-check its rule and audience results under the
            # write lock, after releasing the read lock, since concurrent
            # readers cannot all upgrade (resolving a split rule may compute a
            # unit hash). When both are unchanged, record the rules and the
            # sequence they were checked at (JS sets assignment.ruleKey and
            # attrsSeq) so later reads skip the re-check and the assignment
            # keeps its exposed state, as in the JS SDK's audienceMatches.
            try:
                self.context_lock.acquire_write()
                if self.assignment_cache.get(experiment_name) is assignment:
                    experiment = self.get_experiment(experiment_name)
                    if experiment is not None and \
                            experiment_matches(experiment.data, assignment) and \
                            _holdout_set_matches(experiment, assignment):
                        rule_key = _rule_key(experiment.data)
                        if rule_key == assignment.rule_key and \
                                (assignment.attrs_seq or 0) >= checked_seq:
                            return assignment
                        # Rules removed from an assignment a rule decided:
                        # rebuild it, as JS does.
                        rules_removed = rule_key != assignment.rule_key and \
                            not rule_key and \
                            (assignment.rule_variant is not None or
                             assignment.rule_override)
                        if not rules_removed and \
                                self._rules_and_audience_match(
                                    experiment.data, assignment):
                            assignment.rule_key = rule_key
                            assignment.attrs_seq = checked_seq
                            return assignment
            finally:
                self.context_lock.release_write()

        try:
            self.context_lock.acquire_write()
            # The holdout definitions are read with the experiment, so a
            # concurrent refresh cannot mix two payloads in one decision.
            experiment, failed, holdouts_by_id = \
                self._get_resolution_state(experiment_name)
            assignment = Assignment()
            assignment.name = experiment_name
            assignment.eligible = True
            assignment.data_failed = failed

            if exposed_at:
                assignment.exposedAt = exposed_at

            if experiment is not None and experiment.holdouts is not None:
                # Resolved for overrides and rule wins too: their holdouts
                # still publish exposures (JS _assign).
                self._resolve_holdouts(experiment, assignment, holdouts_by_id)

            if experiment_name in self.overrides:
                if experiment is not None:
                    assignment.id = experiment.data.id
                    assignment.unit_type = experiment.data.unitType

                assignment.overridden = True
                assignment.variant = self.overrides[experiment_name]
            else:
                if experiment is not None:
                    unit_type = experiment.data.unitType

                    rule_variant, assignment.rule_missing_unit = \
                        self._resolve_rule(experiment.data)
                    assignment.rule_key = _rule_key(experiment.data)
                    assignment.rule_variant = rule_variant
                    if rule_variant is not None:
                        # A matching rule wins over holdout suppression, like
                        # an override (JS _assign, scenario 305).
                        assignment.variant = rule_variant
                        assignment.assigned = False
                        assignment.eligible = True
                        assignment.rule_override = True
                    elif assignment.suppressed:
                        # Held out: control, not assigned. The audience,
                        # full-on, traffic and custom assignment are skipped.
                        pass
                    elif experiment.data.audience is not None and \
                            len(experiment.data.audience) > 0:
                        # A rule win happens before audience evaluation (as
                        # in the JS SDK), so the audience is only evaluated
                        # when no rule selected the variant.
                        attrs = self._build_audience_attributes()
                        match = self.audience_matcher.evaluate(
                            experiment.data.audience,
                            attrs)
                        if match is not None:
                            assignment.audience_mismatch = not match.result
                    if assignment.rule_override or assignment.suppressed:
                        pass
                    elif experiment.data.audienceStrict and \
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

    def _get_resolution_state(self, experiment_name: str):
        try:
            self.data_lock.acquire_read()
            return self.index.get(experiment_name, None), self.failed, \
                self._holdouts_by_id
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

    def _resolve_holdouts(self, experiment: ExperimentVariables,
                          assignment: Assignment, holdouts_by_id):
        # Each holdout is evaluated with the covered experiment's unit type,
        # never the holdout's own (scenario 227). A missing unit leaves a
        # None entry, which never suppresses; set_unit evicts the assignment
        # so it is resolved again once the unit is there.
        unit_type = experiment.data.unitType
        holdout_assignments = [
            self._get_holdout_assignment(holdout, unit_type, holdouts_by_id)
            if unit_type is not None else None
            for holdout in experiment.holdouts]
        assignment.holdouts = experiment.holdouts
        assignment.holdout_assignments = holdout_assignments
        full_on_variant = experiment.data.fullOnVariant
        assignment.suppressed = any(
            holdout_assignment is not None and _is_held_out_by(
                holdout_assignment.variant,
                holdout_assignment.holdout_arm_count,
                full_on_variant)
            for holdout_assignment in holdout_assignments)

    def _get_holdout_assignment(self, holdout: _Holdout, unit_type: str,
                                holdouts_by_id=None):
        # Called under the context write lock with the holdout definitions
        # of the payload the experiment came from (the installed ones by
        # default). `holdout` may predate that payload, so its definition
        # there is preferred. The cached arm (and its arm count) stays while
        # the iteration is unchanged, so a seed or split edit does not
        # re-randomise or re-expose.
        if holdouts_by_id is None:
            holdouts_by_id = self._holdouts_by_id
        live = holdouts_by_id.get(holdout.id, holdout)
        cache_key = (live.id, unit_type)
        cached = self._holdout_assignments.get(cache_key)
        if cached is not None and cached.iteration == live.iteration:
            return cached

        if unit_type not in self.units:
            return None
        unit_hash = self.get_unit_hash(unit_type, self.units[unit_type])
        assigner = self.get_variant_assigner(unit_type, unit_hash)

        assignment = Assignment()
        assignment.id = live.id
        assignment.iteration = live.iteration
        assignment.name = live.name
        assignment.unit_type = unit_type
        assignment.variant = assigner.assign(list(live.split), live.seed_hi,
                                             live.seed_lo)
        assignment.assigned = True
        assignment.eligible = True
        assignment.holdout_arm_count = len(live.split)
        installed = self._holdouts_by_id.get(live.id)
        if holdouts_by_id is self._holdouts_by_id or installed is None or \
                installed.iteration == live.iteration:
            # A resolution still working on a replaced payload caches its
            # arm unless the installed payload moved the holdout to another
            # iteration, so every experiment shares one arm per epoch (also
            # when a refresh drops the holdout and a later one restores it)
            # and a newer epoch is never overwritten.
            self._holdout_assignments[cache_key] = assignment
        return assignment

    def _retire(self, assignment: Assignment):
        # Under event_lock, the lock exposures are queued under, so an
        # assignment is either exposed or retired, never both.
        try:
            self.event_lock.acquire_write()
            if assignment.exposed.value:
                return False
            assignment.retired = True
            return True
        finally:
            self.event_lock.release_write()

    def _expose(self, assignment: Assignment, offer_holdouts: bool = True,
                holdouts_first: bool = False):
        """Expose an assignment; False when set_unit retired it first.

        JS _triggerExposures: a held-out experiment publishes no exposure of
        its own (unless an override or a rule chose its variant), and every
        holdout pinned on the assignment publishes its own once per (holdout,
        unit type), from the snapshot taken when the assignment was resolved,
        so a refresh in between cannot mix epochs. The whole group is
        accepted in one event_lock section, so a concurrent close either
        rejects all of it (and a later read retries) or publishes all of it;
        the events are logged after the lock is released. A variable read
        passes holdouts_first=True so the holdouts precede the winner, as on
        the walk; through a queue_exposure override it passes
        offer_holdouts=False, since its walk already offered the holdouts
        (_expose_holdouts) and a declined one is not offered twice in a read.
        """
        if assignment.holdout_assignments is None:
            if getattr(self.queue_exposure, "__func__", None) is \
                    Context.queue_exposure:
                return self.queue_exposure(assignment) is not False
            # Like _expose_through_hook: an override is never handed an
            # assignment set_unit already retired, and is judged by the
            # state, since its return value (v0.2.4 hooks may return False
            # to decline) is not a set_unit retirement.
            try:
                self.event_lock.acquire_write()
                if assignment.retired:
                    return False
            finally:
                self.event_lock.release_write()
            self.queue_exposure(assignment)
            return assignment.exposed.value or not assignment.retired
        if getattr(self.queue_exposure, "__func__", None) is not \
                Context.queue_exposure:
            return self._expose_through_hook(assignment, offer_holdouts)

        accepted = []
        try:
            self.event_lock.acquire_write()
            self.check_not_closed()
            if assignment.retired:
                return False
            exposed_at = assignment.exposedAt or self.clock.millis()

            def accept_assignment():
                if assignment.suppressed and not assignment.overridden and \
                        not assignment.rule_override:
                    assignment.exposed.compare_and_set(False, True)
                else:
                    exposure = self._accept_exposure(
                        assignment, assignment.name, exposed_at)
                    if exposure is not None:
                        accepted.append(exposure)

            if not holdouts_first:
                accept_assignment()
            if offer_holdouts:
                self._accept_holdouts(assignment, exposed_at, accepted)
            if holdouts_first:
                accept_assignment()
        finally:
            self.event_lock.release_write()

        if offer_holdouts:
            assignment.holdouts_exposed = True
            assignment.holdouts_pending = False
        self._log_exposures(accepted)
        return True

    def _accept_holdouts(self, assignment: Assignment, exposed_at,
                         accepted: list, staged=()):
        # Under event_lock, after check_not_closed. Each exposure is named
        # from this assignment's snapshot, like JS holdouts[i].data.name;
        # the shared holdout assignment is not modified. Arms in `staged`
        # are left for the winner's section.
        for holdout, holdout_assignment in zip(
                assignment.holdouts, assignment.holdout_assignments):
            if holdout_assignment is not None and \
                    id(holdout_assignment) not in staged:
                exposure = self._accept_exposure(
                    holdout_assignment, holdout.name, exposed_at)
                if exposure is not None:
                    accepted.append(exposure)

    def _log_exposures(self, accepted: list):
        # After event_lock is released, so a logger may close or read.
        for exposure in accepted:
            self.log_event(EventType.EXPOSURE, exposure)
        if accepted:
            self.set_timeout()

    def _expose_through_hook(self, assignment: Assignment,
                             offer_holdouts: bool = True):
        # A subclass overriding queue_exposure (a v0.2.4 extension point)
        # keeps seeing every exposure, one call each, at the cost of the
        # grouped acceptance. The read's time is taken once for the group.
        exposed_at = assignment.exposedAt or self.clock.millis()
        if not assignment.exposed.value:
            if assignment.suppressed and not assignment.overridden and \
                    not assignment.rule_override:
                try:
                    self.event_lock.acquire_write()
                    self.check_not_closed()
                    if assignment.retired:
                        return False
                    if assignment.exposed.compare_and_set(False, True):
                        assignment.holdouts_pending = True
                finally:
                    self.event_lock.release_write()
            else:
                try:
                    # Reserved under event_lock, like the holdouts below: a
                    # retired assignment is never offered, concurrent reads
                    # offer it once, and holdouts stay pending even if the
                    # hook raises after queuing it.
                    self.event_lock.acquire_write()
                    if assignment.retired:
                        return False
                    if assignment.hook_pending:
                        return True
                    assignment.hook_pending = True
                    assignment.holdouts_pending = True
                finally:
                    self.event_lock.release_write()
                # The assignment itself goes to the hook, so a set_unit
                # retirement during the call is still seen; it carries the
                # read's time for the group during the call only, so a
                # declined exposure is stamped afresh by the next read.
                caller_exposed_at = assignment.exposedAt
                assignment.exposedAt = exposed_at
                try:
                    self.queue_exposure(assignment)
                finally:
                    assignment.exposedAt = caller_exposed_at
                    assignment.hook_pending = False
                # Judged by the state, not the hook's return value: only an
                # assignment set_unit retired before it was queued is
                # retried.
                if not assignment.exposed.value and assignment.retired:
                    return False
        if not offer_holdouts:
            if assignment.holdouts_exposed:
                assignment.holdouts_pending = False
        elif self._offer_holdouts_through_hook(assignment, exposed_at):
            assignment.holdouts_pending = False
        return True

    def _offer_holdouts_through_hook(self, assignment: Assignment,
                                     exposed_at, offered=None):
        # True when every holdout pinned on the assignment is exposed. A
        # raising hook does not stop the other holdouts: the first error is
        # raised after every one was offered (Java
        # triggerApplicableHoldoutExposures).
        finished = True
        failure = None
        for holdout, holdout_assignment in zip(
                assignment.holdouts, assignment.holdout_assignments):
            if holdout_assignment is None:
                continue
            try:
                # Reserved under event_lock so concurrent reads call the
                # hook once per holdout exposure; released if the hook does
                # not queue it, so a later read retries.
                self.event_lock.acquire_write()
                if holdout_assignment.exposed.value:
                    continue
                if holdout_assignment.hook_pending or (
                        offered is not None and
                        holdout_assignment in offered):
                    finished = False
                    continue
                holdout_assignment.hook_pending = True
                if offered is not None:
                    # The arm itself, kept alive for the read: an id could be
                    # reused by an arm a refresh creates after this one is
                    # released.
                    offered.add(holdout_assignment)
            finally:
                self.event_lock.release_write()
            try:
                # The hook gets a copy carrying this snapshot's name and the
                # read's exposure time; it shares `exposed` (an AtomicBool)
                # with the cached arm, so the arm stays exposed once only.
                view = copy.copy(holdout_assignment)
                view.name = holdout.name
                view.exposedAt = exposed_at
                self.queue_exposure(view)
            except Exception as error:
                if failure is None:
                    failure = error
            finally:
                holdout_assignment.hook_pending = False
            if not holdout_assignment.exposed.value:
                finished = False
        if failure is not None:
            raise failure
        return finished

    def _expose_holdouts(self, assignment: Assignment, offered=None,
                         staged=()):
        """Expose the holdouts pinned on a variable-key candidate, not the
        candidate itself (Java triggerApplicableHoldoutExposures).

        A held-out unit and a not held-out one fire the same holdouts on
        every candidate visited, so both arms stay symmetric whichever
        candidate wins the key. Unexposed ones are offered again on the next
        read.
        """
        if assignment.holdout_assignments is None or \
                assignment.holdouts_exposed:
            return
        if not self._holdouts_unexposed(assignment):
            # The pinned arms never change and stay exposed.
            assignment.holdouts_exposed = True
            assignment.holdouts_pending = False
            return
        exposed_at = assignment.exposedAt or self.clock.millis()
        if getattr(self.queue_exposure, "__func__", None) is not \
                Context.queue_exposure:
            self._offer_holdouts_through_hook(assignment, exposed_at,
                                              offered)
            if not self._holdouts_unexposed(assignment):
                assignment.holdouts_exposed = True
                assignment.holdouts_pending = False
            return

        accepted = []
        try:
            self.event_lock.acquire_write()
            self.check_not_closed()
            self._accept_holdouts(assignment, exposed_at, accepted, staged)
        finally:
            self.event_lock.release_write()

        if not staged or not self._holdouts_unexposed(assignment):
            assignment.holdouts_exposed = True
            assignment.holdouts_pending = False
        self._log_exposures(accepted)

    @staticmethod
    def _holdouts_unexposed(assignment: Assignment):
        return any(holdout_assignment is not None and
                   not holdout_assignment.exposed.value
                   for holdout_assignment in assignment.holdout_assignments)

    def _accept_exposure(self, assignment: Assignment, name, exposed_at):
        # Under event_lock, after check_not_closed: the exposure to queue,
        # None when there is nothing to queue, False when retired.
        if assignment.data_failed and not self.failed:
            # A placeholder computed before recovery: its experiment is
            # now known, so the next read recomputes and exposes it.
            return None
        if getattr(assignment, "retired", False):
            return False
        if not assignment.exposed.compare_and_set(False, True):
            return None
        exposure = Exposure()
        exposure.id = assignment.id
        exposure.name = name
        exposure.unit = assignment.unit_type
        exposure.variant = assignment.variant
        exposure.exposedAt = exposed_at
        exposure.assigned = assignment.assigned
        exposure.eligible = assignment.eligible
        exposure.overridden = assignment.overridden
        exposure.fullOn = assignment.full_on
        exposure.custom = assignment.custom
        exposure.audienceMismatch = assignment.audience_mismatch
        exposure.ruleOverride = getattr(assignment, "rule_override", False)

        self.pending_count.increment_and_get()
        self.exposures.append(exposure)
        return exposure

    def queue_exposure(self, assignment: Assignment):
        try:
            self.event_lock.acquire_write()
            # Only mark the assignment exposed once the queue accepts the
            # exposure: a context that started closing rejects it instead.
            self.check_not_closed()
            exposure = self._accept_exposure(
                assignment, assignment.name,
                assignment.exposedAt or self.clock.millis())
        finally:
            self.event_lock.release_write()

        if not exposure:
            return exposure
        self.log_event(EventType.EXPOSURE, exposure)
        self.set_timeout()
