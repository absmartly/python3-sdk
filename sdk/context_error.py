class ContextError(RuntimeError):
    """Raised by Context for lifecycle errors (closed, closing, not ready).

    ``str(error)`` keeps the v0.2.4 message so existing callers matching on it
    keep working; ``canonical_message`` carries the cross-SDK wording.
    """

    def __init__(self, message: str, canonical_message: str = None):
        super().__init__(message)
        self.canonical_message = canonical_message or message


class ContextValueError(ValueError):
    """Raised by Context for invalid arguments; see ContextError."""

    def __init__(self, message: str, canonical_message: str = None):
        super().__init__(message)
        self.canonical_message = canonical_message or message
