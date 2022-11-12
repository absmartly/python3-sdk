import requests as req
from requests.adapters import HTTPAdapter, Response
from urllib3 import Retry

from sdk.default_http_client_config import DefaultHTTPClientConfig
from sdk.http_client import HTTPClient


class DefaultHTTPClient(HTTPClient):

    def __init__(self, config: DefaultHTTPClientConfig):
        self.http_client = req.Session()
        retry = Retry(total=config.max_retries, read=config.max_retries,
                      connect=config.max_retries,
                      backoff_factor=config.retry_interval,
                      status_forcelist=(502, 503),
                      allowed_methods=frozenset(['GET', 'POST']))
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
        return self.http_client.put(url,
                                    data=bytes(body),
                                    params=query,
                                    headers=headers,
                                    timeout=(self.timeout,
                                             self.request_timeout))
