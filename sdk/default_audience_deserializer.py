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
            if bytes_ == b'null' or (offset == 0 and length == 4 and bytes_[offset:offset+length] == b'null'):
                return None
            return jsons.loadb(bytes_, dict)
        except Exception as e:
            logger.error(f"Failed to deserialize audience filter: {e}")
            return None
