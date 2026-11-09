from typing import Optional
import logging

import jsons

from sdk.context_data_deserializer import ContextDataDeserializer
from sdk.json.context_data import ContextData

logger = logging.getLogger(__name__)


class DefaultContextDataDeserializer(ContextDataDeserializer):
    def deserialize(self,
                    bytes_: bytes,
                    offset: int,
                    length: int) -> Optional[ContextData]:
        # Returns None on invalid input, as in v0.2.4; Context fails the
        # load (instead of hanging) when the data it receives is None.
        try:
            return jsons.loadb(bytes_, ContextData)
        except Exception as e:
            logger.error(f"Failed to deserialize context data: {e}")
            return None
