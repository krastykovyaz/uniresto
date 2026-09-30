import os
import socket
from pathlib import Path

import pytest

# app.py calls load_dotenv() at import time, which picks up the server's real
# .env (admin token, Resend key, Telegram bot) and made tests send real emails
# and Telegram messages. load_dotenv() never overrides a key that's already
# set, and every reader treats "" as unset -- so blanking them here, before
# any test module imports app, keeps the real values out of the test run.
# A test that needs one sets it itself with monkeypatch.setenv.
SECRET_ENV_KEYS = (
    "ADMIN_TOKEN",
    "PUBLIC_BASE_URL",
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
    "RESEND_FROM_NAME",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)
for _key in SECRET_ENV_KEYS:
    os.environ[_key] = ""


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Any connection off this machine fails the test instead of reaching
    Resend, Telegram or Restopolis. Tests that exercise those clients mock
    requests.post themselves, so they never get this far."""
    real_connect = socket.socket.connect

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if sock.family == socket.AF_UNIX or host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(sock, address)
        raise RuntimeError(f"tests must not open real network connections (tried {address!r})")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def altius_html() -> str:
    return (FIXTURES_DIR / "altius_week0.html").read_text(encoding="utf-8")


@pytest.fixture
def brasserie_johns_html() -> str:
    return (FIXTURES_DIR / "brasserie_johns_week0.html").read_text(encoding="utf-8")


@pytest.fixture
def altius_closed_week_html() -> str:
    return (FIXTURES_DIR / "altius_closed_week.html").read_text(encoding="utf-8")


@pytest.fixture
def altius_config():
    from restopolis.config import load_restaurants

    return load_restaurants()["UDL-CKB-ALTIUS"]


@pytest.fixture
def fixture_today():
    """The real-world date the live fixtures were captured on."""
    import datetime

    return datetime.date(2026, 9, 23)
