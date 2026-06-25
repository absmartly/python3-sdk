import unittest
from concurrent.futures import Future
from unittest.mock import MagicMock, Mock

from requests import Response
from requests.exceptions import Timeout, HTTPError, ConnectionError

from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.default_context_event_handler import DefaultContextEventHandler
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.json.attribute import Attribute
from sdk.json.exposure import Exposure
from sdk.json.goal_achievement import GoalAchievement
from sdk.json.publish_event import PublishEvent
from sdk.json.unit import Unit


class TestPublisher(unittest.TestCase):

    def setUp(self):
        self.client_config = ClientConfig()
        self.client_config.endpoint = "https://sandbox.test.io/v1"
        self.client_config.api_key = "test-api-key"
        self.client_config.application = "website"
        self.client_config.environment = "dev"

        self.http_client = DefaultHTTPClient(DefaultHTTPClientConfig())
        self.client = Client(self.client_config, self.http_client)
        self.publisher = DefaultContextEventHandler(self.client)

    def create_publish_event(self, with_exposures=True, with_goals=True):
        event = PublishEvent()
        event.hashed = True
        event.publishedAt = 1620000000000

        unit = Unit()
        unit.type = "user_id"
        unit.uid = "test-user-123"
        event.units = [unit]

        if with_exposures:
            exposure = Exposure()
            exposure.id = 1
            exposure.name = "exp_test"
            exposure.unit = "user_id"
            exposure.variant = 1
            exposure.exposedAt = 1620000000000
            exposure.assigned = True
            exposure.eligible = True
            event.exposures = [exposure]
        else:
            event.exposures = []

        if with_goals:
            goal = GoalAchievement()
            goal.name = "goal_test"
            goal.achievedAt = 1620000000000
            goal.properties = {"amount": 100}
            event.goals = [goal]
        else:
            event.goals = []

        event.attributes = []

        return event

    def test_publisher_publish_success(self):
        response = Response()
        response.status_code = 200
        response._content = bytes('{}', encoding="utf-8")
        self.http_client.put = MagicMock(return_value=response)

        event = self.create_publish_event()
        mock_context = Mock()

        future = self.publisher.publish(mock_context, event)
        result = future.result(timeout=5)

        self.http_client.put.assert_called_once()
        call_args = self.http_client.put.call_args
        self.assertIn("https://sandbox.test.io/v1/context", call_args[0])

    def test_publisher_publish_timeout(self):
        def raise_timeout(*args, **kwargs):
            raise Timeout("Connection timed out")

        self.http_client.put = MagicMock(side_effect=raise_timeout)

        event = self.create_publish_event()
        mock_context = Mock()

        future = self.publisher.publish(mock_context, event)

        with self.assertRaises(Timeout):
            future.result(timeout=5)

    def test_publisher_publish_http_error(self):
        response = Response()
        response.status_code = 500
        response._content = bytes('{"error": "Internal Server Error"}', encoding="utf-8")
        self.http_client.put = MagicMock(return_value=response)

        event = self.create_publish_event()
        mock_context = Mock()

        future = self.publisher.publish(mock_context, event)

        with self.assertRaises(HTTPError):
            future.result(timeout=5)

    def test_publisher_batch_events(self):
        response = Response()
        response.status_code = 200
        response._content = bytes('{}', encoding="utf-8")
        self.http_client.put = MagicMock(return_value=response)

        event = PublishEvent()
        event.hashed = True
        event.publishedAt = 1620000000000

        unit = Unit()
        unit.type = "user_id"
        unit.uid = "test-user-123"
        event.units = [unit]

        exposures = []
        for i in range(5):
            exposure = Exposure()
            exposure.id = i
            exposure.name = f"exp_test_{i}"
            exposure.unit = "user_id"
            exposure.variant = 1
            exposure.exposedAt = 1620000000000 + i
            exposure.assigned = True
            exposure.eligible = True
            exposures.append(exposure)
        event.exposures = exposures

        goals = []
        for i in range(3):
            goal = GoalAchievement()
            goal.name = f"goal_test_{i}"
            goal.achievedAt = 1620000000000 + i
            goal.properties = {"amount": 100 * i}
            goals.append(goal)
        event.goals = goals

        event.attributes = []

        mock_context = Mock()

        future = self.publisher.publish(mock_context, event)
        result = future.result(timeout=5)

        self.http_client.put.assert_called_once()
        call_args = self.http_client.put.call_args
        self.assertIn("https://sandbox.test.io/v1/context", call_args[0])


if __name__ == '__main__':
    unittest.main()
