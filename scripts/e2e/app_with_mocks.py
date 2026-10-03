"""The app, wired to the mock services instead of Resend and Telegram -- for local end-to-end tests only.

    MOCK_URL=http://127.0.0.1:5099 gunicorn -w 1 -b 127.0.0.1:5051 --chdir <repo> --pythonpath <repo>,<repo>/scripts/e2e 'app_with_mocks:app'

It only swaps the two service addresses (mailer.RESEND_API_URL and telegram_notify.TELEGRAM_API_BASE); the app's own code is
unchanged. It refuses to start unless the mock is on this machine, so it can never be pointed at anything real by accident."""

import os
from urllib.parse import urlsplit

MOCK_URL = os.environ.get("MOCK_URL", "")
if urlsplit(MOCK_URL).hostname not in ("127.0.0.1", "localhost"):
    raise SystemExit("MOCK_URL must be a loopback address such as http://127.0.0.1:5099")

# Fake credentials so the app believes mail and Telegram are configured; they are useless anywhere but the mock.
os.environ.update(
    RESEND_API_KEY="mock-key",
    RESEND_FROM_EMAIL="orders@mock.test",
    RESEND_FROM_NAME="UniResto (mock)",
    TELEGRAM_BOT_TOKEN="000000:mock",
    TELEGRAM_CHAT_ID="1",
    PUBLIC_BASE_URL="http://127.0.0.1:5051",
)
os.environ.setdefault("ADMIN_TOKEN", "localtest-admin-token")
for key in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY"):
    os.environ[key] = ""  # push is not mocked here (it is covered by unit tests with an injected sender)

from orderability_engine import mailer, telegram_notify  # noqa: E402

mailer.RESEND_API_URL = f"{MOCK_URL}/emails"
telegram_notify.TELEGRAM_API_BASE = MOCK_URL

from app import create_app  # noqa: E402

app = create_app()
