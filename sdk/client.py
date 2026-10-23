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

    def _handle_response(self, response):
        """Helper method to handle HTTP response and deserialize content."""
        if response.status_code // 100 == 2:
            content = response.content
            return self.deserializer.deserialize(content, 0, len(content))
        response.raise_for_status()
        raise RuntimeError(f"Unexpected HTTP status {response.status_code}")

    def get_context_data(self):
        return self.executor.submit(self.send_get, self.url, self.query, self.headers)

    def send_get(self, url: str, query: dict, headers: dict):
        request_headers = dict(headers) if headers else {}
        response = self.http_client.get(url, query, request_headers)
        return self._handle_response(response)

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
        request_headers = dict(headers) if headers else {}
        content = self.serializer.serialize(event)
        response = self.http_client.put(url, query, request_headers, content)
        return self._handle_response(response)

    def post(self, url: str, query: dict, headers: dict, event: PublishEvent):
        return self.send_post(url, query, headers, event)

    def send_post(self,
                  url: str,
                  query: dict,
                  headers: dict,
                  event: PublishEvent):
        request_headers = dict(headers) if headers else {}
        content = self.serializer.serialize(event)
        response = self.http_client.post(url, query, request_headers, content)
        return self._handle_response(response)
