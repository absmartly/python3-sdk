from typing import Optional

import jsons
from jsons import DeserializationError

from sdk.audience_deserializer import AudienceDeserializer


class DefaultAudienceDeserializer(AudienceDeserializer):
    def deserialize(self,
                    bytes_: bytes,
                    offset: int,
                    length: int) -> Optional[dict]:
        try:
            return jsons.loadb(bytes_, dict)
        except DeserializationError:
            return None
