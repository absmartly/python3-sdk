import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from sdk.default_http_client import DefaultHTTPClient
from sdk.default_http_client_config import DefaultHTTPClientConfig


class _Handler(BaseHTTPRequestHandler):
    calls = []
    status = 503

    def _reply(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length:
            self.rfile.read(length)
        _Handler.calls.append(self.command)
        self.send_response(_Handler.status)
        self.send_header('Content-Length', '0')
        self.end_headers()

    do_GET = do_PUT = do_POST = _reply

    def log_message(self, *args):
        pass


class DefaultHTTPClientRetryTest(unittest.TestCase):
    def setUp(self):
        _Handler.calls = []
        _Handler.status = 503
        self.server = HTTPServer(('127.0.0.1', 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1/context'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def make_client(self, **overrides):
        config = DefaultHTTPClientConfig()
        config.max_retries = 2
        config.retry_interval = 0
        for key, value in overrides.items():
            setattr(config, key, value)
        return DefaultHTTPClient(config)

    def test_publish_put_is_not_retried_on_status(self):
        response = self.make_client().put(self.url, {}, {}, bytearray(b'{}'))
        self.assertEqual(['PUT'], _Handler.calls)
        with self.assertRaises(requests.HTTPError):
            response.raise_for_status()

    def test_get_retried_on_503_then_returns_last_response(self):
        response = self.make_client().get(self.url, {}, {})
        self.assertEqual(['GET'] * 3, _Handler.calls)
        with self.assertRaises(requests.HTTPError):
            response.raise_for_status()

    def test_get_not_retried_on_500(self):
        _Handler.status = 500
        self.make_client().get(self.url, {}, {})
        self.assertEqual(['GET'], _Handler.calls)

    def test_wider_policy_is_opt_in(self):
        # 500 is outside the default (502, 503) list, so this only retries
        # when both the status list and the allowed methods are widened.
        _Handler.status = 500
        client = self.make_client(
            retry_status_forcelist=frozenset(range(500, 600)),
            retry_allowed_methods=frozenset(['GET', 'POST', 'PUT']))
        client.put(self.url, {}, {}, bytearray(b'{}'))
        self.assertEqual(['PUT'] * 3, _Handler.calls)


if __name__ == '__main__':
    unittest.main()
