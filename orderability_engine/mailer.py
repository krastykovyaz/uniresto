"""Order confirmation emails -- OUR OWN notification, not a Restopolis
feature (Restopolis has no customer-email concept at all; see README.md
Part 23). Entirely optional: an order still succeeds with no email sent
whenever either the customer left the email field blank or SMTP simply
isn't configured on this server (no real secrets are ever hardcoded --
see the module-level env vars below, read fresh on every send rather
than cached at import time, so an admin can fix a typo in .env and
restart the service without a code change).

Never blocks or fails order creation: `send_order_confirmation` always
returns a (sent: bool, error: str | None) pair and the caller (app.py)
is expected to log the failure and continue -- a flaky mail server must
never turn a successful order into a 500.

Credentials come ONLY from environment variables (SMTP_USER/
SMTP_PASSWORD), typically via a git-ignored .env file loaded by
python-dotenv at app startup (see app.py) or a systemd EnvironmentFile
in production -- never committed, never hardcoded here.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("uniresto.mailer")

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587


def _smtp_config() -> dict | None:
    """Reads config fresh from the environment on every call (not cached
    at import time) so a corrected .env only needs a process restart, not
    a code change. Returns None if the two required secrets aren't set --
    that's the normal "email not configured yet" state, not an error."""
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        return None
    return {
        "host": os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST),
        "port": int(os.environ.get("SMTP_PORT", DEFAULT_SMTP_PORT)),
        "user": user,
        "password": password,
        "from_name": os.environ.get("SMTP_FROM_NAME", "UniResto"),
    }


def is_configured() -> bool:
    return _smtp_config() is not None


def _format_order_text(order: dict) -> str:
    """Plain-text body built ONLY from the order's own already-computed,
    server-verified fields (order['items']/['totals']) -- never a second
    guess at price/weight/name, matching this whole project's standing
    "never invent data" rule."""
    lines = [
        f"Restaurant: {order['restaurant_name']}",
        f"Date: {order['order_date']}",
        "",
        "Items:",
    ]
    for item in order["items"]:
        price = f"€{item['line_price']:.2f}" if item.get("line_price") is not None else "price not available"
        lines.append(f"  - {item['name']} x{item['quantity']} ({price})")

    formula = order["totals"].get("formula") or {}
    if formula.get("total") is not None:
        lines.append("")
        lines.append(f"Total: €{formula['total']:.2f}")

    if order.get("delivery_location"):
        lines.append("")
        lines.append(f"Delivery location: {order['delivery_location']}")

    lines.append("")
    lines.append(f"Order #{order['id']} -- confirmed, no payment collected (see README.md Part 3 scope).")
    return "\n".join(lines)


def send_order_confirmation(to_email: str, order: dict) -> tuple[bool, str | None]:
    """Best-effort send. Returns (sent, error) -- `sent` is False (never
    raises) for both "not configured" and any real SMTP failure, so
    app.py can log either case without special-casing them."""
    config = _smtp_config()
    if config is None:
        return False, "SMTP not configured (SMTP_USER/SMTP_PASSWORD unset)"

    msg = EmailMessage()
    msg["Subject"] = f"UniResto order confirmed -- {order['restaurant_name']}"
    msg["From"] = f"{config['from_name']} <{config['user']}>"
    msg["To"] = to_email
    msg.set_content(_format_order_text(order))

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as smtp:
            smtp.starttls()
            smtp.login(config["user"], config["password"])
            smtp.send_message(msg)
        return True, None
    except Exception as exc:  # noqa: BLE001 -- any SMTP/network failure must degrade gracefully, not crash the request
        logger.warning("[MAIL] failed to send order confirmation to %s: %s", to_email, exc)
        return False, str(exc)
