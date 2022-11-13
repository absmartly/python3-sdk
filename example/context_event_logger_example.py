import jsons

from sdk.context_event_logger import ContextEventLogger, EventType


class ContextEventLoggerExample(ContextEventLogger):

    def handle_event(self, event_type: EventType, data: object):
        print("LOGGER EVENT: " +
              str(event_type) + " " +
              str(jsons.dumps(data)))
