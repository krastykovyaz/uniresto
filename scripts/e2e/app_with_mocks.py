"""The app, wired to the mock services instead of Resend and Telegram -- for local end-to-end tests only.

    MOCK_URL=http://127.0.0.1:5099 gunicorn -w 1 -b 127.0.0.1:5051 --pythonpath <repo>,<repo>/scripts/e2e 'app_with_mocks:app'

It only swaps the two service addresses (mailer.RESEND_API_URL and telegram_notify.TELEGRAM_API_BASE); the app's own code is
unchanged. It refuses to start unless the mock is on this machine, so it can never be pointed at anything real by accident.

Its data never touches a real app's. The app opens every database (orders.db, orderability.db, the verification stores)
and og_cache/ relative to the working directory, so this launcher moves into a scratch data directory first:
E2E_DATA_DIR if set, otherwise a fresh temporary one (printed at start-up). It refuses a directory that is a code checkout
(app.py or .git inside) or one that already holds data it did not create itself (no .uniresto-e2e marker), so it can
never write test orders, Luni or verified emails into a live database, whatever directory it was started from.

Verification codes are fixed (E2E_FIXED_CODE, default 123456), so a hand tester needs no inbox.

The daily-report scheduler is off: it would send the 20:00 report to the mock. The menu-refresh scheduler stays on,
because the app never fetches menus on a request -- it fetches the public Restopolis pages into the scratch
orderability.db, as a real start-up does. Dish photos are still served from the checkout's static/dish_photos."""

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

MOCK_URL = os.environ.get("MOCK_URL", "")
if urlsplit(MOCK_URL).hostname not in ("127.0.0.1", "localhost"):
    raise SystemExit("MOCK_URL must be a loopback address such as http://127.0.0.1:5099")

MARKER = ".uniresto-e2e"


def _scratch_data_dir() -> Path:
    wanted = os.environ.get("E2E_DATA_DIR")
    data_dir = Path(wanted).resolve() if wanted else Path(tempfile.mkdtemp(prefix="uniresto-e2e-")).resolve()
    if (data_dir / "app.py").exists() or (data_dir / ".git").exists():
        raise SystemExit(f"E2E_DATA_DIR {data_dir} is a code checkout; point it at a scratch directory instead")
    data_dir.mkdir(parents=True, exist_ok=True)
    if any(data_dir.iterdir()) and not (data_dir / MARKER).exists():
        raise SystemExit(f"E2E_DATA_DIR {data_dir} already holds data this launcher did not create; refusing to use it")
    (data_dir / MARKER).touch()
    return data_dir


DATA_DIR = _scratch_data_dir()
os.chdir(DATA_DIR)
print(f"[e2e] app data in {DATA_DIR}", file=sys.stderr, flush=True)

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
for key in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT"):
    os.environ[key] = ""  # push is not mocked here (it is covered by unit tests with an injected sender)

from orderability_engine import mailer, telegram_notify  # noqa: E402

mailer.RESEND_API_URL = f"{MOCK_URL}/emails"
telegram_notify.TELEGRAM_API_BASE = MOCK_URL

import app as app_module  # noqa: E402
from app import create_app  # noqa: E402

# Every verification code is the same, so someone trying the app by hand never has to wait on an inbox
# (the code is still "emailed" to the mock like any other, which is how run_e2e.py reads it). The signing
# key and the verified addresses live in the scratch data dir, so reusing E2E_DATA_DIR keeps people verified
# across restarts.
FIXED_CODE = os.environ.get("E2E_FIXED_CODE", "123456")
app_module.generate_verification_code = lambda: FIXED_CODE

app = create_app(enable_daily_report_scheduler=False)
