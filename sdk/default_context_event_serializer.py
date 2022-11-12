import jsons

from sdk.context_event_serializer import ContextEventSerializer
from sdk.json.publish_event import PublishEvent


class DefaultContextEventSerializer(ContextEventSerializer):

    def serialize(self, publish_event: PublishEvent) -> bytearray:
        str_result = jsons.dumps(publish_event, strip_nulls=True)
        return bytearray(str_result, encoding='utf-8')
