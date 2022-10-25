from typing import Optional

from sdk.context_event_logger import ContextEventLogger


class ContextConfig:
    refresh_interval: int = 0
    publish_delay: int = 0
    event_logger: Optional[ContextEventLogger] = None
    cassigmnents: {} = None
    overrides: {} = None
    attributes: {} = None
    units: {} = None

