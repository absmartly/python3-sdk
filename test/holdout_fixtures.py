"""Shared fixtures for the holdout tests (port of the Java SDK's
ContextHoldoutTest set-up)."""
import json
from concurrent.futures import Future

from sdk.audience_matcher import AudienceMatcher
from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.context_event_logger import ContextEventLogger, EventType
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.default_context_data_provider import DefaultContextDataProvider
from sdk.default_context_event_handler import DefaultContextEventHandler
from sdk.default_context_event_serializer import \
    DefaultContextEventSerializer
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.default_variable_parser import DefaultVariableParser
from sdk.json.context_data import ContextData
from sdk.time.fixed_clock import FixedClock
from sdk.utils import hash_unit

UNIT_TYPE = "session_id"
UID = "e791e240fcd3df7d238cfc285f475e8152fcc0ec"
UID_NOT_HELD_OUT = "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3"

# split [0.5, 0.5] with these seeds: variant 1 for UID, 0 for
# UID_NOT_HELD_OUT.
NORMAL_SEED_HI = 100
NORMAL_SEED_LO = 200
NORMAL_VARIANT = 1

# split [0.1, 0.9]: variant 0 (held out) for UID, 1 for UID_NOT_HELD_OUT.
HOLDOUT_A_SEEDS = (13, 111)
# split [0.1, 0.9]: variant 1 (not held out) for both UIDs.
HOLDOUT_B_SEEDS = (1, 222)

# split [0.3, 0.3, 0.4] puts UID in arm 0, 1 and 2 with these seeds.
THREE_ARM_SPLIT = [0.3, 0.3, 0.4]
THREE_ARM_0_SEEDS = (0, 1)
THREE_ARM_1_SEEDS = (0, 3)
THREE_ARM_2_SEEDS = (0, 0)

NOW = 1_620_000_000_000


def experiment(id, name, unit_type=UNIT_TYPE, full_on_variant=0,
               holdout_ids=None, **fields):
    data = {
        "id": id,
        "name": name,
        "unitType": unit_type,
        "iteration": 1,
        "seedHi": NORMAL_SEED_HI,
        "seedLo": NORMAL_SEED_LO,
        "split": [0.5, 0.5],
        "trafficSeedHi": 1,
        "trafficSeedLo": 2,
        "trafficSplit": [0.0, 1.0],
        "fullOnVariant": full_on_variant,
        "applications": [{"name": "website"}],
        "variants": [{"name": "A", "config": None},
                     {"name": "B", "config": None}],
        "audienceStrict": False,
        "audience": None,
    }
    if holdout_ids is not None:
        data["holdoutIds"] = list(holdout_ids)
    data.update(fields)
    return data


def holdout(id, name, seeds, unit_type=UNIT_TYPE, split=None,
            holdout_type="full", **fields):
    data = {
        "id": id,
        "name": name,
        "unitType": unit_type,
        "iteration": 1,
        "seedHi": seeds[0],
        "seedLo": seeds[1],
        "split": list(split) if split is not None else [0.1, 0.9],
        "trafficSeedHi": 0,
        "trafficSeedLo": 0,
        "trafficSplit": [0.0, 1.0],
        "fullOnVariant": 0,
        "applications": [],
        "variants": [{"name": "A", "config": None},
                     {"name": "B", "config": None}],
        "audienceStrict": False,
        "audience": None,
        "holdoutType": holdout_type,
    }
    data.update(fields)
    return data


def three_arm_holdout(id, name, seeds, **fields):
    return holdout(id, name, seeds, split=THREE_ARM_SPLIT,
                   holdout_type="all_full_on",
                   variants=[{"name": n, "config": None} for n in "ABC"],
                   **fields)


def with_variables(data, key, control="control", treatment="treatment"):
    data["variants"] = [
        {"name": "A", "config": json.dumps({key: control})},
        {"name": "B", "config": json.dumps({key: treatment})},
    ]
    return data


def context_data(experiments, holdouts=None, **root):
    """Deserialize like a real GET /context response."""
    payload = {"experiments": list(experiments)}
    if holdouts is not None:
        payload["holdouts"] = holdouts
    payload.update(root)
    content = json.dumps(payload)
    data = DefaultContextDataDeserializer().deserialize(
        bytes(content, encoding="utf-8"), 0, len(content))
    assert data is not None
    return data


class FakeClient(Client):
    def __init__(self):
        config = ClientConfig()
        config.endpoint = "https://sandbox.test.io/v1"
        config.api_key = "key"
        config.application = "website"
        config.environment = "production"
        super().__init__(config, DefaultHTTPClient(DefaultHTTPClientConfig()))
        self.published = []
        self.refresh_data = None

    def get_context_data(self):
        future = Future()
        future.set_result(self.refresh_data)
        return future

    def publish(self, event):
        self.published.append(event)
        future = Future()
        future.set_result(None)
        return future


class RecordingLogger(ContextEventLogger):
    def __init__(self):
        self.events = []
        self.on_event = None

    def handle_event(self, event_type, data):
        self.events.append((event_type, data))
        if self.on_event is not None:
            self.on_event(event_type, data)


class HoldoutFixture:
    """Creates ready contexts over a fake client that records publishes."""

    def set_up_fixture(self):
        self.clock = FixedClock(NOW)
        self.client = FakeClient()
        self.logger = RecordingLogger()

    def create_context(self, data, units=None, overrides=None,
                       custom_assignments=None, publish_delay=-1,
                       attributes=None):
        config = ContextConfig()
        config.units = {UNIT_TYPE: UID} if units is None else dict(units)
        config.publish_delay = publish_delay
        config.refresh_interval = 0
        if overrides:
            config.overrides = overrides
        if custom_assignments:
            config.custom_assignments = custom_assignments
        if attributes:
            config.attributes = attributes
        future = Future()
        future.set_result(data)
        return Context(
            self.clock, config, future,
            DefaultContextDataProvider(self.client),
            DefaultContextEventHandler(self.client), self.logger,
            DefaultVariableParser(),
            AudienceMatcher(DefaultAudienceDeserializer()),
            "website", "production")

    def refresh(self, context, data):
        self.client.refresh_data = data
        context.refresh()

    def publish(self, context):
        before = len(self.client.published)
        context.publish()
        self.assertEqual(before + 1, len(self.client.published))
        return self.client.published[-1]

    @staticmethod
    def exposure(id, name, variant, unit=UNIT_TYPE, assigned=True,
                 eligible=True, overridden=False, full_on=False,
                 custom=False, audience_mismatch=False, rule_override=False):
        return (id, name, unit, variant, assigned, eligible, overridden,
                full_on, custom, audience_mismatch, rule_override)

    def holdout_exposure(self, id, name, variant, unit=UNIT_TYPE):
        return self.exposure(id, name, variant, unit=unit)

    @staticmethod
    def exposure_tuples(exposures):
        return [(e.id, e.name, e.unit, e.variant, e.assigned, e.eligible,
                 e.overridden, e.fullOn, e.custom, e.audienceMismatch,
                 e.ruleOverride) for e in exposures or []]

    def assert_published(self, context, *exposures, unit=UNIT_TYPE,
                         uid=UID):
        event = self.publish(context)
        self.assertEqual(list(exposures),
                         self.exposure_tuples(event.exposures))
        self.assertEqual([(unit, hash_unit(uid))],
                         [(u.type, u.uid) for u in event.units
                          if u.type == unit])
        for exposure in event.exposures or []:
            self.assertEqual(NOW, exposure.exposedAt)
        return event

    def serialized(self, event):
        return bytes(DefaultContextEventSerializer().serialize(event))

    def exposure_events(self):
        return [data for event_type, data in self.logger.events
                if event_type == EventType.EXPOSURE]


def empty_data():
    data = ContextData()
    data.experiments = []
    return data
