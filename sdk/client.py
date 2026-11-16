from sdk.client_config import ClientConfig
from sdk.http_client import HTTPClient
from sdk.json.publish_event import PublishEvent
from sdk.version import AGENT, NAME, VERSION

_MAX_APPLICATION_VERSION_DIGITS = 18


def _application_version_header(value):
    # The collector reads X-Application-Version as a long, so (like the Java
    # SDK) only a trimmed string of 1-18 ASCII digits is sent; anything else,
    # such as a dotted "2.4.1", is sent as "0" rather than failing every
    # fetch and publish.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return "0"
    text = str(value).strip()
    if 0 < len(text) <= _MAX_APPLICATION_VERSION_DIGITS and \
            text.isascii() and text.isdigit():
        return text
    return "0"


class Client:

    def __init__(self, config: ClientConfig, http_client: HTTPClient):
        self.serializer = config.serializer
        self.deserializer = config.deserializer
        self.executor = config.executor
        endpoint = config.endpoint
        api_key = config.api_key
        application = config.application
        environment = config.environment
        application_version = getattr(config, "application_version", None)

        # Kept so the context can evaluate audiences and assignment-rule
        # conditions against the configured application and environment names
        # (the collector adds them to every event server-side).
        self.application = application
        self.environment = environment
        self.application_version = application_version

        self.url = endpoint + "/context"
        self.http_client = http_client

        self.headers = {"X-API-Key": api_key,
                        "X-Application": application,
                        "X-Environment": environment,
                        "X-Application-Version":
                            _application_version_header(application_version),
                        "X-Agent": AGENT}
        self.query = {"application": application,
                      "environment": environment}

    def get_application(self):
        return self.application

    def get_application_version(self):
        return self.application_version

    def get_environment(self):
        return self.environment

    def get_agent_name(self):
        return NAME

    def get_agent_version(self):
        return VERSION

    def get_agent(self):
        return AGENT

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
