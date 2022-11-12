from typing import Optional

import jsons
from jsons import DeserializationError

from sdk.context_data_deserializer import ContextDataDeserializer
from sdk.json.context_data import ContextData


class DefaultContextDataDeserializer(ContextDataDeserializer):
    def deserialize(self,
                    bytes_: bytes,
                    offset: int,
                    length: int) -> Optional[ContextData]:
        try:
            return jsons.loadb(bytes_, ContextData)
        except DeserializationError:
            return None
