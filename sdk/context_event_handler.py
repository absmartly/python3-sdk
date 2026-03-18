import warnings

from sdk.context_publisher import ContextPublisher

warnings.warn(
    "ContextEventHandler is deprecated, use ContextPublisher instead.",
    DeprecationWarning,
    stacklevel=2
)

ContextEventHandler = ContextPublisher
