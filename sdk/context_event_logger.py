from abc import abstractmethod
from enum import Enum


class EventType(Enum):
    ERROR = "error"
    READY = "ready"
    REFRESH = "refresh"
    PUBLISH = "publish"
    EXPOSURE = "exposure"
    GOAL = "goal"
    CLOSE = "close"


class ContextEventLogger:

    @abstractmethod
    def handle_event(self, event_type: EventType, data: object):
        raise NotImplementedError
