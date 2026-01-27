import unittest
from concurrent.futures import Future
from unittest.mock import MagicMock, Mock, patch

from sdk.absmartly import ABSmartly
from sdk.absmartly_config import ABSmartlyConfig
from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_event_handler import ContextEventHandler
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.json.context_data import ContextData
from sdk.json.experiment import Experiment


class TestSDKInitialization(unittest.TestCase):

    def test_sdk_create_with_valid_config(self):
        client_config = ClientConfig()
        client_config.endpoint = "https://sandbox.test.io/v1"
        client_config.api_key = "test-api-key"
        client_config.application = "website"
        client_config.environment = "dev"

        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())
        client = Client(client_config, http_client)

        config = ABSmartlyConfig()
        config.client = client

        sdk = ABSmartly(config)

        self.assertIsNotNone(sdk)
        self.assertIsNotNone(sdk.context_data_provider)
        self.assertIsNotNone(sdk.context_event_handler)
        self.assertIsNotNone(sdk.variable_parser)
        self.assertIsNotNone(sdk.audience_deserializer)

    def test_sdk_create_missing_endpoint(self):
        client_config = ClientConfig()
        client_config.api_key = "test-api-key"
        client_config.application = "website"
        client_config.environment = "dev"

        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())

        self.assertIsNone(client_config.endpoint)

        with self.assertRaises(TypeError):
            Client(client_config, http_client)

    def test_sdk_create_missing_api_key(self):
        client_config = ClientConfig()
        client_config.endpoint = "https://sandbox.test.io/v1"
        client_config.application = "website"
        client_config.environment = "dev"

        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())
        client = Client(client_config, http_client)

        self.assertIsNone(client_config.api_key)

    def test_sdk_create_context(self):
        mock_data_provider = Mock(spec=ContextDataProvider)
        future_data = Future()
        context_data = ContextData()
        context_data.experiments = []
        future_data.set_result(context_data)
        mock_data_provider.get_context_data.return_value = future_data

        mock_event_handler = Mock(spec=ContextEventHandler)

        config = ABSmartlyConfig()
        config.context_data_provider = mock_data_provider
        config.context_event_handler = mock_event_handler

        sdk = ABSmartly(config)

        context_config = ContextConfig()
        context_config.units = {"user_id": "123456789"}

        context = sdk.create_context(context_config)

        self.assertIsNotNone(context)
        self.assertIsInstance(context, Context)
        mock_data_provider.get_context_data.assert_called_once()

    def test_sdk_create_context_with_data(self):
        mock_data_provider = Mock(spec=ContextDataProvider)
        mock_event_handler = Mock(spec=ContextEventHandler)

        config = ABSmartlyConfig()
        config.context_data_provider = mock_data_provider
        config.context_event_handler = mock_event_handler

        sdk = ABSmartly(config)

        context_config = ContextConfig()
        context_config.units = {"user_id": "123456789"}

        pre_fetched_data = ContextData()
        pre_fetched_data.experiments = []
        experiment = Experiment()
        experiment.name = "test_experiment"
        experiment.id = 1
        experiment.unitType = "user_id"
        experiment.iteration = 1
        experiment.seedHi = 1
        experiment.seedLo = 1
        experiment.trafficSeedHi = 1
        experiment.trafficSeedLo = 1
        experiment.split = [50, 50]
        experiment.trafficSplit = [100, 0]
        experiment.fullOnVariant = 0
        experiment.variants = []
        pre_fetched_data.experiments.append(experiment)

        context = sdk.create_context_with(context_config, pre_fetched_data)

        self.assertIsNotNone(context)
        self.assertIsInstance(context, Context)
        self.assertTrue(context.is_ready())
        mock_data_provider.get_context_data.assert_not_called()
        context.close()

    def test_sdk_close(self):
        mock_data_provider = Mock(spec=ContextDataProvider)
        future_data = Future()
        context_data = ContextData()
        context_data.experiments = []
        future_data.set_result(context_data)
        mock_data_provider.get_context_data.return_value = future_data

        mock_event_handler = Mock(spec=ContextEventHandler)
        publish_future = Future()
        publish_future.set_result(None)
        mock_event_handler.publish.return_value = publish_future

        config = ABSmartlyConfig()
        config.context_data_provider = mock_data_provider
        config.context_event_handler = mock_event_handler

        sdk = ABSmartly(config)

        context_config = ContextConfig()
        context_config.units = {"user_id": "123456789"}

        context = sdk.create_context(context_config)
        context.wait_until_ready()

        self.assertFalse(context.is_closed())

        context.close()

        self.assertTrue(context.is_closed())


if __name__ == '__main__':
    unittest.main()
