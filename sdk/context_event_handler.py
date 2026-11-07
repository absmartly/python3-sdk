from abc import abstractmethod
from concurrent.futures import Future
from typing import Optional

from sdk.context_publisher import ContextPublisher
from sdk.json.context_data import ContextData
from sdk.json.publish_event import PublishEvent


class ContextEventHandler:
    """Deprecated: implement ContextPublisher instead.

    Kept as the v0.2.4 plain base class, so a subclass that does not
    override publish can still be instantiated, and importing it does not
    warn. It is registered as a virtual ContextPublisher.
    """

    @abstractmethod
    def publish(self, context, event: PublishEvent) -> \
            Future[Optional[ContextData]]:
        raise NotImplementedError


ContextPublisher.register(ContextEventHandler)
