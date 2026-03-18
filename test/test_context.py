import os
import threading
import time
import typing
import unittest
from concurrent.futures import Future

from sdk.context_config import ContextConfig

from sdk.context import Context

from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.default_context_event_handler import DefaultContextEventHandler

from sdk.default_context_data_provider import DefaultContextDataProvider

from sdk.audience_matcher import AudienceMatcher
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig

from sdk.default_variable_parser import DefaultVariableParser

from sdk.context_event_logger import ContextEventLogger, EventType

from sdk.context_event_handler import ContextEventHandler

from sdk.context_data_provider import ContextDataProvider

from sdk.default_audience_deserializer import DefaultAudienceDeserializer

from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.json.attribute import Attribute
from sdk.json.context_data import ContextData
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.publish_event import PublishEvent
from sdk.json.unit import Unit
from sdk.time.clock import Clock
from sdk.time.fixed_clock import FixedClock


class ContextEventLoggerTest(ContextEventLogger):
    logger_data: typing.Optional[object] = None
    logger_type: typing.Optional[EventType] = None

    def handle_event(self, event_type: EventType, data: object):
        self.logger_data = data
        self.logger_type = event_type


class ClientContextMock(Client):
    def get_context_data(self):
        future = Future()
        context_data = ContextData()
        context_data.experiments = []
        future.set_result(context_data)
        return future

    def publish(self, event: PublishEvent):
        future = Future()
        future.set_result(None)
        return future


def string_in_list(st: str, lst: list):
    for val in lst:
        if val.name == st:
            return True
    return False


class ContextTest(unittest.TestCase):

    expectedVariants = {
        "exp_test_ab": 1,
        "exp_test_abc": 2,
        "exp_test_not_eligible": 0,
        "exp_test_fullon": 2,
        "exp_test_new": 1,
    }

    expectedVariables = {
        "banner.border": 1.0,
        "banner.size": "large",
        "button.color": "red",
        "submit.color": "blue",
        "submit.shape": "rect",
        "show-modal": True,
    }

    variableExperiments = {
        "banner.border": ["exp_test_ab"],
        "banner.size": ["exp_test_ab"],
        "button.color": ["exp_test_abc"],
        "card.width": ["exp_test_not_eligible"],
        "submit.color": ["exp_test_fullon"],
        "submit.shape": ["exp_test_fullon"],
        "show-modal": ["exp_test_new"],
    }

    units = {
        "session_id": "e791e240fcd3df7d238cfc285f475e8152fcc0ec",
        "user_id": "123456789",
        "email": "bleh@absmartly.com"
    }

    deser = DefaultContextDataDeserializer()
    audeser = DefaultAudienceDeserializer()
    data: ContextData
    refresh_data: ContextData
    audience_strict_data: ContextData
    data_future: Future
    data_future_strict: Future
    data_future_refresh: Future
    data_future_ready: Future
    data_future_failed: Future
    clock: Clock
    data_provider: ContextDataProvider
    event_handler: ContextEventHandler
    event_logger: ContextEventLogger = ContextEventLoggerTest()
    variable_parser: DefaultVariableParser
    audience_matcher: AudienceMatcher

    def set_up(self):
        with open(os.path.join(os.path.dirname(__file__),
                               'res/context.json'),
                  'r') as file:
            content = file.read()
        with open(os.path.join(os.path.dirname(__file__),
                               'res/context-strict.json'),
                  'r') as file:
            content_strict = file.read()
        with open(os.path.join(os.path.dirname(__file__),
                               'res/refreshed.json'),
                  'r') as file:
            refreshed = file.read()
        self.data = self.deser.deserialize(
            bytes(content, encoding="utf-8"),
            0,
            len(content))
        self.audience_strict_data = self.deser.deserialize(
            bytes(content_strict, encoding="utf-8"),
            0,
            len(content_strict))
        self.refresh_data = self.deser.deserialize(
            bytes(refreshed, encoding="utf-8"),
            0,
            len(refreshed))
        self.data_future_ready = Future()
        self.data_future_ready.set_result(self.data)
        self.data_future = Future()
        self.data_future_failed = Future()
        self.data_future_failed.set_exception(RuntimeError("FAILED"))
        self.data_future_strict = Future()
        self.data_future_strict.set_result(self.audience_strict_data)
        self.data_future_refresh = Future()
        self.data_future_refresh.set_result(self.refresh_data)

        self.clock = FixedClock(1_620_000_000_000)
        client_config = ClientConfig()
        client_config.endpoint = "https://sandbox.test.io/v1"
        client_config.api_key = "gfsgsgsf"
        client_config.application = "www"
        client_config.environment = "test"
        default_client_config = DefaultHTTPClientConfig()
        default_client = DefaultHTTPClient(default_client_config)
        self.client = ClientContextMock(client_config, default_client)
        self.data_provider = DefaultContextDataProvider(self.client)
        self.event_handler = DefaultContextEventHandler(self.client)
        self.variable_parser = DefaultVariableParser()
        self.audience_matcher = AudienceMatcher(self.audeser)

    def create_test_context(self, config, data_future):
        return Context(self.clock,
                       config, data_future,
                       self.data_provider,
                       self.event_handler,
                       self.event_logger,
                       self.variable_parser,
                       self.audience_matcher)

    def test_constructor_sets_overrides(self):
        self.set_up()
        overrides = {"exp_test": 2, "exp_test_1": 1}
        config = ContextConfig()
        config.units = self.units
        config.overrides = overrides

        context = self.create_test_context(config, self.data_future)
        for key, value in overrides.items():
            res = context.get_override(key)
            self.assertEqual(value, res)

    def test_constructor_sets_custom_assignments(self):
        self.set_up()
        cassignments = {"exp_test": 2, "exp_test_1": 1}
        config = ContextConfig()
        config.units = self.units
        config.cassigmnents = cassignments

        context = self.create_test_context(config, self.data_future)
        for key, value in cassignments.items():
            res = context.get_custom_assignment(key)
            self.assertEqual(value, res)

    def test_becomes_ready_with_completed_future(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        context.close()

    def test_becomes_ready_exceptionally_with_completed_future(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_failed)
        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data.experiments, None)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(True, context.is_failed())
        context.close()

    def test_becomes_ready_with_exception(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.data_future.set_exception(RuntimeError("FAILED"))
        context.wait_until_ready()
        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data.experiments, None)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(True, context.is_failed())
        context.close()

    def test_becomes_ready_without_exception(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.data_future.set_result(self.data)
        context.wait_until_ready()
        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        context.close()

    def test_wait_until_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())

        def set_result():
            self.data_future.set_result(self.data)
        th = threading.Thread(target=set_result)
        th.start()

        context.wait_until_ready()
        data = context.get_data()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)
        context.close()

    def test_wait_until_ready_completed(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.wait_until_ready()
        data = context.get_data()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)
        context.close()

    def test_wait_until_ready_async(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())
        future = context.wait_until_ready_async()
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())

        def set_result():
            self.data_future.set_result(self.data)
        th = threading.Thread(target=set_result)
        th.start()

        future.result()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)
        context.close()

    def test_wait_until_ready_async_completed(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        future = context.wait_until_ready_async()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        future.result()
        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)
        context.close()

    def test_error_when_closing(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)

        context.track("goal1", {"amount": 125, "hours": 245})
        self.assertEqual(False, context.is_closing())
        self.assertEqual(False, context.is_closed())

        def sl(event):
            future = Future()

            def set_result():
                time.sleep(0.2)
                future.set_result(None)
            th = threading.Thread(target=set_result)
            th.start()
            return future
        self.client.publish = sl

        context.close_async()

        self.assertEqual(True, context.is_closing())
        self.assertEqual(False, context.is_closed())
        try:
            context.set_attribute("attr1", "value1")
        except RuntimeError as e:
            self.assertIsNotNone(e)
            self.assertEqual("ABsmartly Context is finalizing.", str(e))
        time.sleep(0.3)
        context.close()

    def test_error_when_closed(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data, self.data)

        context.track("goal1", {"amount": 125, "hours": 245})
        self.assertEqual(False, context.is_closing())
        self.assertEqual(False, context.is_closed())

        def sl(event):
            future = Future()

            def set_result():
                time.sleep(0.2)
                future.set_result(None)
            th = threading.Thread(target=set_result)
            th.start()
            return future
        self.client.publish = sl

        context.close()

        self.assertEqual(False, context.is_closing())
        self.assertEqual(True, context.is_closed())
        try:
            context.set_attribute("attr1", "value1")
        except RuntimeError as e:
            self.assertIsNotNone(e)
            self.assertEqual("ABsmartly Context is finalized.", str(e))
        time.sleep(0.3)
        context.close()

    def test_get_experiments(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        data = context.get_data()
        self.assertIsNotNone(data)
        self.assertEqual(data.experiments, self.data.experiments)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        context.close()

    def test_refresh_timer_when_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.data_future.set_result(self.data)

        def sl():
            future = Future()

            def set_result():
                time.sleep(0.2)
                data = ContextData()
                data.experiments = []
                future.set_result(data)
            th = threading.Thread(target=set_result)
            th.start()
            return future
        self.client.get_context_data = sl

        futu = context.refresh_async()
        self.assertEqual(True, context.refreshing.value)
        context.wait_until_ready()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        futu.result()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.assertEqual(False, context.refreshing.value)
        context.close()

    def test_unit_empty(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        try:
            context.set_unit("db_user_id", "")
        except ValueError as e:
            self.assertEqual("Unit 'db_user_id' UID must not be blank.", str(e))

        try:
            context.set_unit("session_id", "1")
        except ValueError as e:
            self.assertEqual("Unit 'session_id' UID already set.", str(e))

        context.close()

    def test_set_attributes(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_attribute("db_user_id", "test")
        context.set_attributes({"db_user_id2": "test2"})

        self.assertEqual(context.is_failed(), False)
        context.close()

    def test_set_overrides(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_override("db_user_id", 1)
        self.assertEqual(1, context.get_override("db_user_id"))
        context.set_overrides({"db_user_id2": 1})
        self.assertEqual(1, context.get_override("db_user_id2"))

        self.data_future.set_result(self.data)
        context.wait_until_ready()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.assertEqual(1, context.get_override("db_user_id"))
        self.assertEqual(1, context.get_override("db_user_id2"))

        context.close()

    def test_set_overrides_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_override("db_user_id", 1)
        self.assertEqual(1, context.get_override("db_user_id"))
        context.set_overrides({"db_user_id2": 1})
        self.assertEqual(1, context.get_override("db_user_id2"))

        self.data_future.set_result(self.data)
        context.wait_until_ready()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.assertEqual(1, context.get_override("db_user_id"))
        self.assertEqual(1, context.get_override("db_user_id2"))

        self.assertIsNone(context.get_override("db_user_id3"))
        context.close()

    def test_assignment_does_not_override_full_on_or_not_assignments(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_custom_assignment("exp_test_not_eligible", 3)
        context.set_custom_assignment("exp_test_fullon", 3)

        res = context.get_treatment("exp_test_not_eligible")
        self.assertEqual(0, res)
        res = context.get_treatment("exp_test_fullon")
        self.assertEqual(2, res)
        self.assertEqual(2, context.get_pending_count())
        self.assertEqual(3, context.get_custom_assignment("exp_test_fullon"))

        self.assertEqual(
            3,
            context.get_custom_assignment("exp_test_not_eligible"))
        self.assertIsNone(context.get_custom_assignment("db_user_id3"))
        context.close()

    def test_set_overrides_clear_assignment_cache(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_override("db_user_id", 1)
        self.assertEqual(1, context.get_override("db_user_id"))
        context.set_overrides({"db_user_id2": 1})
        self.assertEqual(1, context.get_override("db_user_id2"))

        self.data_future.set_result(self.data)
        context.wait_until_ready()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.assertEqual(1, context.get_override("db_user_id"))
        self.assertEqual(1, context.get_override("db_user_id2"))

        res = context.get_treatment("db_user_id")
        self.assertEqual(res, context.get_override("db_user_id"))
        self.assertEqual(1, context.get_pending_count())

        self.assertIsNone(context.get_override("db_user_id3"))
        context.close()

    def test_set_custom_assignments_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_custom_assignment("db_user_id", 1)
        self.assertEqual(1, context.get_custom_assignment("db_user_id"))
        context.set_custom_assignments({"db_user_id2": 1})
        self.assertEqual(1, context.get_custom_assignment("db_user_id2"))

        self.assertIsNone(context.get_custom_assignment("db_user_id3"))
        context.close()

    def test_set_custom_assignments(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_custom_assignment("db_user_id", 1)
        self.assertEqual(1, context.get_custom_assignment("db_user_id"))
        context.set_custom_assignments({"db_user_id2": 1})
        self.assertEqual(1, context.get_custom_assignment("db_user_id2"))

        self.data_future.set_result(self.data)
        context.wait_until_ready()
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        self.assertEqual(1, context.get_custom_assignment("db_user_id"))
        self.assertEqual(1, context.get_custom_assignment("db_user_id2"))

        self.assertIsNone(context.get_custom_assignment("db_user_id3"))
        context.close()

    def test_set_custom_assignments_pending_assignment_cache(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_custom_assignment("exp_test_ab", 2)
        context.set_custom_assignments({"exp_test_abc": 3})

        self.assertEqual(0, context.get_pending_count())
        res = context.get_treatment("exp_test_ab")
        self.assertEqual(2, res)
        self.assertEqual(1, context.get_pending_count())

        res = context.get_treatment("exp_test_abc")
        self.assertEqual(3, res)
        self.assertEqual(2, context.get_pending_count())

        context.set_custom_assignment("exp_test_ab", 4)
        res = context.get_treatment("exp_test_ab")
        self.assertEqual(4, res)
        self.assertEqual(3, context.get_pending_count())

        context.close()

    def test_peek_treatment(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        for experiment in self.data.experiments:
            res = context.peek_treatment(experiment.name)
            self.assertEqual(self.expectedVariants[experiment.name], res)

        res = context.peek_treatment("not_found")
        self.assertEqual(0, res)
        context.close()

    def test_peek_variable(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        for key, experiments in self.variableExperiments.items():
            res = context.peek_variable_value(key, 17)
            if experiments[0] != "exp_test_not_eligible" and \
                    string_in_list(experiments[0], self.data.experiments):
                self.assertEqual(self.expectedVariables[key], res)
            else:
                self.assertEqual(17, res)

        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_peek_variable_strict(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_strict)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        res = context.peek_variable_value("banner.size", "small")
        self.assertEqual("small", res)

        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_get_variable(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        for key, experiments in self.variableExperiments.items():
            res = context.get_variable_value(key, 17)
            if experiments[0] != "exp_test_not_eligible" and \
                    string_in_list(experiments[0], self.data.experiments):
                self.assertEqual(self.expectedVariables[key], res)
            else:
                self.assertEqual(17, res)

        self.assertEqual(4, context.get_pending_count())
        context.close()

    def test_get_variable_strict(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_strict)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        res = context.get_variable_value("banner.size", "small")
        self.assertEqual("small", res)

        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_get_variable_keys(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_refresh)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        res = context.get_variable_keys()
        self.assertEqual(self.variableExperiments, res)

        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_get_custom_field_keys(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        res = context.get_custom_field_keys()
        self.assertEqual(["country", "languages", "overrides"], res)
        context.close()

    def test_get_custom_field_values(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        self.assertEqual(None, context.get_custom_field_value("not_found", "not_found"))
        self.assertEqual(None, context.get_custom_field_value("exp_test_ab", "not_found"))

        self.assertEqual("US,PT,ES,DE,FR", context.get_custom_field_value("exp_test_ab", "country"))
        self.assertEqual({'123': 1, '456': 0}, context.get_custom_field_value("exp_test_ab", "overrides"))
        self.assertEqual("json", context.get_custom_field_type("exp_test_ab", "overrides"))

        self.assertEqual(None, context.get_custom_field_value("exp_test_ab", "languages"))
        self.assertEqual(None, context.get_custom_field_type("exp_test_ab", "languages"))

        self.assertEqual(None, context.get_custom_field_value("exp_test_abc", "overrides"))
        self.assertEqual(None, context.get_custom_field_type("exp_test_abc", "overrides"))

        self.assertEqual("en-US,en-GB,pt-PT,pt-BR,es-ES,es-MX", context.get_custom_field_value("exp_test_abc", "languages"))
        self.assertEqual("string", context.get_custom_field_type("exp_test_abc", "languages"))

        self.assertEqual(None, context.get_custom_field_value("exp_test_no_custom_fields", "country"))
        self.assertEqual(None, context.get_custom_field_type("exp_test_no_custom_fields", "country"))

        self.assertEqual(None, context.get_custom_field_value("exp_test_no_custom_fields", "overrides"))
        self.assertEqual(None, context.get_custom_field_type("exp_test_no_custom_fields", "overrides"))

        self.assertEqual(None, context.get_custom_field_value("exp_test_no_custom_fields", "languages"))
        self.assertEqual(None, context.get_custom_field_type("exp_test_no_custom_fields", "languages"))

        context.close()

    def test_track(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.track("goal1", {"amount": 125, "hours": 245})
        self.assertEqual(1, context.get_pending_count())
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_closed())

        context.publish()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_closed())

        context.close()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(True, context.is_ready())
        self.assertEqual(True, context.is_closed())

    def test_track_not_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.track("goal1", {"amount": 125, "hours": 245})
        self.assertEqual(1, context.get_pending_count())
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_closed())

        context.track("goal2", {"amount": 125, "hours": 245})
        self.assertEqual(2, context.get_pending_count())
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_closed())

        context.publish()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_closed())

        context.close()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(False, context.is_ready())
        self.assertEqual(True, context.is_closed())

    def test_publish_resets_queue_and_keeps_attr_over_and_assignments(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.set_custom_assignment("exp_test_ab", 2)
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(2, context.get_treatment("exp_test_ab"))

        context.track("goal2", {"amount": 125, "hours": 245})
        self.assertEqual(2, context.get_pending_count())
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_closed())

        context.publish()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_closed())

        self.assertEqual(2, context.get_custom_assignment("exp_test_ab"))
        context.close()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(True, context.is_ready())
        self.assertEqual(True, context.is_closed())

    def test_starts_publish_timeout_when_ready_with_queue_not_empty(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.track("goal2", {"amount": 125, "hours": 245})
        self.assertEqual(1, context.get_pending_count())
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_closed())

        context.publish()
        self.assertEqual(None, context.timeout)
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(False, context.is_ready())
        self.assertEqual(False, context.is_closed())
        self.data_future.set_result(self.data)
        context.wait_until_ready()
        self.assertEqual(None, context.get_custom_assignment("exp_test_ab"))
        context.close()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(True, context.is_ready())
        self.assertEqual(True, context.is_closed())

    def test_publish_success(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        context.set_attribute("test", "value1")
        context.set_custom_assignment("testAssignment", 5)
        res = context.get_treatment("testAssignment")
        self.assertEqual(0, res)

        event = PublishEvent()
        event.hashed = True
        event.units = []
        unit = Unit()
        unit.type = "session_id"
        unit.uid = "pAE3a1i5Drs5mKRNq56adA"
        unit1 = Unit()
        unit1.type = "user_id"
        unit1.uid = "JfnnlDI7RTiF9RgfG2JNCw"
        unit2 = Unit()
        unit2.type = "email"
        unit2.uid = "IuqYkNRfEx5yClel4j3NbA"
        event.units.append(unit)
        event.units.append(unit1)
        event.units.append(unit2)
        event.publishedAt = 1620000000000
        exposure = Exposure()
        exposure.id = 0
        exposure.name = "testAssignment"
        exposure.unit = ""
        exposure.variant = 0
        exposure.exposedAt = 1620000000000
        exposure.eligible = True
        event.exposures = []
        event.exposures.append(exposure)
        goal = GoalAchievement()
        goal.name = "goal1"
        goal.achievedAt = 1620000000000
        goal.properties = {"amount": 125}
        event.goals = []
        event.goals.append(goal)
        event.attributes = []
        attribute = Attribute()
        attribute.name = "test"
        attribute.value = "value1"
        attribute.setAt = 1620000000000
        event.attributes.append(attribute)

        def pubka(pub):
            self.assertEqual(event.goals[0].properties,
                             pub.goals[0].properties)
            self.assertEqual(event.goals[0].name,
                             pub.goals[0].name)
            self.assertEqual(event.attributes[0].name,
                             pub.attributes[0].name)
            self.assertEqual(event.attributes[0].value,
                             pub.attributes[0].value)
            self.assertEqual(event.exposures[0].name,
                             pub.exposures[0].name)
            self.assertEqual(event.exposures[0].variant,
                             pub.exposures[0].variant)
            self.assertEqual(event.units[0].uid,
                             pub.units[0].uid)
            self.assertEqual(len(event.exposures),
                             len(pub.exposures))
            self.assertEqual(len(event.goals),
                             len(pub.goals))
            self.assertEqual(len(event.units),
                             len(pub.units))
            self.assertEqual(len(event.attributes),
                             len(pub.attributes))
            future = Future()
            future.set_result(None)
            return future

        self.client.publish = pubka

        context.track("goal1", {"amount": 125})
        context.publish()
        context.close()

    def test_flush_mapper(self):
        result = "pAE3a1i5Drs5mKRNq56adA"
        force = result.encode('ascii', errors='ignore')\
            .decode()
        self.assertEqual(result, force)

        result = "pAE3a1i5Drs5%KRNq56adA"
        force = "pAE3a1i5Drs5%паKRNq56adA"\
            .encode('ascii', errors='ignore')\
            .decode()
        self.assertEqual(result, force)

    def test_refresh_async(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_refresh)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        def sl():
            future = Future()

            def set_result():
                future.set_result(self.data)
            th = threading.Thread(target=set_result)
            th.start()
            return future
        self.client.get_context_data = sl
        self.assertTrue(context.refresh_timer is not None)
        fut = context.refresh_async()
        fut.result()
        self.assertTrue(context.refresh_timer is not None)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())
        res = context.get_experiments()
        self.assertEqual("exp_test_ab", res[0])
        context.close()

    def test_refresh_clear_assignment_cache_for_started_experiment(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        res = context.get_treatment("exp_test_new")
        self.assertEqual(0, res)
        self.assertEqual(1, context.get_pending_count())

        def sl():
            future = Future()

            def set_result():
                future.set_result(self.data)
            th = threading.Thread(target=set_result)
            th.start()
            return future
        self.client.get_context_data = sl

        context.refresh()
        res = context.get_experiments()
        self.assertEqual("exp_test_ab", res[0])
        self.assertEqual("exp_test_fullon", res[3])
        self.assertEqual(4, len(res))
        res = context.get_treatment("exp_test_fullon")
        self.assertEqual(2, res)
        self.assertEqual(2, context.get_pending_count())
        context.close()

    def test_logger_called(self):
        self.event_logger.logger_data = None
        self.event_logger.logger_type = None
        self.assertIsNone(self.event_logger.logger_data)
        self.assertIsNone(self.event_logger.logger_type)

        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(self.event_logger.logger_type, EventType.READY)
        self.assertEqual(type(self.event_logger.logger_data),
                         type(ContextData()))
        self.assertEqual(True, context.is_ready())

        res = context.get_treatment("exp_test_new")
        self.assertEqual(0, res)
        self.assertEqual(1, context.get_pending_count())
        self.assertEqual(self.event_logger.logger_type, EventType.EXPOSURE)
        self.assertEqual(type(self.event_logger.logger_data),
                         type(Exposure()))

        def sl():
            future = Future()

            def set_result():
                future.set_result(self.data)
            th = threading.Thread(target=set_result)
            th.start()
            return future
        self.client.get_context_data = sl
        self.assertEqual(self.event_logger.logger_type, EventType.EXPOSURE)
        self.assertEqual(type(self.event_logger.logger_data),
                         type(Exposure()))

        context.refresh()
        self.assertEqual(self.event_logger.logger_type, EventType.REFRESH)
        self.assertEqual(type(self.event_logger.logger_data),
                         type(ContextData()))
        res = context.get_experiments()
        self.assertEqual(self.event_logger.logger_type, EventType.REFRESH)
        self.assertEqual(type(self.event_logger.logger_data),
                         type(ContextData()))
        self.assertEqual("exp_test_ab", res[0])
        self.assertEqual("exp_test_fullon", res[3])
        self.assertEqual(4, len(res))
        res = context.get_treatment("exp_test_fullon")
        self.assertEqual(self.event_logger.logger_type, EventType.EXPOSURE)
        self.assertEqual(type(self.event_logger.logger_data),
                         type(Exposure()))
        self.assertEqual(2, res)
        self.assertEqual(2, context.get_pending_count())
        self.assertEqual(self.event_logger.logger_type, EventType.EXPOSURE)
        self.assertEqual(type(self.event_logger.logger_data),
                         type(Exposure()))
        context.close()
        self.assertEqual(self.event_logger.logger_type, EventType.CLOSE)
        self.assertIsNone(self.event_logger.logger_data)

    def test_assignment_with_historical_exposed_at_timestamp(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        res = context.get_treatment(
            "exp_test_historical_timestamp",
            exposed_at = 1713218400000
        )
        exposure = context.exposures[0]
        self.assertEqual(1713218400000, exposure.exposedAt)
        context.close()

    def test_achievement_with_historical_achieved_at_timestamp(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())
        self.assertEqual(False, context.is_failed())

        context.track(
            "goal_test_historical_timestamp",
            properties = {},
            achieved_at = 1713218400000
        )
        achievement = context.achievements[0]
        self.assertEqual(1713218400000, achievement.achievedAt)
        context.close()

    def test_publish_timeout_triggers_auto_publish(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        config.publish_delay = 0.1
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        published = []

        def mock_publish(event):
            published.append(event)
            future = Future()
            future.set_result(None)
            return future

        self.client.publish = mock_publish

        context.track("goal1", {"amount": 100})
        self.assertEqual(1, context.get_pending_count())
        self.assertIsNotNone(context.timeout)

        time.sleep(0.3)

        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(1, len(published))
        context.close()

    def test_publish_timeout_reset_on_manual_publish(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        config.publish_delay = 1
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        context.track("goal1", {"amount": 100})
        self.assertIsNotNone(context.timeout)

        context.publish()

        self.assertIsNone(context.timeout)
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_publish_timeout_with_multiple_events(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        config.publish_delay = 0.2
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        published_events = []

        def mock_publish(event):
            published_events.append(event)
            future = Future()
            future.set_result(None)
            return future

        self.client.publish = mock_publish

        context.track("goal1", {"amount": 100})
        context.track("goal2", {"amount": 200})
        context.track("goal3", {"amount": 300})
        context.get_treatment("exp_test_ab")

        self.assertEqual(4, context.get_pending_count())

        time.sleep(0.4)

        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(1, len(published_events))
        event = published_events[0]
        self.assertEqual(3, len(event.goals))
        self.assertEqual(1, len(event.exposures))
        context.close()

    def test_publish_timeout_on_close(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        config.publish_delay = 10
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        published_events = []

        def mock_publish(event):
            published_events.append(event)
            future = Future()
            future.set_result(None)
            return future

        self.client.publish = mock_publish

        context.track("goal1", {"amount": 100})
        self.assertEqual(1, context.get_pending_count())

        context.close()

        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(1, len(published_events))
        self.assertTrue(context.is_closed())

    def test_publish_timeout_edge_cases(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        config.publish_delay = 0
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        context.track("goal1", {"amount": 100})
        self.assertIsNotNone(context.timeout)

        time.sleep(0.1)
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_set_attribute_single(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        context.set_attribute("user_age", 25)
        context.set_attribute("user_country", "US")

        self.assertEqual(2, len(context.attributes))

        names = [attr.name for attr in context.attributes]
        self.assertIn("user_age", names)
        self.assertIn("user_country", names)
        context.close()

    def test_set_attributes_batch(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        attrs = {
            "user_age": 25,
            "user_country": "US",
            "is_premium": True
        }
        context.set_attributes(attrs)

        self.assertEqual(3, len(context.attributes))

        names = [attr.name for attr in context.attributes]
        for key in attrs.keys():
            self.assertIn(key, names)
        context.close()

    def test_get_attribute(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        context.set_attribute("user_age", 25)

        found = None
        for attr in context.attributes:
            if attr.name == "user_age":
                found = attr
                break

        self.assertIsNotNone(found)
        self.assertEqual(25, found.value)
        context.close()

    def test_attribute_persistence_across_publish(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        context.set_attribute("user_age", 25)
        context.track("goal1", {"amount": 100})

        context.publish()

        self.assertEqual(1, len(context.attributes))
        self.assertEqual("user_age", context.attributes[0].name)
        self.assertEqual(25, context.attributes[0].value)
        context.close()

    def test_set_unit_valid(self):
        self.set_up()
        config = ContextConfig()
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        context.set_unit("device_id", "device-123")

        self.assertIn("device_id", context.units)
        self.assertEqual("device-123", context.units["device_id"])
        context.close()

    def test_set_unit_empty_throws(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        with self.assertRaises(ValueError) as ctx:
            context.set_unit("device_id", "")

        self.assertEqual("Unit 'device_id' UID must not be blank.", str(ctx.exception))
        context.close()

    def test_set_unit_duplicate_throws(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        with self.assertRaises(ValueError) as ctx:
            context.set_unit("user_id", "different-value")

        self.assertEqual("Unit 'user_id' UID already set.", str(ctx.exception))
        context.close()

    def test_set_units_batch(self):
        self.set_up()
        config = ContextConfig()
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        units = {
            "device_id": "device-123",
            "session_id": "session-456"
        }
        context.set_units(units)

        self.assertIn("device_id", context.units)
        self.assertIn("session_id", context.units)
        self.assertEqual("device-123", context.units["device_id"])
        self.assertEqual("session-456", context.units["session_id"])
        context.close()

    def test_recovery_from_failed_publish(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        publish_calls = []

        def failing_publish(event):
            publish_calls.append(event)
            future = Future()
            future.set_exception(RuntimeError("Publish failed"))
            return future

        self.client.publish = failing_publish

        context.track("goal1", {"amount": 100})

        try:
            context.publish()
        except RuntimeError:
            pass

        self.assertFalse(context.is_closed())
        self.assertFalse(context.is_failed())

        def success_publish(event):
            future = Future()
            future.set_result(None)
            return future
        self.client.publish = success_publish
        context.close()

    def test_recovery_from_failed_refresh(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        def failing_get_context_data():
            future = Future()
            future.set_exception(RuntimeError("Refresh failed"))
            return future

        self.client.get_context_data = failing_get_context_data

        try:
            context.refresh()
        except RuntimeError:
            pass

        self.assertTrue(context.is_ready())
        self.assertFalse(context.is_closed())
        context.close()

    def test_graceful_degradation_no_network(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        original_data = context.get_data()

        def network_failure():
            future = Future()
            future.set_exception(ConnectionError("No network"))
            return future

        self.client.get_context_data = network_failure

        try:
            context.refresh()
        except Exception:
            pass

        current_data = context.get_data()
        self.assertEqual(original_data, current_data)

        treatment = context.get_treatment("exp_test_ab")
        self.assertEqual(self.expectedVariants["exp_test_ab"], treatment)
        context.close()

    def test_error_callback_integration(self):
        self.set_up()
        error_events = []

        class ErrorTrackingLogger(ContextEventLogger):
            def handle_event(self, event_type: EventType, data: object):
                if event_type == EventType.ERROR:
                    error_events.append(data)

        config = ContextConfig()
        config.units = self.units
        self.event_logger = ErrorTrackingLogger()
        context = self.create_test_context(config, self.data_future_ready)
        self.assertEqual(True, context.is_ready())

        def failing_get_context_data():
            future = Future()
            future.set_exception(RuntimeError("Test error"))
            return future

        self.client.get_context_data = failing_get_context_data

        try:
            context.refresh()
        except RuntimeError:
            pass

        self.assertEqual(1, len(error_events))
        self.assertIsInstance(error_events[0], RuntimeError)
        context.close()

    def test_flush_atomically_clears_events(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        context.track("goal1", {"amount": 100})
        self.assertEqual(1, context.get_pending_count())

        published_events = []
        original_publish = self.client.publish

        def capturing_publish(event):
            published_events.append(event)
            context.track("goal2", {"amount": 200})
            return original_publish(event)

        self.client.publish = capturing_publish

        context.flush()

        self.assertEqual(1, len(published_events))
        self.assertEqual(1, len(published_events[0].goals))
        self.assertEqual("goal1", published_events[0].goals[0].name)
        self.assertEqual(1, context.get_pending_count())
        self.client.publish = original_publish
        context.close()

    def test_flush_restores_events_on_failure(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        context.track("goal1", {"amount": 100})
        self.assertEqual(1, context.get_pending_count())

        def failing_publish(event):
            future = Future()
            future.set_exception(RuntimeError("Publish failed"))
            return future

        self.client.publish = failing_publish

        try:
            context.publish()
        except RuntimeError:
            pass

        self.assertEqual(1, context.get_pending_count())
        self.assertEqual(1, len(context.achievements))
        self.assertEqual("goal1", context.achievements[0].name)

        self.client.publish = lambda event: (
            lambda f=Future(): (f.set_result(None), f)[1]
        )()
        context.close()

    def test_close_sets_close_error_on_failure(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        context.track("goal1", {"amount": 100})

        def failing_publish(event):
            future = Future()
            future.set_exception(RuntimeError("Publish failed"))
            return future

        self.client.publish = failing_publish
        with self.assertRaises(RuntimeError) as cm:
            context.close()

        self.assertIsNotNone(context.close_error)
        self.assertIsInstance(context.close_error, RuntimeError)
        self.assertEqual("Publish failed", str(cm.exception))

    def test_close_no_error_on_success(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        context.track("goal1", {"amount": 100})
        context.close()

        self.assertIsNone(context.close_error)

    def test_set_attribute_increments_attrs_seq_atomically(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        self.assertEqual(0, context._attrs_seq)
        context.set_attribute("attr1", "value1")
        self.assertEqual(1, context._attrs_seq)
        context.set_attribute("attr2", "value2")
        self.assertEqual(2, context._attrs_seq)

        self.assertEqual(2, len(context.attributes))
        context.close()

    def test_ready_future_not_set_to_none(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units

        context = self.create_test_context(config, self.data_future)
        self.data_future.set_result(self.data)

        self.assertTrue(context.is_ready())
        self.assertIsNotNone(context.ready_future)
        self.assertTrue(context.ready_future.done())
        context.close()

    def test_get_variable_keys_returns_list_of_experiments(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_refresh)
        self.assertTrue(context.is_ready())

        res = context.get_variable_keys()

        for key, experiments in res.items():
            self.assertIsInstance(experiments, list)
            self.assertGreater(len(experiments), 0)

        context.close()

    def test_get_variable_keys_multiple_experiments_share_key(self):
        self.set_up()

        import json
        from sdk.json.context_data import ContextData
        from sdk.json.experiment import Experiment
        from sdk.json.experiment_variant import ExperimentVariant

        exp1 = Experiment()
        exp1.id = 1
        exp1.name = "exp_a"
        exp1.unitType = "user_id"
        exp1.iteration = 1
        exp1.fullOnVariant = 0
        exp1.trafficSplit = [0.0, 1.0]
        exp1.trafficSeedHi = 0
        exp1.trafficSeedLo = 0
        exp1.audience = ""
        exp1.audienceStrict = False
        exp1.split = [0.5, 0.5]
        exp1.seedHi = 0
        exp1.seedLo = 0
        exp1.customFieldValues = None

        v1 = ExperimentVariant()
        v1.name = "control"
        v1.config = None
        v2 = ExperimentVariant()
        v2.name = "treatment"
        v2.config = json.dumps({"shared_key": "value_a"})
        exp1.variants = [v1, v2]

        exp2 = Experiment()
        exp2.id = 2
        exp2.name = "exp_b"
        exp2.unitType = "user_id"
        exp2.iteration = 1
        exp2.fullOnVariant = 0
        exp2.trafficSplit = [0.0, 1.0]
        exp2.trafficSeedHi = 0
        exp2.trafficSeedLo = 0
        exp2.audience = ""
        exp2.audienceStrict = False
        exp2.split = [0.5, 0.5]
        exp2.seedHi = 0
        exp2.seedLo = 0
        exp2.customFieldValues = None

        v3 = ExperimentVariant()
        v3.name = "control"
        v3.config = None
        v4 = ExperimentVariant()
        v4.name = "treatment"
        v4.config = json.dumps({"shared_key": "value_b"})
        exp2.variants = [v3, v4]

        data = ContextData()
        data.experiments = [exp1, exp2]
        future = Future()
        future.set_result(data)

        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, future)
        self.assertTrue(context.is_ready())

        res = context.get_variable_keys()

        self.assertIn("shared_key", res)
        self.assertIsInstance(res["shared_key"], list)
        self.assertEqual(2, len(res["shared_key"]))
        self.assertIn("exp_a", res["shared_key"])
        self.assertIn("exp_b", res["shared_key"])

        context.close()

    def test_set_override_allowed_after_close(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertTrue(context.is_ready())

        context.close()
        self.assertTrue(context.is_closed())

        context.set_override("exp_test_ab", 1)
        self.assertEqual(1, context.get_override("exp_test_ab"))

    def test_set_overrides_allowed_after_close(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertTrue(context.is_ready())

        context.close()
        self.assertTrue(context.is_closed())

        context.set_overrides({"exp_test_ab": 2, "exp_test_abc": 1})
        self.assertEqual(2, context.get_override("exp_test_ab"))
        self.assertEqual(1, context.get_override("exp_test_abc"))

    def test_clear_refresh_timer_thread_safe(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        context.refresh_timer = threading.Timer(999, lambda: None)
        context.clear_refresh_timer()
        self.assertIsNone(context.refresh_timer)

        context.clear_refresh_timer()
        self.assertIsNone(context.refresh_timer)
        context.close()

    def test_get_unit_returns_unit(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        self.assertEqual("e791e240fcd3df7d238cfc285f475e8152fcc0ec", context.get_unit("session_id"))
        self.assertEqual("123456789", context.get_unit("user_id"))
        self.assertEqual("bleh@absmartly.com", context.get_unit("email"))
        self.assertIsNone(context.get_unit("nonexistent"))
        context.close()

    def test_get_units_returns_all_units(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        result = context.get_units()
        self.assertEqual(self.units, result)
        context.close()

    def test_get_attribute_returns_last_set_value(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        context.set_attribute("country", "US")
        context.set_attribute("language", "en")
        context.set_attribute("country", "DE")

        self.assertEqual("DE", context.get_attribute("country"))
        self.assertEqual("en", context.get_attribute("language"))
        self.assertIsNone(context.get_attribute("nonexistent"))
        context.close()

    def test_get_attributes_returns_all_attributes(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        context.set_attribute("country", "US")
        context.set_attribute("language", "en")
        context.set_attribute("country", "DE")

        result = context.get_attributes()
        self.assertEqual("DE", result["country"])
        self.assertEqual("en", result["language"])
        context.close()

    def test_ready_error_is_none_on_success(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        self.assertIsNone(context.ready_error)
        self.assertFalse(context.is_failed())
        context.close()

    def test_ready_error_set_on_failed_future(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_failed)

        self.assertTrue(context.is_failed())
        self.assertIsNotNone(context.ready_error)
        context.close()

    def test_ready_error_set_after_async_failure(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)

        self.assertFalse(context.is_ready())
        error = RuntimeError("FAILED")
        self.data_future.set_exception(error)
        context.wait_until_ready()

        self.assertTrue(context.is_failed())
        self.assertIsNotNone(context.ready_error)
        context.close()

    def test_read_methods_return_safe_defaults_when_not_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future)

        self.assertFalse(context.is_ready())

        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))
        self.assertEqual(17, context.get_variable_value("banner.size", 17))
        self.assertEqual(17, context.peek_variable_value("banner.size", 17))
        self.assertEqual({}, context.get_variable_keys())
        self.assertEqual([], context.get_experiments())
        self.assertIsNone(context.get_custom_field_value("exp_test_abc", "country"))
        self.assertIsNone(context.get_custom_field_value_type("exp_test_abc", "country"))
        self.assertEqual([], context.get_custom_field_keys())

        self.data_future.set_result(self.data)

    def test_read_methods_return_safe_defaults_after_finalize(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)

        self.assertTrue(context.is_ready())

        context.get_treatment("exp_test_ab")
        context.close()

        self.assertTrue(context.is_closed())

        self.assertEqual(0, context.get_treatment("exp_test_ab"))
        self.assertEqual(0, context.peek_treatment("exp_test_ab"))
        self.assertEqual(17, context.get_variable_value("banner.size", 17))
        self.assertEqual(17, context.peek_variable_value("banner.size", 17))
        self.assertEqual({}, context.get_variable_keys())
        self.assertEqual([], context.get_experiments())
        self.assertIsNone(context.get_custom_field_value("exp_test_abc", "country"))
        self.assertIsNone(context.get_custom_field_value_type("exp_test_abc", "country"))
        self.assertEqual([], context.get_custom_field_keys())
