from concurrent.futures import Future
from typing import Optional

from sdk.client import Client
from sdk.context import Context
from sdk.context_publisher import ContextPublisher
from sdk.json.context_data import ContextData
from sdk.json.publish_event import PublishEvent


class DefaultContextPublisher(ContextPublisher):

    def __init__(self, client: Client):
        self.client = client

    def publish(self,
                context: Context,
                event: PublishEvent) -> Future[Optional[ContextData]]:
        return self.client.publish(event)
