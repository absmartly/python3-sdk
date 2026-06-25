import warnings
from typing import Optional

from sdk.audience_deserializer import AudienceDeserializer
from sdk.client import Client
from sdk.context_data_provider import ContextDataProvider
from sdk.context_publisher import ContextPublisher
from sdk.context_event_logger import ContextEventLogger
from sdk.variable_parser import VariableParser


class ABsmartlyConfig:
    context_data_provider: Optional[ContextDataProvider] = None
    context_publisher: Optional[ContextPublisher] = None
    context_event_logger: Optional[ContextEventLogger] = None
    audience_deserializer: Optional[AudienceDeserializer] = None
    client: Optional[Client] = None
    variable_parser: Optional[VariableParser] = None

    @property
    def context_event_handler(self) -> Optional[ContextPublisher]:
        warnings.warn(
            "context_event_handler is deprecated, use context_publisher instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.context_publisher

    @context_event_handler.setter
    def context_event_handler(self, value: Optional[ContextPublisher]):
        warnings.warn(
            "context_event_handler is deprecated, use context_publisher instead",
            DeprecationWarning,
            stacklevel=2,
        )
        self.context_publisher = value


class ABSmartlyConfig(ABsmartlyConfig):
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "ABSmartlyConfig is deprecated, use ABsmartlyConfig instead",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
