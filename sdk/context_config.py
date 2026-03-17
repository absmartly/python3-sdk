import warnings
from typing import Dict, Optional

from sdk.context_event_logger import ContextEventLogger


class ContextConfig:
    refresh_interval: int = 50
    publish_delay: int = 50
    event_logger: Optional[ContextEventLogger] = None
    custom_assignments: Optional[Dict] = None
    overrides: Optional[Dict] = None
    attributes: Optional[Dict] = None
    units: Optional[Dict] = None
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
