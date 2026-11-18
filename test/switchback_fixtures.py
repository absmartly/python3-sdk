"""Shared fixtures for the switchback tests (port of the Java SDK's
ContextSwitchbackTest set-up and SwitchbackTestSupport)."""
import json
from concurrent.futures import Future

from sdk.audience_matcher import AudienceMatcher
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.context_event_logger import EventType
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_context_data_provider import DefaultContextDataProvider
from sdk.default_context_event_handler import DefaultContextEventHandler
from sdk.default_context_event_serializer import \
    DefaultContextEventSerializer
from sdk.default_variable_parser import DefaultVariableParser
from sdk.internal import switchback_assigner
from sdk.time.clock import Clock
from sdk.utils import hash_unit
from test.holdout_fixtures import FakeClient, RecordingLogger, context_data

UNIT_TYPE = "store_id"
UID = "e791e240fcd3df7d238cfc285f475e8152fcc0ec"
# hash_unit(UID): the MD5/base64url string the Collector's UnitHasher
# produces.
UID_HASH = "pAE3a1i5Drs5mKRNq56adA"

HOUR = 3_600_000
DAY = 24 * HOUR
# 2026-01-01T00:00:00Z, hour aligned.
ANCHOR = 1_767_225_600_000

SEED_HI = -5
SEED_LO = -7
SEED = (SEED_HI << 32) | (SEED_LO & 0xffffffff)

# The store unit's cluster value: attribute CLUSTER_PATH, set on every
# default context.
CLUSTER_PATH = "store_key"
CLUSTER_KEY = "store-42"
# Periods 0..11 of the raw cluster key "store-42" under seed (SEED_HI,
# SEED_LO), from the Java SDK's independent Python reference (murmur3 over
# the platform formulas, reproducing every golden vector).
EXPECTED_2_ARMS = [0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 0, 1]
EXPECTED_3_ARMS = [0, 2, 1, 2, 1, 0, 1, 2, 0, 1, 0, 2]
EXPECTED_10_ARMS = [8, 3, 7, 4, 2, 0, 5, 1, 9, 6, 3, 7]
# Same reference fed UID_HASH and the raw UID: what keying by the unit
# instead of the cluster value would serve.
UID_HASH_3_ARMS = [1, 2, 0, 2, 1, 0, 2, 0, 1, 1, 2, 0]
UID_3_ARMS = [2, 0, 1, 0, 1, 2, 1, 2, 0, 0, 1, 2]

ASSIGN_VARIANT_1 = json.dumps(
    {"rules": [{"type": "assign", "environments": [], "variant": 1}]})
ASSIGN_VARIANT_2 = json.dumps(
    {"rules": [{"type": "assign", "environments": [], "variant": 2}]})
# An audience the default context never matches (no "tier" attribute).
STRICT_GOLD_AUDIENCE = json.dumps(
    {"filter": [{"eq": [{"var": "tier"}, {"value": "gold"}]}]})


class MutableClock(Clock):
    def __init__(self, now):
        self.now = now
        self.next_read = None

    def millis(self):
        if self.next_read is not None:
            value = self.next_read
            self.next_read = None
            return value
        return self.now


def clusters(*entries):
    """An ordered switchbackClusters map: type, path, type, path, ..."""
    return {entries[i]: entries[i + 1] for i in range(0, len(entries), 2)}


def switchback(id=1, name="exp_sb", arm_count=2, period_ms=HOUR, **fields):
    data = {
        "id": id,
        "name": name,
        "unitType": UNIT_TYPE,
        "iteration": 1,
        "seedHi": SEED_HI,
        "seedLo": SEED_LO,
        "split": [1.0 / arm_count] * arm_count,
        "trafficSeedHi": 1,
        "trafficSeedLo": 2,
        "trafficSplit": [0.0, 1.0],
        "fullOnVariant": 0,
        "applications": [{"name": "website"}],
        "variants": [{"name": chr(ord("A") + i),
                      "config": json.dumps({"sb.arm": i})}
                     for i in range(arm_count)],
        "audienceStrict": False,
        "audience": None,
        "randomizationType": "switchback",
        "switchbackClusters": clusters(UNIT_TYPE, CLUSTER_PATH),
        "switchbackStartAt": ANCHOR,
        "switchbackPeriodMs": period_ms,
        "switchbackCarryoverDurationMs": 0,
        "switchbackBurnInDurationMs": 0,
        "switchbackBurnOutDurationMs": 0,
        "switchbackDesignType": "balanced_block",
        "switchbackEstimand": "global_average_treatment_effect",
    }
    data.update(fields)
    return data


def unit_twin(id=1, name="exp_unit", arm_count=2, **fields):
    """switchback() without any switchback field: a unit experiment."""
    data = switchback(id, name, arm_count)
    for key in [k for k in data if k.startswith(("switchback",
                                                 "randomization"))]:
        del data[key]
    data.update(fields)
    return data


def draw(key, period, arm_count, seed=SEED):
    return switchback_assigner.assign(key, period, seed, arm_count)


def exposure(id, name, variant, exposed_at, unit=UNIT_TYPE, assigned=True,
             eligible=True, overridden=False, full_on=False, custom=False,
             audience_mismatch=False, rule_override=False):
    return (id, name, unit, variant, exposed_at, assigned, eligible,
            overridden, full_on, custom, audience_mismatch, rule_override)


def rule_exposure(name, variant, exposed_at, id=1):
    return exposure(id, name, variant, exposed_at, assigned=False,
                    rule_override=True)


def strict_mismatch_exposure(exposed_at):
    return exposure(1, "exp_sb", 0, exposed_at, assigned=False,
                    audience_mismatch=True)


def exposure_tuples(exposures):
    return [(e.id, e.name, e.unit, e.variant, e.exposedAt, e.assigned,
             e.eligible, e.overridden, e.fullOn, e.custom,
             e.audienceMismatch, e.ruleOverride) for e in exposures or []]


class CountingAudienceMatcher(AudienceMatcher):
    """Counts assignment-rule evaluations."""

    def __init__(self):
        super().__init__(DefaultAudienceDeserializer())
        self.rule_evaluations = 0

    def evaluate_parsed_rules(self, *args, **kwargs):
        self.rule_evaluations += 1
        return super().evaluate_parsed_rules(*args, **kwargs)


class SwitchbackFixture:
    """Creates ready contexts on a mutable clock over a fake client."""

    def set_up_fixture(self):
        self.clock = MutableClock(ANCHOR)
        self.client = FakeClient()
        self.logger = RecordingLogger()

    def create_context(self, experiments, units=None, attributes=None,
                       audience_matcher=None, holdouts=None,
                       cluster_attribute=True, overrides=None,
                       custom_assignments=None):
        config = ContextConfig()
        config.units = {UNIT_TYPE: UID} if units is None else dict(units)
        config.publish_delay = -1
        config.refresh_interval = 0
        attrs = {CLUSTER_PATH: CLUSTER_KEY} if cluster_attribute else {}
        attrs.update(attributes or {})
        if attrs:
            config.attributes = attrs
        if overrides:
            config.overrides = overrides
        if custom_assignments:
            config.custom_assignments = custom_assignments
        future = Future()
        future.set_result(context_data(experiments, holdouts))
        return Context(
            self.clock, config, future,
            DefaultContextDataProvider(self.client),
            DefaultContextEventHandler(self.client), self.logger,
            DefaultVariableParser(),
            audience_matcher or AudienceMatcher(DefaultAudienceDeserializer()),
            "website", "production")

    def refresh_to(self, context, *experiments, holdouts=None):
        self.client.refresh_data = context_data(experiments, holdouts)
        context.refresh()

    def peek_schedule(self, context, name, period_ms=HOUR, periods=12):
        result = []
        for i in range(periods):
            self.clock.now = ANCHOR + i * period_ms
            result.append(context.peek_treatment(name))
        return result

    def publish_event(self, context):
        before = len(self.client.published)
        context.publish()
        self.assertEqual(before + 1, len(self.client.published))
        return self.client.published[-1]

    def published_exposures(self, context):
        if context.get_pending_count() == 0:
            context.publish()
            return []
        return exposure_tuples(self.publish_event(context).exposures)

    def assert_published(self, context, *expected):
        self.assertEqual(list(expected), self.published_exposures(context))

    def serialized(self, event):
        return bytes(DefaultContextEventSerializer().serialize(event)).decode()

    def logged_exposures(self):
        return [data for event_type, data in self.logger.events
                if event_type == EventType.EXPOSURE]

    @staticmethod
    def unit_hash(uid):
        return hash_unit(uid)
