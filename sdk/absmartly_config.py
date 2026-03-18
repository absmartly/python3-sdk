from typing import Optional

from sdk.audience_deserializer import AudienceDeserializer
from sdk.client import Client
from sdk.context_data_provider import ContextDataProvider
from sdk.context_publisher import ContextPublisher
from sdk.context_event_logger import ContextEventLogger
from sdk.variable_parser import VariableParser


class ABsmartlyConfig:
    context_data_provider: Optional[ContextDataProvider] = None
    context_event_handler: Optional[ContextPublisher] = None
    context_event_logger: Optional[ContextEventLogger] = None
    audience_deserializer: Optional[AudienceDeserializer] = None
    client: Optional[Client] = None
    variable_parser: Optional[VariableParser] = None


class ABSmartlyConfig(ABsmartlyConfig):
    def __init__(self, *args, **kwargs):
        import warnings
        warnings.warn(
            "ABSmartlyConfig is deprecated, use ABsmartlyConfig instead",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)
