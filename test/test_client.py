import time
import unittest
from unittest.mock import MagicMock, Mock

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


class ClientTest(unittest.TestCase):

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
            {})
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
            {})
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
                            "X-Agent": "absmartly-python-sdk"}

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
