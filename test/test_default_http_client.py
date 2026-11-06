import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

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
        # PUT is outside the allowed methods, so it is sent once and the
        # 503 response is returned; the caller sees an HTTPError only when
        # it calls raise_for_status(), exactly as in v0.2.4.
        response = self.make_client().put(self.url, {}, {}, bytearray(b'{}'))
        self.assertEqual(['PUT'], _Handler.calls)
        with self.assertRaises(requests.HTTPError):
            response.raise_for_status()

    def test_get_retried_on_503_then_raises_retry_error(self):
        # retries=2 means 1 initial + 2 retries = 3 attempts; once they are
        # exhausted urllib3 raises, which requests surfaces as a RetryError,
        # preserving the v0.2.4 exhausted-GET exception type.
        with self.assertRaises(requests.exceptions.RetryError):
            self.make_client().get(self.url, {}, {})
        self.assertEqual(['GET'] * 3, _Handler.calls)

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
        with self.assertRaises(requests.exceptions.RetryError):
            client.put(self.url, {}, {}, bytearray(b'{}'))
        self.assertEqual(['PUT'] * 3, _Handler.calls)

    def test_legacy_duck_typed_config_keeps_v024_policy(self):
        # A v0.2.4-style config carries only the released fields.
        config = SimpleNamespace(connection_timeout=3,
                                 connection_request_timeout=1,
                                 retry_interval=0, max_retries=2)
        client = DefaultHTTPClient(config)
        with self.assertRaises(requests.exceptions.RetryError):
            client.get(self.url, {}, {})
        self.assertEqual(['GET'] * 3, _Handler.calls)
        _Handler.calls = []
        client.put(self.url, {}, {}, bytearray(b'{}'))
        self.assertEqual(['PUT'], _Handler.calls)

    def test_legacy_subclass_without_super_init(self):
        class LegacyConfig(DefaultHTTPClientConfig):
            def __init__(self):
                self.connection_timeout = 3
                self.connection_request_timeout = 1
                self.retry_interval = 0
                self.max_retries = 2

        with self.assertRaises(requests.exceptions.RetryError):
            DefaultHTTPClient(LegacyConfig()).get(self.url, {}, {})
        self.assertEqual(['GET'] * 3, _Handler.calls)


if __name__ == '__main__':
    unittest.main()
