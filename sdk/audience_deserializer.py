from abc import abstractmethod
from typing import Optional


class AudienceDeserializer:

    @abstractmethod
    def deserialize(self,
                    bytes_: bytes,
                    offset: int,
                    length: int) -> Optional[dict]:
        raise NotImplementedError
