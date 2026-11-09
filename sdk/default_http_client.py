import requests as req
from requests.adapters import HTTPAdapter, Response
from urllib3 import Retry

from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.http_client import HTTPClient


class DefaultHTTPClient(HTTPClient):

    def __init__(self, config: DefaultHTTPClientConfig):
        self.http_client = req.Session()
        # Keep v0.2.4's exhausted-retry behaviour: the default
        # raise_on_status=True makes urllib3 raise RetryError once GET
        # retries are exhausted, rather than returning the last 502/503
        # response (which would otherwise surface as a plain HTTPError).
        # getattr: duck-typed or v0.2.4-style configs (no super().__init__)
        # lack the retry policy fields and keep the v0.2.4 policy.
        retry = Retry(total=config.max_retries, read=config.max_retries,
                      connect=config.max_retries,
                      backoff_factor=config.retry_interval,
                      status_forcelist=getattr(
                          config, 'retry_status_forcelist', (502, 503)),
                      allowed_methods=getattr(
                          config, 'retry_allowed_methods',
                          frozenset(('GET', 'POST'))))
        self.http_client.mount(
            'http://', HTTPAdapter(max_retries=retry,
                                   pool_maxsize=200,
                                   pool_connections=20))
        self.http_client.mount(
            'https://', HTTPAdapter(max_retries=retry,
                                    pool_maxsize=200,
                                    pool_connections=20))
        self.timeout = config.connection_timeout
        self.request_timeout = config.connection_request_timeout

    def get(self,
            url: str,
            query: dict,
            headers: dict) -> Response:
        return self.http_client.get(url,
                                    params=query,
                                    headers=headers,
                                    timeout=(self.timeout,
                                             self.request_timeout))

    def put(self,
            url: str,
            query: dict,
            headers: dict,
            body: bytearray) -> Response:
        headers.update({'Content-type': 'application/json'})
        return self.http_client.put(url,
                                    data=bytes(body),
                                    params=query,
                                    headers=headers,
                                    timeout=(self.timeout,
                                             self.request_timeout))

    def post(self,
             url: str,
             query: dict,
             headers: dict,
             body: bytearray) -> Response:
        headers.update({'Content-type': 'application/json'})
        return self.http_client.post(url,
                                     data=bytes(body),
                                     params=query,
                                     headers=headers,
                                     timeout=(self.timeout,
                                              self.request_timeout))
