from sdk.context_event_handler import ContextEventHandler
from sdk.default_context_publisher import DefaultContextPublisher


class DefaultContextEventHandler(DefaultContextPublisher, ContextEventHandler):
    """Deprecated: use DefaultContextPublisher instead.

    Constructing it does not warn, so code written against v0.2.4 keeps
    running under ``-W error::DeprecationWarning``.
    """
