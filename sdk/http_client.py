from abc import abstractmethod

from requests.adapters import Response


class HTTPClient:

    @abstractmethod
    def get(self,
            url: str,
            query: dict,
            headers: dict) -> Response:
        raise NotImplementedError

    @abstractmethod
    def put(self,
            url: str,
            query: dict,
            headers: dict,
            body: bytearray) -> Response:
        raise NotImplementedError

    @abstractmethod
    def post(self,
             url: str,
             query: dict,
             headers: dict,
             body: bytearray) -> Response:
        raise NotImplementedError
