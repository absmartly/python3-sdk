import subprocess
import sys
import unittest
import warnings
from concurrent.futures import Future

from sdk.absmartly import ABsmartly
from sdk.absmartly_config import ABsmartlyConfig
from sdk.audience_matcher import AudienceMatcher
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_event_handler import ContextEventHandler
from sdk.context_event_logger import ContextEventLogger, EventType
from sdk.context_publisher import ContextPublisher
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.default_context_event_handler import DefaultContextEventHandler
from sdk.default_context_publisher import DefaultContextPublisher
from sdk.default_variable_parser import DefaultVariableParser
from sdk.json.context_data import ContextData
from sdk.json.experiment import Experiment
from sdk.json.experiment_variant import ExperimentVariant
from sdk.time.fixed_clock import FixedClock


def done_future(value):
    future = Future()
    future.set_result(value)
    return future


class Provider(ContextDataProvider):
    def __init__(self, next_future=None):
        self.next = next_future

    def get_context_data(self):
        return self.next


class Publisher(ContextPublisher):
    def publish(self, context, event):
        return done_future(None)


class Recorder(ContextEventLogger):
    def __init__(self):
        self.events = []

    def handle_event(self, event_type, data):
        self.events.append((event_type, data))


class ReleasedImportPathsTest(unittest.TestCase):
    """Every v0.2.4 import path keeps working, without warnings."""

    RELEASED_IMPORTS = [
        "from sdk.absmartly import ABSmartly",
        "from sdk.absmartly import ABSmartlyConfig",
        "from sdk.absmartly import DefaultContextEventHandler",
        "from sdk.absmartly_config import ABSmartlyConfig",
        "from sdk.absmartly_config import ContextEventHandler",
        "from sdk.context import ContextEventHandler",
        "from sdk.context_event_handler import ContextEventHandler",
        "from sdk.default_context_event_handler import "
        "DefaultContextEventHandler",
    ]

    def test_released_imports_do_not_warn(self):
        for statement in self.RELEASED_IMPORTS:
            with self.subTest(statement=statement):
                result = subprocess.run(
                    [sys.executable, "-W", "error::DeprecationWarning",
                     "-c", statement],
                    capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_deprecated_names_are_the_released_classes(self):
        from sdk import absmartly, absmartly_config, context
        self.assertIs(absmartly_config.ABSmartlyConfig,
                      absmartly.ABSmartlyConfig)
        self.assertIs(ContextEventHandler, absmartly_config.ContextEventHandler)
        self.assertIs(ContextEventHandler, context.ContextEventHandler)
        self.assertIs(DefaultContextEventHandler,
                      absmartly.DefaultContextEventHandler)


class LegacyEventHandlerTest(unittest.TestCase):

    def test_subclass_without_publish_can_be_instantiated(self):
        class Partial(ContextEventHandler):
            pass

        handler = Partial()
        with self.assertRaises(NotImplementedError):
            handler.publish(None, None)

    def test_legacy_handler_is_a_context_publisher(self):
        class Legacy(ContextEventHandler):
            def publish(self, context, event):
                return done_future(None)

        self.assertIsInstance(Legacy(), ContextPublisher)

    def test_new_publisher_stays_strict(self):
        class Partial(ContextPublisher):
            pass

        with self.assertRaises(TypeError):
            Partial()

    def test_sdk_default_publisher_is_a_legacy_handler(self):
        sdk = ABsmartly(ABsmartlyConfig())
        self.assertIsInstance(sdk.context_publisher,
                              DefaultContextEventHandler)
        self.assertIsInstance(sdk.context_publisher, ContextEventHandler)
        self.assertIsInstance(sdk.context_publisher, DefaultContextPublisher)

    def test_default_handler_constructs_without_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            handler = DefaultContextEventHandler(client=None)
        self.assertIsInstance(handler, DefaultContextPublisher)
        self.assertIsInstance(handler, ContextEventHandler)


class InvalidInputReturnsNoneTest(unittest.TestCase):

    def make(self, data_future, provider=None, logger=None):
        config = ContextConfig()
        config.units = {"session_id": "abc"}
        config.publish_delay = -1
        config.refresh_interval = 0
        return Context(FixedClock(1_620_000_000_000), config, data_future,
                       provider or Provider(), Publisher(),
                       logger or Recorder(), DefaultVariableParser(),
                       AudienceMatcher(DefaultAudienceDeserializer()))

    def test_variable_parser_returns_none_on_invalid_json(self):
        parser = DefaultVariableParser()
        self.assertIsNone(parser.parse(None, "exp", "variant", "{invalid"))
        self.assertEqual({"a": 1}, parser.parse(None, "e", "v", '{"a": 1}'))

    def test_deserializer_returns_none_on_invalid_input(self):
        deserializer = DefaultContextDataDeserializer()
        payload = b"not json"
        self.assertIsNone(deserializer.deserialize(payload, 0, len(payload)))

    def data_with_config(self, config):
        variant0 = ExperimentVariant()
        variant0.name = "A"
        variant0.config = config
        experiment = Experiment()
        experiment.id = 1
        experiment.name = "exp"
        experiment.unitType = "session_id"
        experiment.iteration = 1
        experiment.seedHi = experiment.seedLo = 0
        experiment.trafficSeedHi = experiment.trafficSeedLo = 0
        experiment.split = [1.0]
        experiment.trafficSplit = [0.0, 1.0]
        experiment.fullOnVariant = 0
        experiment.audience = None
        experiment.audienceStrict = False
        experiment.variants = [variant0]
        experiment.customFieldValues = None
        data = ContextData()
        data.experiments = [experiment]
        return data

    def test_invalid_variant_config_logs_error_and_has_no_variables(self):
        logger = Recorder()
        context = self.make(done_future(self.data_with_config("{invalid")),
                            logger=logger)
        self.assertTrue(context.is_ready())
        self.assertFalse(context.is_failed())
        self.assertEqual({}, context.get_variable_keys())
        self.assertIn(EventType.ERROR, [e for e, _ in logger.events])

    def test_non_object_variant_config_logs_error_and_has_no_variables(self):
        for config in ['"abc"', '[1, 2]', '5', 'true', 'null']:
            with self.subTest(config=config):
                logger = Recorder()
                context = self.make(
                    done_future(self.data_with_config(config)),
                    logger=logger)
                self.assertTrue(context.is_ready())
                self.assertFalse(context.is_failed())
                self.assertEqual({}, context.get_variable_keys())
                self.assertEqual("x", context.get_variable_value("a", "x"))
                self.assertEqual("x", context.get_variable_value(1, "x"))
                self.assertEqual([EventType.ERROR],
                                 [e for e, _ in logger.events
                                  if e != EventType.READY])

    def test_none_data_fails_context_already_done(self):
        context = self.make(done_future(None))
        self.assertTrue(context.is_ready())
        self.assertTrue(context.is_failed())

    def test_none_data_fails_pending_context_without_hanging(self):
        data_future = Future()
        context = self.make(data_future)
        data_future.set_result(None)
        context.wait_until_ready()
        self.assertTrue(context.is_ready())
        self.assertTrue(context.is_failed())
        self.assertEqual(0, context.get_treatment("exp"))

    def test_none_data_on_refresh_fails_refresh_and_keeps_data(self):
        data = ContextData()
        data.experiments = []
        provider = Provider(done_future(None))
        context = self.make(done_future(data), provider=provider)
        with self.assertRaises(RuntimeError):
            context.refresh_async().result(timeout=1)
        self.assertFalse(context.is_failed())
        self.assertIs(data, context.data)


if __name__ == "__main__":
    unittest.main()
