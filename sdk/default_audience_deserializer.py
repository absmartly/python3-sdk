from typing import Optional
import logging

import jsons
from jsons import DeserializationError

from sdk.audience_deserializer import AudienceDeserializer

logger = logging.getLogger(__name__)


class DefaultAudienceDeserializer(AudienceDeserializer):
    def deserialize(self,
                    bytes_: bytes,
                    offset: int,
                    length: int) -> Optional[dict]:
        try:
            segment = bytes_[offset:offset + length]
            if segment == b'null':
                return None
            return jsons.loadb(segment, dict)
        except Exception as e:
            logger.error(f"Failed to deserialize audience filter: {e}")
            return None
