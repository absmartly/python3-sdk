from concurrent.futures import Future
from typing import Optional

from sdk.client import Client
from sdk.context_data_provider import ContextDataProvider
from sdk.json.context_data import ContextData


class DefaultContextDataProvider(ContextDataProvider):

    def __init__(self, client: Client):
        self.client = client

    def get_context_data(self) -> Future[Optional[ContextData]]:
        return self.client.get_context_data()
