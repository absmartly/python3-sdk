import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from sdk.absmartly import ABsmartly
from sdk.context_config import ContextConfig


# Shared list capturing every request the local server received.
RECORDED = []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the default stderr logging
        pass

    def do_GET(self):
        RECORDED.append({
            "method": "GET",
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": None,
        })
        payload = json.dumps({"experiments": []}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_PUT(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        RECORDED.append({
            "method": "PUT",
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(raw.decode("utf-8")) if raw else None,
        })
        payload = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class LocalServerIntegrationTest(unittest.TestCase):
    """Hermetic integration test: a real local HTTP server on an ephemeral port,
    driven by the public SDK API so the real DefaultHTTPClient makes GET/PUT
    /context calls matching the wire contract."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        RECORDED.clear()

    def test_real_get_and_put_context(self):
        sdk = ABsmartly.create(
            endpoint=self.base_url,
            api_key="test-api-key",
            application="website",
            environment="dev",
        )

        context_config = ContextConfig()
        context_config.units = {"user_id": "123456789"}

        context = sdk.create_context(context_config)
        context.wait_until_ready()

        # --- assert the real GET /context ---
        get_reqs = [r for r in RECORDED if r["method"] == "GET"]
        self.assertTrue(len(get_reqs) >= 1, "expected a GET /context")
        get = get_reqs[0]
        parsed = urlparse(get["path"])
        self.assertEqual(parsed.path, "/context")
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get("application"), ["website"])
        self.assertEqual(qs.get("environment"), ["dev"])

        # --- queue an event then publish ---
        context.track("payment", {"value": 99})
        context.publish()

        put_reqs = [r for r in RECORDED if r["method"] == "PUT"]
        self.assertTrue(len(put_reqs) >= 1, "expected a PUT /context")
        put = put_reqs[0]
        self.assertEqual(urlparse(put["path"]).path, "/context")

        # --- headers ---
        h = put["headers"]
        self.assertEqual(h.get("x-api-key"), "test-api-key")
        self.assertEqual(h.get("x-application"), "website")
        self.assertEqual(h.get("x-environment"), "dev")
        self.assertEqual(h.get("x-application-version"), "0")
        self.assertTrue(h.get("x-agent"))
        self.assertIn("application/json", h.get("content-type", ""))

        # --- body ---
        body = put["body"]
        self.assertIn("hashed", body)
        self.assertIsInstance(body["units"], list)
        self.assertTrue(len(body["units"]) > 0)
        self.assertIn("type", body["units"][0])
        self.assertIn("uid", body["units"][0])
        self.assertIn("publishedAt", body)
        self.assertIsInstance(body["publishedAt"], int)
        self.assertIn("goals", body)
        self.assertTrue(len(body["goals"]) > 0)
        self.assertEqual(body["goals"][0]["name"], "payment")

        context.close()


if __name__ == "__main__":
    unittest.main()
