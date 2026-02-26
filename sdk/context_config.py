import warnings
from typing import Optional

from sdk.context_event_logger import ContextEventLogger


class ContextConfig:
    refresh_interval: int = 50
    publish_delay: int = 50  # seconds
    event_logger: Optional[ContextEventLogger] = None
    custom_assignments: {} = None
    overrides: {} = None
    attributes: {} = None
    units: {} = None
    historic: bool = False

    @property
    def cassigmnents(self):
        warnings.warn(
            "'cassigmnents' is deprecated and will be removed in a future version. "
            "Use 'custom_assignments' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.custom_assignments

    @cassigmnents.setter
    def cassigmnents(self, value):
        warnings.warn(
            "'cassigmnents' is deprecated and will be removed in a future version. "
            "Use 'custom_assignments' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.custom_assignments = value
