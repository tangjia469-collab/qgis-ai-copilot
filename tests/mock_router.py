"""Deterministic local router fixture for manual and automated Alpha tests."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MODELS = [
    {"id": "fixture-model", "owned_by": "local-fixture"},
    {
        "id": "fixture-reasoning-model",
        "owned_by": "local-fixture",
        "supported_reasoning_efforts": ["low", "medium", "high"],
    },
]


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    last_payload = None

    def log_message(self, format, *args):
        return

    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_GET(self):  # noqa: N802
        if self.path.endswith("/slow/v1/models"):
            time.sleep(0.15)
            self._json(200, {"object": "list", "data": [{"id": "stale-model"}]})
            return
        if self.path.endswith("/authfail/v1/models"):
            self._json(401, {"error": {"message": "Fixture token rejected"}})
            return
        if self.path.endswith("/malformed/v1/models"):
            body = b"not-json"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.endswith("/serverfail/v1/models"):
            self._json(503, {"error": {"message": "Fixture catalog unavailable"}})
            return
        if self.path.endswith("/missing/v1/models"):
            self._json(404, {"error": {"message": "Fixture endpoint missing"}})
            return
        if self.path.endswith("/v1/models"):
            self._json(200, {"object": "list", "data": MODELS})
            return
        self._json(404, {"error": {"message": "Fixture endpoint missing"}})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "Malformed fixture request"}})
            return
        FixtureHandler.last_payload = payload
        if not self.path.endswith("/v1/chat/completions"):
            self._json(404, {"error": {"message": "Fixture endpoint missing"}})
            return
        if payload.get("model") == "fixture-rate-limit":
            self._json(429, {"error": {"message": "Fixture rate limit"}})
            return
        if payload.get("model") == "fixture-server-error":
            self._json(503, {"error": {"message": "Fixture router unavailable"}})
            return
        if payload.get("model") == "fixture-malformed-response":
            self._json(200, {"choices": []})
            return
        if payload.get("model") == "fixture-slow-old":
            time.sleep(0.15)
        text = "The local fixture received QGIS metadata only."
        if not payload.get("stream"):
            self._json(
                200,
                {
                    "choices": [{"message": {"role": "assistant", "content": text}}],
                    "usage": {"total_tokens": 12},
                },
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        parts = ["The local ", "fixture received ", "QGIS metadata only."]
        for part in parts:
            event = {"choices": [{"delta": {"content": part}}]}
            try:
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except BrokenPipeError:
                return
            time.sleep(0.04)
        if payload.get("model") != "fixture-broken-stream":
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except BrokenPipeError:
                pass


def start_fixture(host: str = "127.0.0.1", port: int = 0):
    server = ThreadingHTTPServer((host, port), FixtureHandler)
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = start_fixture(args.host, args.port)
    print(f"Mock router listening on http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
