from typing import Optional

from sdk.audience_deserializer import AudienceDeserializer
from sdk.client import Client
from sdk.context_data_provider import ContextDataProvider
from sdk.context_event_handler import ContextEventHandler
from sdk.context_event_logger import ContextEventLogger
from sdk.variable_parser import VariableParser


class ABSmartlyConfig:
    context_data_provider: Optional[ContextDataProvider]
    context_event_handler: Optional[ContextEventHandler]
    context_event_logger: Optional[ContextEventLogger]
    audience_deserializer: Optional[AudienceDeserializer]
    client: Optional[Client]
    variable_parser: Optional[VariableParser]


