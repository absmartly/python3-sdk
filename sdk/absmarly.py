from concurrent.futures import Future
from typing import Optional

from sdk.absmartly_config import ABSmartlyConfig
from sdk.audience_matcher import AudienceMatcher
from sdk.context import Context
from sdk.context_config import ContextConfig
from sdk.default_audience_deserializer import DefaultAudienceDeserializer
from sdk.default_context_data_provider import DefaultContextDataProvider
from sdk.default_context_event_handler import DefaultContextEventHandler
from sdk.default_variable_parser import DefaultVariableParser
from sdk.json.context_data import ContextData
from sdk.time.system_clock_utc import SystemClockUTC


class ABSmartly:

    def __init__(self, config: ABSmartlyConfig):
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
                    DefaultContextEventHandler(self.client)

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
