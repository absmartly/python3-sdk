from abc import abstractmethod

from sdk.json.context_data import ContextData


class ContextDataDeserializer:

    @abstractmethod
    def deserialize(self,
                    bytes_: bytearray,
                    offset: int,
                    length: int) -> ContextData:
        raise NotImplementedError
