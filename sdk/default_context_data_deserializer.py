from typing import Optional
import logging

import jsons
from jsons import DeserializationError

from sdk.context_data_deserializer import ContextDataDeserializer
from sdk.json.context_data import ContextData

logger = logging.getLogger(__name__)


class DefaultContextDataDeserializer(ContextDataDeserializer):
    def deserialize(self,
                    bytes_: bytes,
                    offset: int,
                    length: int) -> Optional[ContextData]:
        try:
            return jsons.loadb(bytes_, ContextData)
        except DeserializationError as e:
            logger.error(f"Failed to deserialize context data: {e}")
            raise ValueError(f"Failed to deserialize context data: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error deserializing context data: {e}")
            raise ValueError(f"Unexpected error deserializing context data: {e}") from e
