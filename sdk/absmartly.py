from concurrent.futures import Future
from typing import Optional

from sdk.absmartly_config import ABsmartlyConfig
from sdk.audience_matcher import AudienceMatcher
from sdk.client import Client
from sdk.client_config import ClientConfig
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.context_event_logger import ContextEventLogger
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_context_data_provider import DefaultContextDataProvider
from sdk.default_context_publisher import DefaultContextPublisher
from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.default_variable_parser import DefaultVariableParser
from sdk.json.context_data import ContextData
from sdk.time.system_clock_utc import SystemClockUTC


class ABsmartly:

    @classmethod
    def create(
        cls,
        endpoint: str,
        api_key: str,
        application: str,
        environment: str,
        timeout: int = 3,
        retries: int = 5,
        event_logger: Optional[ContextEventLogger] = None
    ) -> "ABsmartly":
        if not endpoint:
            raise ValueError("endpoint is required and cannot be empty")
        if not api_key:
            raise ValueError("api_key is required and cannot be empty")
        if not application:
            raise ValueError("application is required and cannot be empty")
        if not environment:
            raise ValueError("environment is required and cannot be empty")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if retries < 0:
            raise ValueError("retries must be 0 or greater")

        client_config = ClientConfig()
        client_config.endpoint = endpoint
        client_config.api_key = api_key
        client_config.application = application
        client_config.environment = environment

        http_client_config = DefaultHTTPClientConfig()
        http_client_config.connection_timeout = timeout
        http_client_config.max_retries = retries

        http_client = DefaultHTTPClient(http_client_config)
        client = Client(client_config, http_client)

        sdk_config = ABsmartlyConfig()
        sdk_config.client = client
        if event_logger is not None:
            sdk_config.context_event_logger = event_logger

        return cls(sdk_config)

    def __init__(self, config: ABsmartlyConfig):
        self.context_data_provider = config.context_data_provider
        self.context_event_handler = config.context_event_handler
        self.context_event_logger = config.context_event_logger
        self.variable_parser = config.variable_parser
        self.audience_deserializer = config.audience_deserializer

        if self.context_data_provider is None or \
                self.context_event_handler is None:
            self.client = config.client

            if self.context_data_provider is None:
                self.context_data_provider = \
                    DefaultContextDataProvider(self.client)

            if self.context_event_handler is None:
                self.context_event_handler = \
                    DefaultContextPublisher(self.client)

        if self.variable_parser is None:
            self.variable_parser = DefaultVariableParser()

        if self.audience_deserializer is None:
            self.audience_deserializer = DefaultAudienceDeserializer()

    def get_context_data(self) -> Future[Optional[ContextData]]:
        return self.context_data_provider.get_context_data()

    def create_context(self, config: ContextConfig) -> Context:
        return Context(SystemClockUTC(),
                       config,
                       self.context_data_provider.get_context_data(),
                       self.context_data_provider,
                       self.context_event_handler,
                       self.context_event_logger,
                       self.variable_parser,
                       AudienceMatcher(self.audience_deserializer))

    def create_context_with(self,
                            config: ContextConfig,
                            data: ContextData) -> Context:
        future_data = Future()
        future_data.set_result(data)
        return Context(SystemClockUTC(), config,
                       future_data,
                       self.context_data_provider,
                       self.context_event_handler,
                       self.context_event_logger,
                       self.variable_parser,
                       AudienceMatcher(self.audience_deserializer))


class ABSmartly(ABsmartly):
    def __init__(self, *args, **kwargs):
        import warnings
        warnings.warn(
            "ABSmartly is deprecated, use ABsmartly instead",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
