#!/usr/bin/env python3
"""Local stand-ins for the two outside services the app talks to, so a full order can be tested end to end
without sending anything real: Resend (email) and Telegram (the admin bot).

    python scripts/e2e/mock_services.py            # listens on 127.0.0.1:5099

Every request the app makes is kept in memory and can be read back:
    GET  /__outbox?kind=email|telegram     what was "sent", oldest first
    POST /__reset                          forget everything
    POST /__fail?on=1                      make email sending answer HTTP 500 (and ?on=0 to stop), to test that a
                                           failing mail never breaks an order
Resend's POST /emails and Telegram's POST /bot<token>/<method> answer like the real services.
Binds to loopback only."""

from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

OUTBOX: list[dict] = []
STATE = {"fail_email": False}
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _json(self, code: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {"_raw": raw.decode("utf-8", "replace")}

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/__outbox":
            kind = parse_qs(parts.query).get("kind", [None])[0]
            with LOCK:
                self._json(200, [m for m in OUTBOX if kind in (None, m["kind"])])
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        parts = urlsplit(self.path)
        body = self._body()
        if parts.path == "/__reset":
            with LOCK:
                OUTBOX.clear()
                STATE["fail_email"] = False
            return self._json(200, {"reset": True})
        if parts.path == "/__fail":
            STATE["fail_email"] = parse_qs(parts.query).get("on", ["1"])[0] == "1"
            return self._json(200, STATE)
        if parts.path == "/emails":
            if STATE["fail_email"]:
                return self._json(500, {"message": "mock: email sending is switched off"})
            to = body.get("to") or []
            with LOCK:
                OUTBOX.append({"kind": "email", "to": to[0] if to else None, "subject": body.get("subject"), "text": body.get("text"), "html": body.get("html")})
            return self._json(200, {"id": f"mock-{len(OUTBOX)}"})
        match = re.fullmatch(r"/bot[^/]+/(\w+)", parts.path)
        if match:
            with LOCK:
                OUTBOX.append({"kind": "telegram", "method": match.group(1), "text": body.get("text") or body.get("caption"), "body": body})
            return self._json(200, {"ok": True, "result": {"message_id": len(OUTBOX)}})
        self._json(404, {"error": "not found"})


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5099
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"mock services on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
