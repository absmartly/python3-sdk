import warnings

from sdk.client import Client
from sdk.default_context_publisher import DefaultContextPublisher


class DefaultContextEventHandler(DefaultContextPublisher):
    """Deprecated: Use DefaultContextPublisher instead."""

    def __init__(self, client: Client):
        warnings.warn(
            "DefaultContextEventHandler is deprecated, use DefaultContextPublisher instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(client)
