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
from sdk.internal import switchback_assigner, switchback_serving
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

# The Collector's switchback anchor bounds (Registry): an anchor must be hour
# aligned and in [0, 10000-01-01T00:00:00Z).
_SWITCHBACK_ANCHOR_ALIGNMENT_MS = 3_600_000
_SWITCHBACK_MAX_ANCHOR_MS = 253_402_300_800_000
# Period slots kept per switchback experiment (plus its bare-name slot).
_SWITCHBACK_RETAINED_PERIODS = 2
# The characters Java's String.trim() removes, which the Collector applies to
# attribute names.
_JAVA_TRIM = "".join(chr(c) for c in range(0x21))


class Assignment:
    # Switchbacks (see Context._get_switchback_assignment): the epoch the
    # slot was resolved in, its serving resolution (read once per slot), the
    # custom assignment it saw, and whether it records no exposure. Class
    # defaults, set per instance only on switchback slots, so unit
    # assignments stay as small as before.
    switchback: bool = False
    switchback_generation: Optional[int] = None
    switchback_serving = None
    switchback_custom: Optional[int] = None
    switchback_silent: bool = False

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


class ExperimentVariables:
    data: Optional[Experiment]
    variables: Optional[list[dict]]
    # The holdouts covering the experiment, sorted by id; None when it has
    # none (or none of its holdoutIds names a usable holdout).
    holdouts: Optional[list] = None
    # The parsed switchback definition; None for a unit experiment.
    switchback: Optional["_Switchback"] = None


class _Holdout:
    __slots__ = ("id", "name", "iteration", "seed_hi", "seed_lo", "split")

    def __init__(self, id, name, iteration, seed_hi, seed_lo, split):
        self.id = id
        self.name = name
        self.iteration = iteration
        self.seed_hi = seed_hi
        self.seed_lo = seed_lo
        self.split = split


class _Switchback:
    """An installed switchback experiment's serving definition.

    `sources` is the cluster map split in declared order, or None when it is
    missing, empty or unreadable (the Collector's legacy path). `identity` is
    every input to the period grid and the cluster key (see
    _switchback_identity); `generation` changes whenever it does.
    """
    __slots__ = ("sources", "allowed", "start_at", "period_ms", "servable",
                 "seed", "identity", "generation")

    def __init__(self, experiment):
        self.sources = switchback_serving.sources(
            getattr(experiment, "switchbackClusters", None))
        self.allowed = switchback_serving.allow_list(
            getattr(experiment, "switchbackClusterValues", None))
        self.start_at = _int_id(getattr(experiment, "switchbackStartAt", None))
        self.period_ms = _int_id(
            getattr(experiment, "switchbackPeriodMs", None))
        split = getattr(experiment, "split", None)
        # Whether the Collector's Registry can serve the schedule: an anchor
        # that is set, hour aligned and in range (used as served, never
        # rounded), a period > 0 and at least two arms. An unservable
        # schedule only replaces the draw: rules and full-on still apply.
        self.servable = self.start_at is not None and \
            0 <= self.start_at < _SWITCHBACK_MAX_ANCHOR_MS and \
            self.start_at % _SWITCHBACK_ANCHOR_ALIGNMENT_MS == 0 and \
            self.period_ms is not None and self.period_ms > 0 and \
            isinstance(split, (list, tuple)) and len(split) >= 2
        seed_hi = _int_id(getattr(experiment, "seedHi", 0)) or 0
        seed_lo = _int_id(getattr(experiment, "seedLo", 0)) or 0
        # Java's ((long) seedHi << 32) | (seedLo & 0xffffffffL).
        self.seed = (seed_hi << 32) | (seed_lo & 0xffffffff)
        self.identity = _switchback_identity(experiment, self.sources)
        self.generation = 0

    @classmethod
    def installed(cls, experiment):
        # A switchback whose fields cannot be read is served as an
        # unservable one (the legacy ineligible control) instead of failing
        # the whole context.
        try:
            return cls(experiment)
        except Exception as e:
            logger.warning("Switchback experiment '%s' is unreadable: %s",
                           getattr(experiment, "name", None),
                           type(e).__name__)
            switchback = cls.__new__(cls)
            switchback.sources = None
            switchback.allowed = None
            switchback.start_at = None
            switchback.period_ms = None
            switchback.servable = False
            switchback.seed = 0
            switchback.identity = ("unreadable", object())
            switchback.generation = 0
            return switchback

    def period(self, now):
        """floor((now - startAt) / periodMs), as the Collector computes it;
        None before the anchor, for an unservable schedule and on the legacy
        path."""
        if isinstance(now, float) and math.isfinite(now):
            now = math.floor(now)
        if not self.servable or self.sources is None or \
                not isinstance(now, int) or now < self.start_at:
            return None
        return (now - self.start_at) // self.period_ms


def _is_switchback(experiment):
    return getattr(experiment, "randomizationType", None) == "switchback"


_MAX_IDENTITY_TOKENS = 100_000


def _identity_value(value):
    # Value and type, mappings in their order, so the same cluster map
    # entries in another order are another identity. Encoded iteratively
    # with explicit open/close markers, so deeply nested metadata cannot
    # exhaust the stack; a value too large (or cyclic) to encode never
    # equals another, which only starts a new epoch.
    tokens = []
    stack = [(False, value)]
    while stack:
        if len(tokens) > _MAX_IDENTITY_TOKENS:
            return ("unbounded", object())
        is_marker, item = stack.pop()
        if is_marker:
            tokens.append(item)
        elif isinstance(item, Mapping):
            tokens.append("{")
            stack.append((True, "}"))
            for key, child in reversed(list(item.items())):
                stack.append((False, child))
                stack.append((True, ("key", type(key).__name__, repr(key))))
        elif isinstance(item, (list, tuple)):
            tokens.append("[")
            stack.append((True, "]"))
            stack.extend((False, child) for child in reversed(item))
        else:
            tokens.append((type(item).__name__, repr(item)))
    return tuple(tokens)


def _switchback_identity(experiment, sources):
    # Java sameSwitchbackIdentity: id, iteration, the ordered cluster map,
    # the allow-list, startAt, periodMs and design, plus unitType on the
    # legacy path. Seed, split and the analysis-only fields (carryover, burn
    # windows, estimand) are not part of it.
    return (
        _identity_value(getattr(experiment, "id", None)),
        _identity_value(getattr(experiment, "iteration", None)),
        _identity_value(getattr(experiment, "switchbackClusters", None)),
        _identity_value(getattr(experiment, "switchbackClusterValues", None)),
        _identity_value(getattr(experiment, "switchbackStartAt", None)),
        _identity_value(getattr(experiment, "switchbackPeriodMs", None)),
        _identity_value(getattr(experiment, "switchbackDesignType", None)),
        _identity_value(getattr(experiment, "unitType", None))
        if sources is None else None)


class _SwitchbackEpoch:
    # The slots of one switchback experiment created under one generation:
    # its bare-name slot (pre-anchor, unservable or legacy) and the indices
    # of its period slots.
    __slots__ = ("generation", "periods")

    def __init__(self, generation):
        self.generation = generation
        self.periods = set()


def _switchback_slot_key(experiment_name, period):
    # A tuple, so no experiment name can collide with a period slot.
    return experiment_name if period is None else (experiment_name, period)


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
        # Switchbacks: whether the installed data has any, the epoch of
        # every switchback with cached slots, and the generation source.
        # The names that take the switchback path: switchbacks in the
        # installed data and experiments whose epoch still has slots to
        # drop. Empty when the data has no switchbacks, which leaves unit
        # experiments on the path they took before switchbacks.
        self._switchback_names = frozenset()
        self._switchback_epochs = {}
        self._switchback_generations = 0
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
                # Like the JS SDK's unit(): an unexposed assignment for this
                # unit type was resolved while the unit was missing, so drop
                # it and let the next read resolve it with the unit. Exposed
                # ones are kept, as re-resolving would expose them twice.
                for name, assignment in list(self.assignment_cache.items()):
                    serving = assignment.switchback_serving
                    if serving is not None and \
                            serving.status == switchback_serving.ABSENT:
                        # A switchback resolved before any linked unit was
                        # set is resolved again now that one may be. A
                        # non-overridden one never published anything, so
                        # it is dropped even if exposed.
                        if not assignment.overridden or \
                                self._retire(assignment):
                            del self.assignment_cache[name]
                    elif assignment.unit_type == unit_type and \
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
        switchbacks = []

        for experiment in data.experiments:
            experiment_variables = ExperimentVariables()
            experiment_variables.data = experiment
            experiment_variables.variables = []
            if _is_switchback(experiment):
                # Holdouts never apply to a switchback.
                experiment_variables.switchback = \
                    _Switchback.installed(experiment)
                switchbacks.append(experiment_variables)
            elif holdouts_by_id:
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

            for experiment_variables in switchbacks:
                # The previous generation is kept only while the previous
                # definition was a switchback with the same identity; any
                # other transition (a change, a unit definition, a removal)
                # starts a new epoch, even one that was never looked up.
                previous = self.index.get(experiment_variables.data.name)
                switchback = experiment_variables.switchback
                if previous is not None and previous.switchback is not None \
                        and previous.switchback.identity == \
                        switchback.identity:
                    switchback.generation = previous.switchback.generation
                else:
                    self._switchback_generations += 1
                    switchback.generation = self._switchback_generations

            self.index = index
            self._switchback_names = frozenset(
                [e.data.name for e in switchbacks] +
                list(self._switchback_epochs))
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
            self._switchback_names = frozenset(self._switchback_epochs)
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
                        attempt: int = 1):
        # Port of the JS SDK's _variableValue/_peekVariable: walk every
        # experiment defining the key (sorted by id) and return the value from
        # the first one the unit is assigned to or overridden in, queuing an
        # exposure for each experiment visited on the way.
        # A held-out experiment never wins the key over an assigned one, but
        # when nothing else does its control value is returned instead of
        # the default (JS _resolveVariableValue). The first held-out
        # candidate is kept even if it lacks the key.
        experiments = Concurrency.get_rw(
            self.data_lock, self.index_variables, key) or []
        # A switchback is resolved and exposed at one clock reading per
        # walk; a retry takes a fresh one.
        now = self.clock.millis() if self._switchback_names else None
        suppressed_fallback = None
        for experiment in list(experiments):
            assignment = self._assignment_at(experiment.data.name, None, now) \
                if now is not None else \
                self.get_assignment(experiment.data.name)
            if assignment.variables is not None:
                if expose and (not assignment.exposed.value or
                               assignment.holdouts_pending) and \
                        not self._expose_at(assignment, now) and \
                        attempt < _MAX_EXPOSURE_ATTEMPTS:
                    # set_unit retired a candidate in between, so the key
                    # may resolve differently: walk it again.
                    return self._variable_value(key, default_value, expose,
                                                attempt + 1)

                if key in assignment.variables and \
                        (assignment.assigned or assignment.overridden or
                         assignment.rule_override):
                    return assignment.variables[key]

                if assignment.suppressed and not assignment.overridden and \
                        not assignment.rule_override and \
                        suppressed_fallback is None:
                    suppressed_fallback = assignment.variables
        if suppressed_fallback is not None and key in suppressed_fallback:
            return suppressed_fallback[key]
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
        if experiment_name in self._switchback_names:
            return self._switchback_treatment(experiment_name, exposed_at)
        assignment = self.get_assignment(experiment_name, exposed_at=exposed_at)
        if (not assignment.exposed.value or assignment.holdouts_pending) and \
                not self._expose(assignment):
            for _ in range(_MAX_EXPOSURE_ATTEMPTS - 1):
                assignment = self.get_assignment(experiment_name,
                                                 exposed_at=exposed_at)
                if assignment.exposed.value or self._expose(assignment):
                    break
        return assignment.variant

    def _switchback_treatment(self, experiment_name, exposed_at):
        # Each attempt resolves and exposes at one clock reading (exposed_at
        # when given, so a historic exposure lands in the period it names).
        for _ in range(_MAX_EXPOSURE_ATTEMPTS):
            now = exposed_at if exposed_at is not None else \
                self.clock.millis()
            assignment = self._assignment_at(experiment_name, exposed_at, now)
            if assignment.exposed.value or self._expose_at(assignment, now):
                break
        return assignment.variant

    def _assignment_at(self, experiment_name, exposed_at, now):
        if experiment_name in self._switchback_names:
            assignment = self._get_switchback_assignment(
                experiment_name, exposed_at, now)
            if assignment is not None:
                return assignment
        return self.get_assignment(experiment_name, exposed_at=exposed_at)

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
                      unit_pinned_missing: bool = False, unit_type=None):
        """The variant the first matching assignment rule selects and whether
        it is the no-unit result, or (None, False)
        when no rule matches or the matching rule does not fit the
        experiment (a variant out of range or a split of the wrong length).
        Like the JS SDK's _resolveRule, a split whose unit is not set (or is
        pinned as missing) selects the experiment's no-unit result, its
        fullOnVariant. A switchback passes its serving unit's type, which
        a split rule randomizes over instead of the experiment's unitType."""
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
        if unit_type is None:
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
        if experiment_name in self._switchback_names:
            assignment = self._get_switchback_assignment(
                experiment_name, exposed_at, None)
            if assignment is not None:
                return assignment
        assignment = self._get_unit_assignment(experiment_name, exposed_at)
        if assignment is None:
            # A refresh installed a switchback under this name after the
            # check above: resolve the definition that is installed now.
            assignment = self._get_switchback_assignment(
                experiment_name, exposed_at, None)
        return assignment

    def _get_unit_assignment(self, experiment_name, exposed_at):
        # None when the installed definition turns out to be a switchback.
        checked_seq = None
        try:
            self.context_lock.acquire_read()

            if experiment_name in self.assignment_cache:
                assignment: Assignment = self.assignment_cache[experiment_name]

                experiment, failed = self._get_experiment_state(
                    experiment_name)

                if experiment is not None and \
                        experiment.switchback is not None:
                    return None
                if assignment.data_failed and not failed:
                    # Computed before a refresh recovered the context; its
                    # placeholder exposure was dropped, so recompute.
                    pass
                elif experiment_name in self.overrides:
                    override = self.overrides[experiment_name]
                    if assignment.overridden and \
                            assignment.variant == override and \
                            (experiment is None or
                             experiment.holdouts is assignment.holdouts or
                             _holdout_set_matches(experiment, assignment)):
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
                            experiment.switchback is not None:
                        return None
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
            if experiment is not None and experiment.switchback is not None:
                return None
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

    def _get_switchback_assignment(self, experiment_name, exposed_at, now):
        """The switchback slot for experiment_name at `now`, or None when it
        is not a switchback, for the unit path to resolve.

        Port of the Java SDK's switchback branch of getAssignment: each
        period of a switchback has its own slot (the bare name before the
        anchor, for an unservable schedule and on the legacy path), so a new
        period resolves and exposes again. The slots of an epoch are dropped
        together, lazily, once a refresh changes the switchback's identity.
        """
        try:
            self.context_lock.acquire_read()
            experiment, _ = self._get_experiment_state(experiment_name)
            switchback = experiment.switchback \
                if experiment is not None else None
            epoch = self._switchback_epochs.get(experiment_name)
            if switchback is None and epoch is None:
                return None
            if now is None:
                now = exposed_at if exposed_at is not None else \
                    self.clock.millis()
            if switchback is not None and (
                    epoch is None or
                    epoch.generation == switchback.generation):
                cached = self.assignment_cache.get(_switchback_slot_key(
                    experiment_name, switchback.period(now)))
                if cached is not None and self._switchback_slot_current(
                        experiment_name, cached, experiment, False):
                    return cached
        finally:
            self.context_lock.release_read()

        try:
            self.context_lock.acquire_write()
            experiment, failed = self._get_experiment_state(experiment_name)
            switchback = experiment.switchback \
                if experiment is not None else None
            epoch = self._switchback_epochs.get(experiment_name)
            if epoch is not None and (
                    switchback is None or
                    epoch.generation != switchback.generation):
                self._drop_switchback_epoch(experiment_name)
            if switchback is None:
                self._prune_switchback_names()
                return None

            period = switchback.period(now)
            slot_key = _switchback_slot_key(experiment_name, period)
            # Rechecked: a concurrent caller may have installed this slot
            # (the first call in a new period) between the two locks.
            cached = self.assignment_cache.get(slot_key)
            if cached is not None and self._switchback_slot_current(
                    experiment_name, cached, experiment, True):
                return cached

            data = experiment.data
            assignment = Assignment()
            assignment.name = experiment_name
            assignment.eligible = True
            assignment.data_failed = failed
            assignment.switchback = True
            assignment.switchback_generation = switchback.generation
            # Within one period slot the serving unit and cluster key are
            # read once: a slot replaced in the same epoch, for example after
            # set_attribute changed the audience, keeps its cluster.
            cached_serving = cached.switchback_serving \
                if cached is not None else None
            if cached_serving is None or \
                    cached_serving.status == switchback_serving.ABSENT:
                cached_serving = self._resolve_switchback_serving(experiment,
                                                                  now)
            assignment.switchback_serving = cached_serving

            if experiment_name in self.overrides:
                assignment.id = data.id
                assignment.unit_type = cached_serving.unit_type or \
                    self._switchback_fallback_unit_type(experiment)
                assignment.overridden = True
                assignment.variant = self.overrides[experiment_name]
            else:
                self._resolve_switchback_variant(
                    assignment, experiment, cached_serving, period,
                    self.custom_assignments.get(experiment_name))

            if 0 <= assignment.variant < len(data.variants or []):
                assignment.variables = experiment.variables[assignment.variant]

            self.assignment_cache[slot_key] = assignment
            self._retain_switchback_period(experiment_name, switchback,
                                           period)
            return assignment
        finally:
            self.context_lock.release_write()

    def _resolve_switchback_variant(self, assignment, experiment, serving,
                                    period, custom):
        # The Collector's switchback branch (R33): the serving resolution
        # decides whether the experiment applies and under which unit. For
        # an eligible cluster the Collector's assignExperiment order follows:
        # assignment rules (a split rule randomizes over the serving unit),
        # the audience, full-on, the schedule check, traffic (sticky on the
        # serving unit's hash), custom assignment and then the draw over the
        # raw cluster key. Holdouts never apply to a switchback.
        data = experiment.data
        assignment.id = data.id
        assignment.iteration = data.iteration
        assignment.traffic_split = data.trafficSplit
        assignment.full_on_variant = data.fullOnVariant
        assignment.attrs_seq = self._attrs_seq
        assignment.rule_key = _rule_key(data)
        assignment.switchback_custom = custom
        assignment.variant = 0

        if serving.status == switchback_serving.ABSENT:
            assignment.unit_type = \
                self._switchback_fallback_unit_type(experiment)
            assignment.eligible = False
            assignment.switchback_silent = True
            return

        unit_type = serving.unit_type
        assignment.unit_type = unit_type
        assignment.assigned = True
        if serving.status == switchback_serving.INELIGIBLE:
            # No value, units disagreeing, or a value outside the allow-list:
            # control, and nothing is recorded. Rules, the audience and
            # full-on are not evaluated.
            assignment.eligible = False
            assignment.switchback_silent = True
            return

        rule_variant, assignment.rule_missing_unit = self._resolve_rule(
            data, unit_type=unit_type)
        assignment.rule_variant = rule_variant
        if rule_variant is not None:
            # Recorded like a unit experiment's rule win.
            assignment.assigned = False
            assignment.rule_override = True
            assignment.variant = rule_variant
            return

        if data.audience is not None and len(data.audience) > 0:
            match = self.audience_matcher.evaluate(
                data.audience, self._build_audience_attributes())
            if match is not None:
                assignment.audience_mismatch = not match.result
        if data.audienceStrict and assignment.audience_mismatch:
            # Recorded like a unit experiment's strict mismatch.
            assignment.assigned = False
            return
        if data.fullOnVariant != 0:
            assignment.variant = data.fullOnVariant
            assignment.full_on = True
            return
        if period is None:
            # Before the anchor or with an unservable schedule there is no
            # draw: control, and nothing is recorded (the Java SDK's choice;
            # the Collector would record it). This precedes traffic, so a
            # traffic miss before the anchor is silent too.
            assignment.eligible = False
            assignment.switchback_silent = True
            return

        unit_hash = self.get_unit_hash(unit_type, serving.uid)
        assigner = self.get_variant_assigner(unit_type, unit_hash)
        if assigner.assign(data.trafficSplit, data.trafficSeedHi,
                           data.trafficSeedLo) != 1:
            # A traffic miss on an eligible cluster is recorded, as for a
            # unit experiment.
            assignment.eligible = False
            return
        if custom is not None:
            assignment.variant = custom
            assignment.custom = True
            return
        assignment.variant = switchback_assigner.assign(
            serving.cluster_key, period, experiment.switchback.seed,
            len(data.split))

    def _switchback_slot_current(self, experiment_name, cached, experiment,
                                 revalidate):
        # Java isAssignmentCurrent for a switchback slot. On the read path
        # (revalidate False) a slot whose rules or attributes changed is
        # reported stale; the write path re-checks its rule and audience
        # results and keeps it (with its exposed state) when both are
        # unchanged.
        if not cached.switchback or cached.switchback_generation != \
                experiment.switchback.generation:
            return False
        if experiment_name in self.overrides:
            return cached.overridden and \
                cached.variant == self.overrides[experiment_name]
        if cached.overridden:
            return False
        data = experiment.data
        # A matching rule wins over a custom assignment, so a custom change
        # is not staleness for it.
        if not cached.rule_override and cached.switchback_custom != \
                self.custom_assignments.get(experiment_name):
            return False
        if data.fullOnVariant != cached.full_on_variant or \
                list(data.trafficSplit or []) != \
                list(cached.traffic_split or []):
            return False
        serving = cached.switchback_serving
        if serving is None or serving.status != switchback_serving.ELIGIBLE:
            return True
        rule_key = _rule_key(data)
        if rule_key == cached.rule_key and \
                self._attrs_seq <= (cached.attrs_seq or 0):
            return True
        if not revalidate:
            return False
        rule_variant, _ = self._resolve_rule(
            data, unit_type=serving.unit_type)
        if rule_variant != cached.rule_variant:
            return False
        if not cached.rule_override and data.audience is not None and \
                len(data.audience) > 0:
            match = self.audience_matcher.evaluate(
                data.audience, self._build_audience_attributes())
            mismatch = not match.result if match is not None else False
            if mismatch != cached.audience_mismatch:
                return False
        cached.rule_key = rule_key
        cached.attrs_seq = self._attrs_seq
        return True

    def _resolve_switchback_serving(self, experiment, now):
        # The Collector's ContextAPI.switchbackServing at `now`, resolved
        # whether or not the schedule can be drawn now, so rules and full-on
        # still see the serving unit. Caller holds the context write lock.
        switchback = experiment.switchback
        if switchback.sources is None:
            serving = switchback_serving.legacy(experiment.data.unitType,
                                                self.units)
        else:
            types, paths = switchback.sources

            def read(path):
                attribute = self._latest_attribute(path.root_key(), now)
                if attribute is None:
                    return None
                return path.resolve_attribute(attribute.value)

            serving = switchback_serving.resolve(
                types, paths, switchback.allowed, self.units, read)
        serving.read_at = now
        return serving

    def _latest_attribute(self, name, now):
        # The attribute the Collector records with an exposure at `now`:
        # among attributes set at or before now whose trimmed name matches,
        # the greatest setAt wins and a tie goes to the one set last.
        selected = None
        for attribute in self.attributes:
            set_at = attribute.setAt
            if isinstance(attribute.name, str) and \
                    attribute.name.strip(_JAVA_TRIM) == name and \
                    isinstance(set_at, (int, float)) and set_at <= now and \
                    (selected is None or set_at >= selected.setAt):
                selected = attribute
        return selected

    @staticmethod
    def _switchback_fallback_unit_type(experiment):
        # The unit type a switchback without a serving unit is recorded
        # under (an override is still exposed): the first linked type of a
        # readable cluster map, otherwise the declared unitType.
        sources = experiment.switchback.sources
        return sources[0][0] if sources is not None \
            else experiment.data.unitType

    def _prune_switchback_names(self):
        # Once a former switchback's slots are dropped its reads go back to
        # the unit path. Recomputed under the data lock from the installed
        # data, so a concurrent set_data cannot lose a new switchback.
        try:
            self.data_lock.acquire_write()
            self._switchback_names = frozenset(
                [name for name, experiment in self.index.items()
                 if experiment.switchback is not None] +
                list(self._switchback_epochs))
        finally:
            self.data_lock.release_write()

    def _drop_switchback_epoch(self, experiment_name):
        # Drops every slot of the epoch, the bare-name slot included. Caller
        # holds the context write lock.
        epoch = self._switchback_epochs.pop(experiment_name, None)
        if epoch is not None:
            for period in epoch.periods:
                self.assignment_cache.pop(
                    _switchback_slot_key(experiment_name, period), None)
            self.assignment_cache.pop(experiment_name, None)

    def _retain_switchback_period(self, experiment_name, switchback, period):
        # At most _SWITCHBACK_RETAINED_PERIODS period slots are kept; the
        # lowest index other than `period` is evicted, so the slot just
        # installed always survives. Re-entering an evicted period (a clock
        # rewind) resolves and exposes it once more.
        epoch = self._switchback_epochs.get(experiment_name)
        if epoch is None:
            epoch = _SwitchbackEpoch(switchback.generation)
            self._switchback_epochs[experiment_name] = epoch
            # A refresh during this first resolution rebuilt the names
            # before the epoch existed; keep the name routed here until its
            # slots are dropped.
            try:
                self.data_lock.acquire_write()
                self._switchback_names = \
                    self._switchback_names | {experiment_name}
            finally:
                self.data_lock.release_write()
        if period is None:
            return
        epoch.periods.add(period)
        while len(epoch.periods) > _SWITCHBACK_RETAINED_PERIODS:
            evicted = min(p for p in epoch.periods if p != period)
            epoch.periods.discard(evicted)
            self.assignment_cache.pop(
                _switchback_slot_key(experiment_name, evicted), None)

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

    def _expose_at(self, assignment: Assignment, resolved_at):
        # A switchback is exposed at the read that resolved it; everything
        # else goes through _expose(assignment), which subclasses may
        # override with its one-argument signature.
        if assignment.switchback:
            return self._expose_switchback(assignment, resolved_at)
        return self._expose(assignment)

    def _expose(self, assignment: Assignment, resolved_at=None):
        """Expose an assignment; False when set_unit retired it first.

        JS _triggerExposures: a held-out experiment publishes no exposure of
        its own (unless an override or a rule chose its variant), and every
        holdout pinned on the assignment publishes its own once per (holdout,
        unit type), from the snapshot taken when the assignment was resolved,
        so a refresh in between cannot mix epochs. The whole group is
        accepted in one event_lock section, so a concurrent close either
        rejects all of it (and a later read retries) or publishes all of it;
        the events are logged after the lock is released.

        A switchback exposure is stamped with resolved_at, the clock reading
        that selected its period: analysis derives the period from
        exposedAt, so a later reading could place the variant in the next
        period. Unit experiments read the clock when the exposure is queued.
        """
        if assignment.switchback:
            return self._expose_switchback(assignment, resolved_at)
        if assignment.holdout_assignments is None:
            return self.queue_exposure(assignment) is not False
        if getattr(self.queue_exposure, "__func__", None) is not \
                Context.queue_exposure:
            return self._expose_through_hook(assignment)

        accepted = []
        try:
            self.event_lock.acquire_write()
            self.check_not_closed()
            if assignment.retired:
                return False
            exposed_at = assignment.exposedAt or self.clock.millis()
            if assignment.suppressed and not assignment.overridden and \
                    not assignment.rule_override:
                assignment.exposed.compare_and_set(False, True)
            else:
                exposure = self._accept_exposure(assignment, assignment.name,
                                                 exposed_at)
                if exposure is not None:
                    accepted.append(exposure)
            for holdout, holdout_assignment in zip(
                    assignment.holdouts, assignment.holdout_assignments):
                if holdout_assignment is not None:
                    # Named from this assignment's snapshot, like JS
                    # holdouts[i].data.name; the shared holdout assignment
                    # is not modified.
                    exposure = self._accept_exposure(
                        holdout_assignment, holdout.name, exposed_at)
                    if exposure is not None:
                        accepted.append(exposure)
        finally:
            self.event_lock.release_write()

        for exposure in accepted:
            self.log_event(EventType.EXPOSURE, exposure)
        if accepted:
            self.set_timeout()
        return True

    def _expose_switchback(self, assignment: Assignment, resolved_at):
        if assignment.switchback_silent:
            # No linked unit, an ineligible cluster, or no draw: the Collector
            # records nothing, so nothing is queued.
            try:
                self.event_lock.acquire_write()
                self.check_not_closed()
                if assignment.retired:
                    return False
                assignment.exposed.compare_and_set(False, True)
                return True
            finally:
                self.event_lock.release_write()
        exposed_at = self._switchback_exposed_at(
            assignment, resolved_at if resolved_at is not None
            else self.clock.millis())
        if getattr(self.queue_exposure, "__func__", None) is not \
                Context.queue_exposure:
            # The hook reads the time from the assignment; it is set only for
            # this call, so a failed or rejected call leaves no stale time
            # on the cached slot.
            assignment.exposedAt = exposed_at
            try:
                return self.queue_exposure(assignment) is not False
            finally:
                assignment.exposedAt = None
        return self._queue_exposure_at(assignment, exposed_at) is not False

    def _switchback_exposed_at(self, assignment, now):
        # The Collector re-resolves the cluster from the published attributes
        # at exposedAt. The slot read its cluster once (possibly at an
        # earlier peek in the same period); if the attributes now select
        # another one, stamp the exposure at that read instead, which lies in
        # the same period and reconstructs the cluster behind the variant.
        serving = assignment.switchback_serving
        read_at = getattr(serving, "read_at", None)
        if read_at is None or read_at == now:
            return now
        try:
            self.context_lock.acquire_write()
            experiment = self.get_experiment(assignment.name)
            if experiment is None or experiment.switchback is None:
                return now
            current = self._resolve_switchback_serving(experiment, now)
        finally:
            self.context_lock.release_write()
        if (current.status, current.unit_type, current.cluster_key) == \
                (serving.status, serving.unit_type, serving.cluster_key):
            return now
        return read_at

    def _expose_through_hook(self, assignment: Assignment):
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
        finished = True
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
                if holdout_assignment.hook_pending:
                    finished = False
                    continue
                holdout_assignment.hook_pending = True
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
            finally:
                holdout_assignment.hook_pending = False
            if not holdout_assignment.exposed.value:
                finished = False
        if finished:
            assignment.holdouts_pending = False
        return True

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
        exposed_at = assignment.exposedAt
        return self._queue_exposure_at(
            assignment, exposed_at if exposed_at is not None
            else self.clock.millis())

    def _queue_exposure_at(self, assignment: Assignment, exposed_at):
        try:
            self.event_lock.acquire_write()
            # Only mark the assignment exposed once the queue accepts the
            # exposure: a context that started closing rejects it instead.
            self.check_not_closed()
            exposure = self._accept_exposure(
                assignment, assignment.name, exposed_at)
        finally:
            self.event_lock.release_write()

        if not exposure:
            return exposure
        self.log_event(EventType.EXPOSURE, exposure)
        self.set_timeout()
