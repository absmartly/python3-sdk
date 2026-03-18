import copy
import json
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
from sdk.default_context_data_deserializer import DefaultContextDataDeserializer
from sdk.json.attribute import Attribute
from sdk.json.context_data import ContextData
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.publish_event import PublishEvent
from sdk.json.unit import Unit
from sdk.time.clock import Clock
from sdk.time.fixed_clock import FixedClock


class EventLoggerCapture(ContextEventLogger):
    def __init__(self):
        self.events = []

    def handle_event(self, event_type: EventType, data: object):
        self.events.append((event_type, data))

    @property
    def last_type(self):
        return self.events[-1][0] if self.events else None

    @property
    def last_data(self):
        return self.events[-1][1] if self.events else None

    def clear(self):
        self.events.clear()

    def count_type(self, event_type):
        return sum(1 for e in self.events if e[0] == event_type)


class ClientContextMock(Client):
    def __init__(self, config, http_client):
        super().__init__(config, http_client)
        self._publish_future = None
        self._refresh_data = None
        self._publish_calls = []

    def get_context_data(self):
        future = Future()
        if self._refresh_data is not None:
            future.set_result(self._refresh_data)
        else:
            context_data = ContextData()
            context_data.experiments = []
            future.set_result(context_data)
        return future

    def publish(self, event: PublishEvent):
        self._publish_calls.append(event)
        if self._publish_future is not None:
            return self._publish_future
        future = Future()
        future.set_result(None)
        return future


class ContextCanonicalTestBase(unittest.TestCase):

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

    units = {
        "session_id": "e791e240fcd3df7d238cfc285f475e8152fcc0ec",
        "user_id": "123456789",
        "email": "bleh@absmartly.com"
    }

    deser = DefaultContextDataDeserializer()
    audeser = DefaultAudienceDeserializer()

    def set_up(self):
        with open(os.path.join(os.path.dirname(__file__), 'res/context.json'), 'r') as file:
            content = file.read()
        with open(os.path.join(os.path.dirname(__file__), 'res/context-strict.json'), 'r') as file:
            content_strict = file.read()
        with open(os.path.join(os.path.dirname(__file__), 'res/refreshed.json'), 'r') as file:
            refreshed = file.read()

        self.data = self.deser.deserialize(bytes(content, encoding="utf-8"), 0, len(content))
        self.audience_strict_data = self.deser.deserialize(
            bytes(content_strict, encoding="utf-8"), 0, len(content_strict))
        self.refresh_data = self.deser.deserialize(
            bytes(refreshed, encoding="utf-8"), 0, len(refreshed))

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
        self.event_logger = EventLoggerCapture()
        self.variable_parser = DefaultVariableParser()
        self.audience_matcher = AudienceMatcher(self.audeser)

    def create_context(self, config, data_future):
        return Context(
            self.clock, config, data_future,
            self.data_provider, self.event_handler,
            self.event_logger, self.variable_parser,
            self.audience_matcher)

    def create_ready_context(self, **kwargs):
        config = ContextConfig()
        config.units = kwargs.get('units', self.units)
        if 'overrides' in kwargs:
            config.overrides = kwargs['overrides']
        if 'custom_assignments' in kwargs:
            config.custom_assignments = kwargs['custom_assignments']
        if 'cassignments' in kwargs:
            config.cassigmnents = kwargs['cassignments']
        data_future = kwargs.get('data_future', self.data_future_ready)
        return self.create_context(config, data_future)


class ContextEventLoggerTests(ContextCanonicalTestBase):

    def test_event_logger_on_ready_success(self):
        self.set_up()
        context = self.create_ready_context()
        self.assertTrue(context.is_ready())
        self.assertEqual(self.event_logger.last_type, EventType.READY)
        self.assertIsInstance(self.event_logger.last_data, ContextData)
        context.close()

    def test_event_logger_on_ready_failure(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future_failed)
        self.assertTrue(context.is_ready())
        self.assertTrue(context.is_failed())
        self.assertEqual(self.event_logger.last_type, EventType.ERROR)
        self.assertIsInstance(self.event_logger.last_data, RuntimeError)
        context.close()

    def test_event_logger_on_exposure(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_treatment("exp_test_ab")
        self.assertEqual(self.event_logger.last_type, EventType.EXPOSURE)
        self.assertIsInstance(self.event_logger.last_data, Exposure)
        context.close()

    def test_event_logger_on_goal(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        self.assertEqual(self.event_logger.last_type, EventType.GOAL)
        self.assertIsInstance(self.event_logger.last_data, GoalAchievement)
        context.close()

    def test_event_logger_on_publish_success(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        context.publish()
        self.assertEqual(self.event_logger.last_type, EventType.PUBLISH)
        context.close()

    def test_event_logger_on_publish_error(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        fail_future = Future()
        fail_future.set_exception(RuntimeError("publish error"))
        self.client._publish_future = fail_future
        try:
            context.publish()
        except RuntimeError:
            pass
        self.assertEqual(self.event_logger.last_type, EventType.ERROR)
        self.client._publish_future = None
        context.close()

    def test_event_logger_on_refresh_success(self):
        self.set_up()
        context = self.create_ready_context()
        self.client._refresh_data = self.data
        context.refresh()
        has_refresh = any(e[0] == EventType.REFRESH for e in self.event_logger.events)
        self.assertTrue(has_refresh)
        context.close()

    def test_event_logger_on_refresh_error(self):
        self.set_up()
        context = self.create_ready_context()

        def failing_get():
            future = Future()
            future.set_exception(RuntimeError("refresh error"))
            return future
        self.client.get_context_data = failing_get

        try:
            context.refresh()
        except RuntimeError:
            pass
        self.assertEqual(self.event_logger.last_type, EventType.ERROR)
        context.close()

    def test_event_logger_on_close(self):
        self.set_up()
        context = self.create_ready_context()
        context.close()
        self.assertEqual(self.event_logger.last_type, EventType.CLOSE)


class ContextTreatmentTests(ContextCanonicalTestBase):

    def test_treatment_queues_exposure(self):
        self.set_up()
        context = self.create_ready_context()
        for experiment in self.data.experiments:
            result = context.get_treatment(experiment.name)
            self.assertEqual(self.expectedVariants[experiment.name], result)
        self.assertGreater(context.get_pending_count(), 0)
        context.close()

    def test_treatment_queues_exposure_only_once(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_treatment("exp_test_ab")
        count_after_first = context.get_pending_count()
        context.get_treatment("exp_test_ab")
        self.assertEqual(count_after_first, context.get_pending_count())
        context.close()

    def test_treatment_queues_exposure_after_peek(self):
        self.set_up()
        context = self.create_ready_context()
        context.peek_treatment("exp_test_ab")
        self.assertEqual(0, context.get_pending_count())
        context.get_treatment("exp_test_ab")
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_treatment_returns_base_variant_for_unknown_experiment(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.get_treatment("unknown_experiment")
        self.assertEqual(0, result)
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_treatment_does_not_requeue_unknown_experiment(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_treatment("unknown_experiment")
        self.assertEqual(1, context.get_pending_count())
        context.get_treatment("unknown_experiment")
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_treatment_queues_exposure_with_audience_match_true(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_strict)
        context.set_attribute("age", 25)
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(1, result)
        self.assertEqual(1, context.get_pending_count())
        exposure = context.exposures[0]
        self.assertFalse(exposure.audienceMismatch)
        context.close()

    def test_treatment_queues_exposure_with_audience_mismatch_false_nonstrict(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_strict)
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(0, result)
        self.assertEqual(1, context.get_pending_count())
        exposure = context.exposures[0]
        self.assertTrue(exposure.audienceMismatch)
        context.close()

    def test_treatment_queues_exposure_with_override_variant(self):
        self.set_up()
        context = self.create_ready_context(overrides={"exp_test_ab": 2})
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(2, result)
        self.assertEqual(1, context.get_pending_count())
        exposure = context.exposures[0]
        self.assertTrue(exposure.overridden)
        context.close()

    def test_treatment_queues_exposure_with_custom_assignment(self):
        self.set_up()
        context = self.create_ready_context(cassignments={"exp_test_ab": 2})
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(2, result)
        self.assertEqual(1, context.get_pending_count())
        exposure = context.exposures[0]
        self.assertTrue(exposure.custom)
        context.close()


class ContextPeekTests(ContextCanonicalTestBase):

    def test_peek_does_not_queue_exposures(self):
        self.set_up()
        context = self.create_ready_context()
        for experiment in self.data.experiments:
            context.peek_treatment(experiment.name)
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_peek_returns_override_variant(self):
        self.set_up()
        context = self.create_ready_context(overrides={"exp_test_ab": 2})
        result = context.peek_treatment("exp_test_ab")
        self.assertEqual(2, result)
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_peek_returns_assigned_variant_on_audience_mismatch_nonstrict(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.peek_treatment("exp_test_ab")
        self.assertEqual(self.expectedVariants["exp_test_ab"], result)
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_peek_returns_control_variant_on_audience_mismatch_strict(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_strict)
        result = context.peek_treatment("exp_test_ab")
        self.assertEqual(0, result)
        self.assertEqual(0, context.get_pending_count())
        context.close()


class ContextVariableValueTests(ContextCanonicalTestBase):

    def test_variable_value_returns_default_when_unassigned(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.get_variable_value("nonexistent_var", "default")
        self.assertEqual("default", result)
        context.close()

    def test_variable_value_returns_override_values(self):
        self.set_up()
        context = self.create_ready_context(overrides={"exp_test_ab": 1})
        result = context.get_variable_value("banner.size", "default")
        self.assertEqual("large", result)
        context.close()

    def test_variable_value_queues_exposure(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_variable_value("banner.size", "default")
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_variable_value_queues_exposure_only_once(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_variable_value("banner.size", "default")
        count = context.get_pending_count()
        context.get_variable_value("banner.size", "default")
        self.assertEqual(count, context.get_pending_count())
        context.close()

    def test_variable_value_queues_exposure_after_peek(self):
        self.set_up()
        context = self.create_ready_context()
        context.peek_variable_value("banner.size", "default")
        self.assertEqual(0, context.get_pending_count())
        context.get_variable_value("banner.size", "default")
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_variable_value_strict_returns_default_on_mismatch(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_strict)
        result = context.get_variable_value("banner.size", "small")
        self.assertEqual("small", result)
        context.close()

    def test_variable_value_returns_correct_types(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_refresh)
        self.assertEqual(1.0, context.get_variable_value("banner.border", 0))
        self.assertEqual("large", context.get_variable_value("banner.size", ""))
        self.assertEqual("red", context.get_variable_value("button.color", ""))
        self.assertEqual(True, context.get_variable_value("show-modal", False))
        context.close()


class ContextPeekVariableValueTests(ContextCanonicalTestBase):

    def test_peek_variable_value_returns_default_when_unassigned(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.peek_variable_value("nonexistent_var", "default")
        self.assertEqual("default", result)
        context.close()

    def test_peek_variable_value_returns_override_values(self):
        self.set_up()
        context = self.create_ready_context(overrides={"exp_test_ab": 1})
        result = context.peek_variable_value("banner.size", "default")
        self.assertEqual("large", result)
        context.close()

    def test_peek_variable_value_does_not_queue_exposure(self):
        self.set_up()
        context = self.create_ready_context()
        context.peek_variable_value("banner.size", "default")
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_peek_variable_value_strict_returns_default_on_mismatch(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_strict)
        result = context.peek_variable_value("banner.size", "small")
        self.assertEqual("small", result)
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_peek_variable_value_nonstrict_returns_assigned_on_mismatch(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.peek_variable_value("banner.size", "small")
        self.assertEqual("large", result)
        context.close()


class ContextVariableKeysTests(ContextCanonicalTestBase):

    def test_variable_keys_returns_all_active_keys(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_refresh)
        keys = context.get_variable_keys()
        expected = {
            "banner.border": ["exp_test_ab"],
            "banner.size": ["exp_test_ab"],
            "button.color": ["exp_test_abc"],
            "card.width": ["exp_test_not_eligible"],
            "submit.color": ["exp_test_fullon"],
            "submit.shape": ["exp_test_fullon"],
            "show-modal": ["exp_test_new"],
        }
        self.assertEqual(expected, keys)
        context.close()


class ContextTrackTests(ContextCanonicalTestBase):

    def test_track_queues_goals(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 125, "hours": 245})
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_track_calls_event_logger(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        goal_events = [e for e in self.event_logger.events if e[0] == EventType.GOAL]
        self.assertEqual(1, len(goal_events))
        self.assertIsInstance(goal_events[0][1], GoalAchievement)
        context.close()

    def test_track_accepts_number_properties(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 125, "hours": 245})
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_track_accepts_none_properties(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", None)
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_track_callable_before_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        context.track("goal1", {"amount": 100})
        self.assertEqual(1, context.get_pending_count())
        context.close()

    def test_track_throws_after_close(self):
        self.set_up()
        context = self.create_ready_context()
        context.close()
        with self.assertRaises(RuntimeError):
            context.track("goal1", {"amount": 100})

    def test_track_with_timestamp(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100}, achieved_at=1713218400000)
        achievement = context.achievements[0]
        self.assertEqual(1713218400000, achievement.achievedAt)
        context.close()


class ContextPublishTests(ContextCanonicalTestBase):

    def test_publish_does_not_call_client_when_empty(self):
        self.set_up()
        context = self.create_ready_context()
        context.publish()
        self.assertEqual(0, len(self.client._publish_calls))
        context.close()

    def test_publish_calls_client(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        context.publish()
        self.assertEqual(1, len(self.client._publish_calls))
        context.close()

    def test_publish_includes_exposure_data(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_treatment("exp_test_ab")
        context.publish()
        self.assertEqual(1, len(self.client._publish_calls))
        event = self.client._publish_calls[0]
        self.assertIsNotNone(event.exposures)
        self.assertEqual(1, len(event.exposures))
        self.assertEqual("exp_test_ab", event.exposures[0].name)
        context.close()

    def test_publish_includes_goal_data(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        context.publish()
        event = self.client._publish_calls[0]
        self.assertIsNotNone(event.goals)
        self.assertEqual(1, len(event.goals))
        self.assertEqual("goal1", event.goals[0].name)
        context.close()

    def test_publish_includes_attribute_data(self):
        self.set_up()
        context = self.create_ready_context()
        context.set_attribute("attr1", "value1")
        context.track("goal1", {"amount": 100})
        context.publish()
        event = self.client._publish_calls[0]
        self.assertIsNotNone(event.attributes)
        self.assertEqual(1, len(event.attributes))
        self.assertEqual("attr1", event.attributes[0].name)
        context.close()

    def test_publish_clears_queue_on_success(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        self.assertEqual(1, context.get_pending_count())
        context.publish()
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_publish_propagates_client_error(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        fail_future = Future()
        fail_future.set_exception(RuntimeError("publish failed"))
        self.client._publish_future = fail_future
        with self.assertRaises(RuntimeError):
            context.publish()
        self.client._publish_future = None
        context.close()

    def test_publish_throws_after_close(self):
        self.set_up()
        context = self.create_ready_context()
        context.close()
        with self.assertRaises(RuntimeError):
            context.publish()


class ContextFinalizeTests(ContextCanonicalTestBase):

    def test_finalize_does_not_publish_when_empty(self):
        self.set_up()
        context = self.create_ready_context()
        context.close()
        self.assertEqual(0, len(self.client._publish_calls))
        self.assertTrue(context.is_closed())

    def test_finalize_publishes_pending_events(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        context.close()
        self.assertEqual(1, len(self.client._publish_calls))
        self.assertTrue(context.is_closed())

    def test_finalize_includes_exposure_data(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_treatment("exp_test_ab")
        context.close()
        self.assertEqual(1, len(self.client._publish_calls))
        event = self.client._publish_calls[0]
        self.assertIsNotNone(event.exposures)
        self.assertEqual(1, len(event.exposures))

    def test_finalize_includes_goal_data(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        context.close()
        event = self.client._publish_calls[0]
        self.assertIsNotNone(event.goals)
        self.assertEqual(1, len(event.goals))

    def test_finalize_includes_attribute_data(self):
        self.set_up()
        context = self.create_ready_context()
        context.set_attribute("attr1", "value1")
        context.track("goal1", {"amount": 100})
        context.close()
        event = self.client._publish_calls[0]
        self.assertIsNotNone(event.attributes)
        self.assertEqual(1, len(event.attributes))

    def test_finalize_clears_queue(self):
        self.set_up()
        context = self.create_ready_context()
        context.track("goal1", {"amount": 100})
        context.close()
        self.assertEqual(0, context.get_pending_count())

    def test_finalize_stops_refresh_timer(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_refresh)
        self.assertIsNotNone(context.refresh_timer)
        context.close()
        self.assertIsNone(context.refresh_timer)


class ContextRefreshTests(ContextCanonicalTestBase):

    def test_refresh_loads_new_data(self):
        self.set_up()
        context = self.create_ready_context()
        self.client._refresh_data = self.refresh_data
        context.refresh()
        experiments = context.get_experiments()
        self.assertIn("exp_test_new", experiments)
        context.close()

    def test_refresh_throws_after_close(self):
        self.set_up()
        context = self.create_ready_context()
        context.close()
        with self.assertRaises(RuntimeError):
            context.refresh()

    def test_refresh_keeps_overrides(self):
        self.set_up()
        context = self.create_ready_context(overrides={"exp_test_ab": 2})
        self.client._refresh_data = self.refresh_data
        context.refresh()
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(2, result)
        context.close()

    def test_refresh_keeps_custom_assignments(self):
        self.set_up()
        context = self.create_ready_context(cassignments={"exp_test_ab": 2})
        self.client._refresh_data = self.refresh_data
        context.refresh()
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(2, result)
        context.close()

    def test_refresh_not_requeue_when_not_changed(self):
        self.set_up()
        context = self.create_ready_context()
        context.get_treatment("exp_test_ab")
        initial_count = context.get_pending_count()
        self.client._refresh_data = self.data
        context.refresh()
        context.get_treatment("exp_test_ab")
        self.assertEqual(initial_count, context.get_pending_count())
        context.close()

    def test_refresh_not_requeue_with_override(self):
        self.set_up()
        context = self.create_ready_context(overrides={"exp_test_ab": 2})
        context.get_treatment("exp_test_ab")
        initial_count = context.get_pending_count()
        self.client._refresh_data = self.data
        context.refresh()
        context.get_treatment("exp_test_ab")
        self.assertEqual(initial_count, context.get_pending_count())
        context.close()

    def test_refresh_picks_up_experiment_started(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.get_treatment("exp_test_new")
        self.assertEqual(0, result)
        self.client._refresh_data = self.refresh_data
        context.refresh()
        result = context.get_treatment("exp_test_new")
        self.assertEqual(1, result)
        context.close()

    def test_refresh_picks_up_experiment_stopped(self):
        self.set_up()
        context = self.create_ready_context(data_future=self.data_future_refresh)
        result = context.get_treatment("exp_test_new")
        self.assertEqual(1, result)
        self.client._refresh_data = self.data
        context.refresh()
        result = context.get_treatment("exp_test_new")
        self.assertEqual(0, result)
        context.close()


class ContextUnitTests(ContextCanonicalTestBase):

    def test_set_unit_before_ready(self):
        self.set_up()
        config = ContextConfig()
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        context.set_unit("session_id", "some-session")
        self.assertIn("session_id", context.units)
        context.close()

    def test_set_unit_throws_after_close(self):
        self.set_up()
        context = self.create_ready_context()
        context.close()
        with self.assertRaises(RuntimeError):
            context.set_unit("device_id", "device-123")


class ContextAttributeTests(ContextCanonicalTestBase):

    def test_set_attribute_before_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        context.set_attribute("user_age", 25)
        self.assertEqual(1, len(context.attributes))
        context.close()

    def test_get_attribute_returns_last_set_value(self):
        self.set_up()
        context = self.create_ready_context()
        context.set_attribute("user_age", 25)
        context.set_attribute("user_age", 30)
        age_attrs = [a for a in context.attributes if a.name == "user_age"]
        self.assertEqual(2, len(age_attrs))
        self.assertEqual(30, age_attrs[-1].value)
        context.close()


class ContextOverrideTests(ContextCanonicalTestBase):

    def test_override_callable_before_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        context.set_override("exp_test_ab", 2)
        self.assertEqual(2, context.get_override("exp_test_ab"))
        context.close()


class ContextCustomAssignmentTests(ContextCanonicalTestBase):

    def test_custom_assignment_overrides_natural(self):
        self.set_up()
        context = self.create_ready_context()
        context.set_custom_assignment("exp_test_ab", 2)
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(2, result)
        exposure = context.exposures[0]
        self.assertTrue(exposure.custom)
        context.close()

    def test_custom_assignment_does_not_override_fullon(self):
        self.set_up()
        context = self.create_ready_context()
        context.set_custom_assignment("exp_test_fullon", 3)
        result = context.get_treatment("exp_test_fullon")
        self.assertEqual(2, result)
        context.close()

    def test_custom_assignment_does_not_override_not_eligible(self):
        self.set_up()
        context = self.create_ready_context()
        context.set_custom_assignment("exp_test_not_eligible", 3)
        result = context.get_treatment("exp_test_not_eligible")
        self.assertEqual(0, result)
        context.close()

    def test_custom_assignment_callable_before_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        context.set_custom_assignment("exp_test_ab", 2)
        self.assertEqual(2, context.get_custom_assignment("exp_test_ab"))
        context.close()

    def test_custom_assignment_throws_after_close(self):
        self.set_up()
        context = self.create_ready_context()
        context.close()
        with self.assertRaises(RuntimeError):
            context.set_custom_assignment("exp_test_ab", 2)


class ContextCustomFieldTests(ContextCanonicalTestBase):

    def test_custom_field_keys(self):
        self.set_up()
        context = self.create_ready_context()
        keys = context.get_custom_field_keys()
        self.assertEqual(["country", "languages", "overrides"], keys)
        context.close()

    def test_custom_field_value_string(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.get_custom_field_value("exp_test_ab", "country")
        self.assertEqual("US,PT,ES,DE,FR", result)
        context.close()

    def test_custom_field_value_json(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.get_custom_field_value("exp_test_ab", "overrides")
        self.assertEqual({'123': 1, '456': 0}, result)
        context.close()

    def test_custom_field_value_type(self):
        self.set_up()
        context = self.create_ready_context()
        result = context.get_custom_field_type("exp_test_ab", "overrides")
        self.assertEqual("json", result)
        context.close()

    def test_custom_field_value_returns_none_nonexistent(self):
        self.set_up()
        context = self.create_ready_context()
        self.assertIsNone(context.get_custom_field_value("not_found", "not_found"))
        self.assertIsNone(context.get_custom_field_value("exp_test_ab", "not_found"))
        context.close()

    def test_custom_field_value_returns_none_no_custom_fields(self):
        self.set_up()
        context = self.create_ready_context()
        self.assertIsNone(context.get_custom_field_value("exp_test_no_custom_fields", "country"))
        context.close()


class ContextNotReadyTests(ContextCanonicalTestBase):

    def test_throws_when_not_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        result = context.get_treatment("exp_test_ab")
        self.assertEqual(0, result)
        context.close()

    def test_peek_throws_when_not_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        result = context.peek_treatment("exp_test_ab")
        self.assertEqual(0, result)
        context.close()

    def test_variable_value_throws_when_not_ready(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_context(config, self.data_future)
        self.assertFalse(context.is_ready())
        result = context.get_variable_value("banner.size", "default")
        self.assertEqual("default", result)
        context.close()


class ContextPublishResetTests(ContextCanonicalTestBase):

    def test_publish_resets_queues_keeps_attributes_overrides_assignments(self):
        self.set_up()
        context = self.create_ready_context()
        context.set_override("exp_override", 2)
        context.set_custom_assignment("exp_test_ab", 2)
        context.set_attribute("attr1", "value1")
        context.get_treatment("exp_test_ab")
        context.track("goal1", {"amount": 100})
        self.assertGreater(context.get_pending_count(), 0)
        context.publish()
        self.assertEqual(0, context.get_pending_count())
        self.assertEqual(2, context.get_override("exp_override"))
        self.assertEqual(2, context.get_custom_assignment("exp_test_ab"))
        self.assertTrue(len(context.attributes) > 0)
        context.close()


class ContextPublishDelayTests(ContextCanonicalTestBase):

    def test_publish_delay_triggers_after_exposure(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        config.publish_delay = 0.1
        context = self.create_context(config, self.data_future_ready)
        context.get_treatment("exp_test_ab")
        self.assertEqual(1, context.get_pending_count())
        self.assertIsNotNone(context.timeout)
        time.sleep(0.3)
        self.assertEqual(0, context.get_pending_count())
        context.close()

    def test_publish_delay_triggers_after_goal(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        config.publish_delay = 0.1
        context = self.create_context(config, self.data_future_ready)
        context.track("goal1", {"amount": 100})
        self.assertEqual(1, context.get_pending_count())
        self.assertIsNotNone(context.timeout)
        time.sleep(0.3)
        self.assertEqual(0, context.get_pending_count())
        context.close()
