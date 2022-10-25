from abc import abstractmethod
from concurrent.futures import Future
from typing import Optional

from sdk.context import Context
from sdk.json.context_data import ContextData
from sdk.json.publish_event import PublishEvent


class ContextEventHandler:

    @abstractmethod
    def publish(self, context: Context, event: PublishEvent) -> Future[Optional[ContextData]]:
        raise NotImplementedError
