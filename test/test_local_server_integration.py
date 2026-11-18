import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from sdk.absmartly import ABsmartly
from sdk.context_config import ContextConfig


RECORDED = []
# The GET /context body; a test may replace it.
CONTEXT = {"experiments": []}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        RECORDED.append({
            "method": "GET",
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": None,
        })
        payload = json.dumps(CONTEXT).encode("utf-8")
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
        CONTEXT.clear()
        CONTEXT["experiments"] = []

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

        get_reqs = [r for r in RECORDED if r["method"] == "GET"]
        self.assertTrue(len(get_reqs) >= 1, "expected a GET /context")
        get = get_reqs[0]
        parsed = urlparse(get["path"])
        self.assertEqual(parsed.path, "/context")
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get("application"), ["website"])
        self.assertEqual(qs.get("environment"), ["dev"])

        context.track("payment", {"value": 99})
        context.publish()

        put_reqs = [r for r in RECORDED if r["method"] == "PUT"]
        self.assertTrue(len(put_reqs) >= 1, "expected a PUT /context")
        put = put_reqs[0]
        self.assertEqual(urlparse(put["path"]).path, "/context")

        h = put["headers"]
        self.assertEqual(h.get("x-api-key"), "test-api-key")
        self.assertEqual(h.get("x-application"), "website")
        self.assertEqual(h.get("x-environment"), "dev")
        self.assertEqual(h.get("x-application-version"), "0")
        self.assertTrue(h.get("x-agent"))
        self.assertIn("application/json", h.get("content-type", ""))

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

    def test_holdouts_over_real_get_and_put(self):
        # session_id e791e240... is in arm 0 (held out) of a [0.1, 0.9]
        # holdout with seeds 13/111, and in variant 1 of the experiments.
        def experiment(id, name, holdout_ids):
            return {
                "id": id, "name": name, "iteration": 1,
                "unitType": "session_id", "seedHi": 100, "seedLo": 200,
                "split": [0.5, 0.5], "trafficSeedHi": 1, "trafficSeedLo": 2,
                "trafficSplit": [0, 1], "fullOnVariant": 0,
                "applications": [{"name": "website"}],
                "variants": [{"name": "A", "config": None},
                             {"name": "B", "config": None}],
                "audienceStrict": False, "audience": None,
                "holdoutIds": holdout_ids,
            }

        CONTEXT["experiments"] = [experiment(1, "exp_covered", [11]),
                                  experiment(2, "exp_plain", None)]
        CONTEXT["holdouts"] = [{
            "id": 11, "name": "holdout_a", "unitType": "session_id",
            "iteration": 1, "seedHi": 13, "seedLo": 111, "split": [0.1, 0.9],
            "futureField": {"x": [1]},
        }]
        sdk = ABsmartly.create(endpoint=self.base_url, api_key="test-api-key",
                               application="website", environment="dev")
        config = ContextConfig()
        config.units = {"session_id": "e791e240fcd3df7d238cfc285f475e8152fcc0ec"}
        context = sdk.create_context(config)
        context.wait_until_ready()

        self.assertEqual(0, context.get_treatment("exp_covered"))
        self.assertEqual(1, context.get_treatment("exp_plain"))
        context.publish()

        body = [r for r in RECORDED if r["method"] == "PUT"][0]["body"]
        self.assertEqual(
            [(11, "holdout_a", 0, True), (2, "exp_plain", 1, True)],
            [(e["id"], e["name"], e["variant"], e["assigned"])
             for e in body["exposures"]])
        context.close()


if __name__ == "__main__":
    unittest.main()
