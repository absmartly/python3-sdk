import os
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor

from sdk.audience_matcher import AudienceMatcher
from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_event_handler import ContextEventHandler
from sdk.context_event_logger import ContextEventLogger, EventType
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_context_data_deserializer import DefaultContextDataDeserializer
from sdk.default_context_data_provider import DefaultContextDataProvider
from sdk.default_context_event_handler import DefaultContextEventHandler
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.default_variable_parser import DefaultVariableParser
from sdk.json.context_data import ContextData
from sdk.json.publish_event import PublishEvent
from sdk.time.fixed_clock import FixedClock


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


class TestConcurrency(unittest.TestCase):

    units = {
        "session_id": "e791e240fcd3df7d238cfc285f475e8152fcc0ec",
        "user_id": "123456789",
    }

    deser = DefaultContextDataDeserializer()
    audeser = DefaultAudienceDeserializer()

    def set_up(self):
        with open(os.path.join(os.path.dirname(__file__),
                               'res/context.json'),
                  'r') as file:
            content = file.read()
        self.data = self.deser.deserialize(
            bytes(content, encoding="utf-8"),
            0,
            len(content))
        self.data_future_ready = Future()
        self.data_future_ready.set_result(self.data)

        self.clock = FixedClock(1_620_000_000_000)
        client_config = ClientConfig()
        client_config.endpoint = "https://sandbox.test.io/v1"
        client_config.api_key = "test-api-key"
        client_config.application = "www"
        client_config.environment = "test"
        default_client_config = DefaultHTTPClientConfig()
        default_client = DefaultHTTPClient(default_client_config)
        self.client = ClientContextMock(client_config, default_client)
        self.data_provider = DefaultContextDataProvider(self.client)
        self.event_handler = DefaultContextEventHandler(self.client)
        self.variable_parser = DefaultVariableParser()
        self.audience_matcher = AudienceMatcher(self.audeser)
        self.event_logger = None

    def create_test_context(self, config, data_future):
        return Context(self.clock,
                       config, data_future,
                       self.data_provider,
                       self.event_handler,
                       self.event_logger,
                       self.variable_parser,
                       self.audience_matcher)

    def test_concurrent_treatment_calls(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertTrue(context.is_ready())

        results = []
        errors = []
        experiment_name = "exp_test_ab"

        def get_treatment():
            try:
                result = context.get_treatment(experiment_name)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(20):
            t = threading.Thread(target=get_treatment)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(0, len(errors))
        self.assertEqual(20, len(results))
        first_result = results[0]
        for result in results:
            self.assertEqual(first_result, result)

        context.close()

    def test_concurrent_track_calls(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertTrue(context.is_ready())

        errors = []

        def track_goal(goal_name, amount):
            try:
                context.track(goal_name, {"amount": amount})
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            t = threading.Thread(target=track_goal, args=(f"goal_{i}", i * 100))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(0, len(errors))
        self.assertEqual(20, context.get_pending_count())

        context.close()

    def test_concurrent_publish(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertTrue(context.is_ready())

        publish_count = [0]
        lock = threading.Lock()

        def counting_publish(event):
            with lock:
                publish_count[0] += 1
            future = Future()
            time.sleep(0.01)
            future.set_result(None)
            return future

        self.client.publish = counting_publish

        for i in range(5):
            context.track(f"goal_{i}", {"amount": i * 100})

        errors = []

        def call_publish():
            try:
                context.publish()
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(5):
            t = threading.Thread(target=call_publish)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(0, len(errors))

        context.close()

    def test_concurrent_context_operations(self):
        self.set_up()
        config = ContextConfig()
        config.units = self.units
        context = self.create_test_context(config, self.data_future_ready)
        self.assertTrue(context.is_ready())

        errors = []

        def set_attributes():
            try:
                for i in range(5):
                    context.set_attribute(f"attr_{threading.current_thread().name}_{i}", i)
            except Exception as e:
                errors.append(e)

        def get_treatments():
            try:
                for _ in range(5):
                    context.get_treatment("exp_test_ab")
            except Exception as e:
                errors.append(e)

        def track_goals():
            try:
                for i in range(5):
                    context.track(f"goal_{threading.current_thread().name}_{i}", {"value": i})
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=set_attributes, name=f"attr_{i}"))
            threads.append(threading.Thread(target=get_treatments, name=f"treat_{i}"))
            threads.append(threading.Thread(target=track_goals, name=f"goal_{i}"))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(0, len(errors))

        self.assertGreater(len(context.attributes), 0)
        self.assertGreater(context.get_pending_count(), 0)

        context.close()


if __name__ == '__main__':
    unittest.main()
