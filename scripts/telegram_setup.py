#!/usr/bin/env python3
"""One-time (safe to repeat) setup of the bot's "📊 Stats" button.

  1. tells Telegram to POST the bot's incoming messages to
     <base url>/telegram/webhook (with the secret the app checks), and
  2. sends the admin chat a message that installs the persistent button.

Run it on the server, where the bot token lives (loaded from the app's .env):

    cd /root/uniresto && .venv/bin/python scripts/telegram_setup.py

Optional argument: the public base URL (default https://resto.unilu.space,
or $PUBLIC_BASE_URL).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from orderability_engine.telegram_notify import is_configured, send_admin_text, set_webhook  # noqa: E402


def main(argv: list[str]) -> int:
    if not is_configured():
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set -- nothing to do.")
        return 1
    base = (argv[1] if len(argv) > 1 else os.environ.get("PUBLIC_BASE_URL", "https://resto.unilu.space")).rstrip("/")
    ok, error = set_webhook(f"{base}/telegram/webhook")
    print("webhook:", "set" if ok else f"FAILED ({error})")
    if not ok:
        return 1
    ok, error = send_admin_text(
        "📊 The Stats button is on. Tap it (or send /stats) any time to get today's stats and the last 2 days, "
        "with every QR source.",
        with_stats_button=True,
    )
    print("button message:", "sent" if ok else f"FAILED ({error})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
