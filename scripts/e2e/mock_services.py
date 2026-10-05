#!/usr/bin/env python3
"""Local stand-ins for the two outside services the app talks to, so a full order can be tested end to end
without sending anything real: Resend (email) and Telegram (the admin bot).

    python scripts/e2e/mock_services.py            # listens on 127.0.0.1:5099

Every request the app makes is kept in memory and can be read back:
    GET  /__outbox?kind=email|telegram     what was "sent", oldest first
    POST /__reset                          forget everything
    POST /__real_mail?on=0                 pause (and ?on=1 resume) the real sending to E2E_REAL_MAIL_TO, e.g. while
                                           seeding many orders under your own address
    POST /__fail?on=1                      make email sending answer HTTP 500 (and ?on=0 to stop), to test that a
                                           failing mail never breaks an order
Resend's POST /emails and Telegram's POST /bot<token>/<method> answer like the real services.
Binds to loopback only.

Optional, for trying the app by hand with a real inbox: set E2E_REAL_MAIL_TO to a comma-separated list of addresses
(your own). An email to one of THOSE addresses is also sent for real through Resend, using the mail settings in the
app's own .env (read here, never printed or stored); an email to anyone else is only recorded, as always. Telegram is
never forwarded."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

REAL_MAIL_TO = {a.strip().lower() for a in os.environ.get("E2E_REAL_MAIL_TO", "").split(",") if a.strip()}
ENV_FILE = os.environ.get("E2E_ENV_FILE", os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

OUTBOX: list[dict] = []
STATE = {"fail_email": False, "real_mail": True}
LOCK = threading.Lock()


def _real_mail_settings() -> dict | None:
    """The real Resend settings, from the app's .env (and the sender defaults the app itself uses), or None.
    Read on each use so nothing is kept around."""
    try:
        from dotenv import dotenv_values

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from orderability_engine.mailer import DEFAULT_FROM_EMAIL, DEFAULT_FROM_NAME

        values = dotenv_values(ENV_FILE)
    except Exception:  # noqa: BLE001
        return None
    if not values.get("RESEND_API_KEY"):
        return None
    sender = f"{values.get('RESEND_FROM_NAME') or DEFAULT_FROM_NAME} <{values.get('RESEND_FROM_EMAIL') or DEFAULT_FROM_EMAIL}>"
    return {"key": values["RESEND_API_KEY"], "from": sender}


def _forward_to_resend(body: dict) -> tuple[int, dict]:
    """Really sends this one email (the caller has already checked the recipient is on the allow-list)."""
    settings = _real_mail_settings()
    if settings is None:
        return 500, {"message": "E2E_REAL_MAIL_TO is set but the app's .env has no Resend settings"}
    payload = {**body, "from": settings["from"]}
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {settings['key']}", "Content-Type": "application/json", "User-Agent": "uniresto-preview/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"message": f"Resend answered HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return 500, {"message": f"could not reach Resend: {type(exc).__name__}"}


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
        if parts.path == "/__real_mail":
            STATE["real_mail"] = parse_qs(parts.query).get("on", ["1"])[0] == "1"
            return self._json(200, STATE)
        if parts.path == "/__fail":
            STATE["fail_email"] = parse_qs(parts.query).get("on", ["1"])[0] == "1"
            return self._json(200, STATE)
        if parts.path == "/emails":
            if STATE["fail_email"]:
                return self._json(500, {"message": "mock: email sending is switched off"})
            to = body.get("to") or []
            recipient = to[0] if to else None
            real = STATE["real_mail"] and bool(recipient) and recipient.strip().lower() in REAL_MAIL_TO
            status, answer = (_forward_to_resend(body) if real else (200, {"id": f"mock-{len(OUTBOX)}"}))
            with LOCK:
                OUTBOX.append({"kind": "email", "to": recipient, "subject": body.get("subject"), "text": body.get("text"), "html": body.get("html"), "sent_for_real": real and status < 300})
            return self._json(status, answer)
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
