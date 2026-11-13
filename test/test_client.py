import os
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from requests import Response

from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.default_context_event_serializer import \
    DefaultContextEventSerializer
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.json.context_data import ContextData
from sdk.json.publish_event import PublishEvent

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


class ClientTest(unittest.TestCase):

    def test_configured_application_version_and_agent(self):
        config = ClientConfig()
        config.endpoint = "https://localhost/v1"
        config.api_key = "test-api-key"
        config.application = "website"
        config.environment = "dev"
        config.application_version = "2.4.1"
        client = Client(config, Mock())

        self.assertEqual("website", client.get_application())
        self.assertEqual("2.4.1", client.get_application_version())
        self.assertEqual("dev", client.get_environment())
        self.assertEqual("absmartly-python-sdk", client.get_agent_name())
        self.assertEqual("0.3.0", client.get_agent_version())
        self.assertEqual("absmartly-python-sdk/0.3.0", client.get_agent())
        self.assertEqual("2.4.1", client.headers["X-Application-Version"])
        self.assertEqual("absmartly-python-sdk/0.3.0", client.headers["X-Agent"])

    @unittest.skipIf(tomllib is None, "tomllib requires Python 3.11")
    def test_agent_follows_package_version(self):
        # The release builds the package with the version pyproject.toml
        # reads from sdk.version, and X-Agent is derived from the same value.
        path = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(path, "rb") as f:
            pyproject = tomllib.load(f)
        self.assertIn("version", pyproject["project"]["dynamic"])
        self.assertEqual(
            "sdk.version.VERSION",
            pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"])

        config = ClientConfig()
        config.endpoint = "https://localhost/v1"
        config.application = "website"
        config.environment = "dev"
        with patch("sdk.client.AGENT", "absmartly-python-sdk/9.8.7"), \
                patch("sdk.client.VERSION", "9.8.7"):
            client = Client(config, Mock())
            self.assertEqual("9.8.7", client.get_agent_version())
            self.assertEqual("absmartly-python-sdk/9.8.7", client.get_agent())
        self.assertEqual("absmartly-python-sdk/9.8.7",
                         client.headers["X-Agent"])

    def test_create_with_defaults(self):
        config = ClientConfig()
        config.endpoint = "https://localhost/v1"
        config.api_key = "test-api-key"
        config.application = "website"
        config.environment = "dev"

        expected = ContextData()
        event = PublishEvent()
        publish_bytes = bytes(0)

        expected_query = {"application": "website", "environment": "dev"}

        deserializer = DefaultContextDataDeserializer()
        deserializer.deserialize = MagicMock(return_value=expected)

        serializer = DefaultContextEventSerializer()
        serializer.serialize = MagicMock(return_value=publish_bytes)
        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())
        http_client.get = MagicMock(return_value="test")
        http_client.put = Mock(return_value="test")

        client = Client(config, http_client)
        client.get_context_data()

        http_client.get.assert_called_once_with(
            "https://localhost/v1/context",
            expected_query,
            {"X-API-Key": "test-api-key",
             "X-Application": "website",
             "X-Environment": "dev",
             "X-Application-Version": '0',
             "X-Agent": "absmartly-python-sdk/0.3.0"})
        http_client.get.reset_mock()
        client.publish(event)
        time.sleep(0.1)
        http_client.put.assert_called()

    def test_get_context_data(self):
        config = ClientConfig()
        config.endpoint = "https://localhost/v1"
        config.api_key = "test-api-key"
        config.application = "website"
        config.environment = "dev"

        expected = ContextData()
        publish_bytes = bytes(0)
        expected_query = {"application": "website", "environment": "dev"}

        deserializer = DefaultContextDataDeserializer()
        deserializer.deserialize = MagicMock(return_value=expected)

        serializer = DefaultContextEventSerializer()
        serializer.serialize = MagicMock(return_value=publish_bytes)
        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())

        response = Response()
        response.status_code = 200
        response._content = bytes("{}", encoding="utf-8")
        http_client.get = MagicMock(return_value=response)
        http_client.put = Mock(return_value="test")

        client = Client(config, http_client)
        future = client.get_context_data()

        http_client.get.assert_called_once_with(
            "https://localhost/v1/context",
            expected_query,
            {"X-API-Key": "test-api-key",
             "X-Application": "website",
             "X-Environment": "dev",
             "X-Application-Version": '0',
             "X-Agent": "absmartly-python-sdk/0.3.0"})
        http_client.get.reset_mock()

        result = future.result()
        self.assertEqual(type(expected), type(result))

    def test_publish(self):
        config = ClientConfig()
        config.endpoint = "https://localhost/v1"
        config.api_key = "test-api-key"
        config.application = "website"
        config.environment = "dev"

        expected = ContextData()

        event = PublishEvent()
        publish_bytes = bytes(0)

        expected_headers = {"X-API-Key": "test-api-key",
                            "X-Application": "website",
                            "X-Environment": "dev",
                            "X-Application-Version": '0',
                            "X-Agent": "absmartly-python-sdk/0.3.0"}

        deserializer = DefaultContextDataDeserializer()
        deserializer.deserialize = MagicMock(return_value=expected)

        serializer = DefaultContextEventSerializer()
        serializer.serialize = MagicMock(return_value=publish_bytes)
        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())

        response = Response()
        response.status_code = 200
        response._content = bytes("{}", encoding="utf-8")
        http_client.put = Mock(return_value=response)

        client = Client(config, http_client)
        client.serializer = serializer
        client.publish(event)

        http_client.put.assert_called_once_with("https://localhost/v1/context",
                                                {},
                                                expected_headers,
                                                publish_bytes)
        http_client.put.reset_mock()
        serializer.serialize.assert_called_once()
