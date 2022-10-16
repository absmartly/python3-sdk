from abc import abstractmethod

from sdk.json.publish_event import PublishEvent


class ContextEventSerializer:

    @abstractmethod
    def serialize(self, publish_event: PublishEvent) -> bytearray:
        raise NotImplementedError
