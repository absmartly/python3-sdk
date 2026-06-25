import unittest
from unittest.mock import Mock, patch

from sdk.absmartly import ABsmartly
from sdk.absmartly_config import ABsmartlyConfig
from sdk.context_config import ContextConfig
from sdk.context_event_logger import ContextEventLogger


class TestNamedParameterInitialization(unittest.TestCase):

    def test_create_with_all_required_params(self):
        sdk = ABsmartly.create(
            endpoint="https://sandbox.test.io/v1",
            api_key="test-api-key",
            application="website",
            environment="dev"
        )

        self.assertIsNotNone(sdk)
        self.assertIsNotNone(sdk.context_data_provider)
        self.assertIsNotNone(sdk.context_publisher)
        self.assertIsNotNone(sdk.variable_parser)
        self.assertIsNotNone(sdk.audience_deserializer)

    def test_create_with_custom_timeout(self):
        sdk = ABsmartly.create(
            endpoint="https://sandbox.test.io/v1",
            api_key="test-api-key",
            application="website",
            environment="dev",
            timeout=10
        )

        self.assertIsNotNone(sdk)

    def test_create_with_custom_retries(self):
        sdk = ABsmartly.create(
            endpoint="https://sandbox.test.io/v1",
            api_key="test-api-key",
            application="website",
            environment="dev",
            retries=3
        )

        self.assertIsNotNone(sdk)

    def test_create_with_all_optional_params(self):
        mock_logger = Mock(spec=ContextEventLogger)

        sdk = ABsmartly.create(
            endpoint="https://sandbox.test.io/v1",
            api_key="test-api-key",
            application="website",
            environment="dev",
            timeout=5,
            retries=3,
            event_logger=mock_logger
        )

        self.assertIsNotNone(sdk)
        self.assertEqual(sdk.context_event_logger, mock_logger)

    def test_create_missing_endpoint(self):
        with self.assertRaises(ValueError) as context:
            ABsmartly.create(
                endpoint="",
                api_key="test-api-key",
                application="website",
                environment="dev"
            )

        self.assertIn("endpoint", str(context.exception))

    def test_create_missing_api_key(self):
        with self.assertRaises(ValueError) as context:
            ABsmartly.create(
                endpoint="https://sandbox.test.io/v1",
                api_key="",
                application="website",
                environment="dev"
            )

        self.assertIn("api_key", str(context.exception))

    def test_create_missing_application(self):
        with self.assertRaises(ValueError) as context:
            ABsmartly.create(
                endpoint="https://sandbox.test.io/v1",
                api_key="test-api-key",
                application="",
                environment="dev"
            )

        self.assertIn("application", str(context.exception))

    def test_create_missing_environment(self):
        with self.assertRaises(ValueError) as context:
            ABsmartly.create(
                endpoint="https://sandbox.test.io/v1",
                api_key="test-api-key",
                application="website",
                environment=""
            )

        self.assertIn("environment", str(context.exception))

    def test_create_invalid_timeout(self):
        with self.assertRaises(ValueError) as context:
            ABsmartly.create(
                endpoint="https://sandbox.test.io/v1",
                api_key="test-api-key",
                application="website",
                environment="dev",
                timeout=0
            )

        self.assertIn("timeout", str(context.exception))

    def test_create_negative_timeout(self):
        with self.assertRaises(ValueError) as context:
            ABsmartly.create(
                endpoint="https://sandbox.test.io/v1",
                api_key="test-api-key",
                application="website",
                environment="dev",
                timeout=-1
            )

        self.assertIn("timeout", str(context.exception))

    def test_create_negative_retries(self):
        with self.assertRaises(ValueError) as context:
            ABsmartly.create(
                endpoint="https://sandbox.test.io/v1",
                api_key="test-api-key",
                application="website",
                environment="dev",
                retries=-1
            )

        self.assertIn("retries", str(context.exception))

    def test_create_with_zero_retries(self):
        sdk = ABsmartly.create(
            endpoint="https://sandbox.test.io/v1",
            api_key="test-api-key",
            application="website",
            environment="dev",
            retries=0
        )

        self.assertIsNotNone(sdk)

    def test_create_context_with_named_init(self):
        sdk = ABsmartly.create(
            endpoint="https://sandbox.test.io/v1",
            api_key="test-api-key",
            application="website",
            environment="dev"
        )

        context_config = ContextConfig()
        context_config.units = {"user_id": "123456789"}

        context = sdk.create_context(context_config)

        self.assertIsNotNone(context)

    def test_backwards_compatibility_with_config(self):
        from sdk.client import Client
        from sdk.client_config import ClientConfig
        from sdk.default_http_client import DefaultHTTPClient
        from sdk.default_http_client_config import DefaultHTTPClientConfig

        client_config = ClientConfig()
        client_config.endpoint = "https://sandbox.test.io/v1"
        client_config.api_key = "test-api-key"
        client_config.application = "website"
        client_config.environment = "dev"

        http_client = DefaultHTTPClient(DefaultHTTPClientConfig())
        client = Client(client_config, http_client)

        config = ABsmartlyConfig()
        config.client = client

        sdk = ABsmartly(config)

        self.assertIsNotNone(sdk)
        self.assertIsNotNone(sdk.context_data_provider)

    def test_named_params_uses_defaults(self):
        sdk = ABsmartly.create(
            endpoint="https://sandbox.test.io/v1",
            api_key="test-api-key",
            application="website",
            environment="dev"
        )

        self.assertIsNotNone(sdk.client)


if __name__ == '__main__':
    unittest.main()
