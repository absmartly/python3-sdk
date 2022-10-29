from abc import abstractmethod
from concurrent.futures import Future
from typing import Optional

from sdk.json.context_data import ContextData


class ContextDataProvider:

    @abstractmethod
    def get_context_data(self) -> Future[Optional[ContextData]]:
        raise NotImplementedError
