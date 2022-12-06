from sdk.client_config import ClientConfig
from sdk.http_client import HTTPClient
from sdk.json.publish_event import PublishEvent


class Client:

    def __init__(self, config: ClientConfig, http_client: HTTPClient):
        self.serializer = config.serializer
        self.deserializer = config.deserializer
        self.executor = config.executor
        endpoint = config.endpoint
        api_key = config.api_key
        application = config.application
        environment = config.environment

        self.url = endpoint + "/context"
        self.http_client = http_client

        self.headers = {"X-API-Key": api_key,
                        "X-Application": application,
                        "X-Environment": environment,
                        "X-Application-Version": '0',
                        "X-Agent": "absmartly-python-sdk"}
        self.query = {"application": application,
                      "environment": environment}

    def get_context_data(self):
        return self.executor.submit(self.send_get, self.url, self.query, {})

    def send_get(self, url: str, query: dict, headers: dict):
        response = self.http_client.get(url, query, headers)
        if response.status_code // 100 == 2:
            content = response.content
            return self.deserializer.deserialize(content, 0, len(content))
        return response.raise_for_status()

    def publish(self, event: PublishEvent):
        return self.executor.submit(
            self.send_put,
            self.url,
            {},
            self.headers,
            event)

    def send_put(self,
                 url: str,
                 query: dict,
                 headers: dict,
                 event: PublishEvent):
        content = self.serializer.serialize(event)
        response = self.http_client.put(url, query, headers, content)
        if response.status_code // 100 == 2:
            content = response.content
            return self.deserializer.deserialize(content, 0, len(content))
        return response.raise_for_status()
