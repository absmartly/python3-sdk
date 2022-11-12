import os
from concurrent.futures import ThreadPoolExecutor

from sdk.default_context_data_deserializer import \
    DefaultContextDataDeserializer
from sdk.default_context_event_serializer import \
    DefaultContextEventSerializer


class ClientConfig:
    def __init__(self, prefix=""):
        self.executor = ThreadPoolExecutor()
        self.endpoint = os.environ.get(prefix + "endpoint")
        self.environment = os.environ.get(prefix + "environment")
        self.application = os.environ.get(prefix + "application")
        self.api_key = os.environ.get(prefix + "api_key")
        self.serializer = DefaultContextEventSerializer()
        self.deserializer = DefaultContextDataDeserializer()
