from concurrent.futures import Future

from sdk.audience_matcher import AudienceMatcher
from sdk.context_config import ContextConfig
from sdk.context_data_provider import ContextDataProvider
from sdk.context_event_handler import ContextEventHandler
from sdk.context_event_logger import ContextEventLogger
from sdk.time.clock import Clock
from sdk.variable_parser import VariableParser


class Context:
    def __init__(self, utc: Clock, config: ContextConfig, data: Future, provider: ContextDataProvider,
                 handler: ContextEventHandler, logger: ContextEventLogger, parser: VariableParser,
                 matcher: AudienceMatcher):
        print("da")