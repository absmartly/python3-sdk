import unittest
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from unittest.mock import MagicMock, Mock, patch

from requests import Response
from requests.exceptions import Timeout, HTTPError, ConnectionError

from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.default_context_data_provider import DefaultContextDataProvider
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.json.context_data import ContextData


class TestProviderGetContextData(unittest.TestCase):

    def setUp(self):
        self.client_config = ClientConfig()
        self.client_config.endpoint = "https://sandbox.test.io/v1"
        self.client_config.api_key = "test-api-key"
        self.client_config.application = "website"
        self.client_config.environment = "dev"

        self.http_client = DefaultHTTPClient(DefaultHTTPClientConfig())
        self.client = Client(self.client_config, self.http_client)
        self.provider = DefaultContextDataProvider(self.client)

    def test_provider_get_context_data_success(self):
        response = Response()
        response.status_code = 200
        response._content = bytes('{"experiments": []}', encoding="utf-8")
        self.http_client.get = MagicMock(return_value=response)

        future = self.provider.get_context_data()
        result = future.result(timeout=5)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, ContextData)
        self.http_client.get.assert_called_once()

    def test_provider_get_context_data_timeout(self):
        def raise_timeout(*args, **kwargs):
            raise Timeout("Connection timed out")

        self.http_client.get = MagicMock(side_effect=raise_timeout)

        future = self.provider.get_context_data()

        with self.assertRaises(Timeout):
            future.result(timeout=5)

    def test_provider_get_context_data_http_error(self):
        response = Response()
        response.status_code = 500
        response._content = bytes('{"error": "Internal Server Error"}', encoding="utf-8")
        self.http_client.get = MagicMock(return_value=response)

        future = self.provider.get_context_data()

        with self.assertRaises(HTTPError):
            future.result(timeout=5)

    def test_provider_get_context_data_connection_error(self):
        def raise_connection_error(*args, **kwargs):
            raise ConnectionError("Connection refused")

        self.http_client.get = MagicMock(side_effect=raise_connection_error)

        future = self.provider.get_context_data()

        with self.assertRaises(ConnectionError):
            future.result(timeout=5)

    def test_provider_retry_configuration(self):
        http_client_config = DefaultHTTPClientConfig()
        http_client_config.max_retries = 3
        http_client_config.retry_interval = 0.1
        http_client = DefaultHTTPClient(http_client_config)

        https_adapter = http_client.http_client.get_adapter("https://")
        self.assertIsNotNone(https_adapter)
        self.assertEqual(3, https_adapter.max_retries.total)

        http_adapter = http_client.http_client.get_adapter("http://")
        self.assertIsNotNone(http_adapter)
        self.assertEqual(3, http_adapter.max_retries.total)


if __name__ == '__main__':
    unittest.main()
