"""Admin notification via Telegram (Part 30) -- pings the admin the
moment a new order is placed, so they know to go place the matching
reservation in real Restopolis. Entirely optional and best-effort, same
contract as orderability_engine/mailer.py: never raises, never blocks
order creation, returns (sent: bool, error: str | None).

Credentials come ONLY from environment variables (TELEGRAM_BOT_TOKEN/
TELEGRAM_CHAT_ID), same git-ignored .env / systemd EnvironmentFile
pattern as mailer.py's SMTP_USER/SMTP_PASSWORD -- never hardcoded here.
TELEGRAM_CHAT_ID is the admin's own chat with the bot; a bot can't
message anyone who hasn't first messaged it (Telegram Bot API
requirement), so this has to be captured once during setup (e.g. via
GET https://api.telegram.org/bot<token>/getUpdates after the admin
sends the bot any message) -- there's no way to derive it otherwise.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("uniresto.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org"


def _bot_config() -> dict | None:
    """Reads config fresh from the environment on every call (not cached
    at import time) -- same reasoning as mailer.py's _smtp_config()."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return None
    return {"token": token, "chat_id": chat_id}


def is_configured() -> bool:
    return _bot_config() is not None


def _format_order_message(order: dict, admin_url: str | None) -> str:
    """Plain text (Telegram's default parse mode) built ONLY from the
    order's own already-computed, server-verified fields -- same "never
    invent data" rule as mailer.py's own message-building functions."""
    lines = [
        f"New order #{order['id']} -- needs a real Restopolis reservation",
        "",
        f"Restaurant: {order['restaurant_name']}",
        f"Date: {order['order_date']}",
        "",
        "Items:",
    ]
    for item in order["items"]:
        lines.append(f"  - {item['name']} x{item['quantity']}")

    formula = order["totals"].get("formula") or {}
    if formula.get("total") is not None:
        lines.append("")
        lines.append(f"Approximate price (our own estimate): €{formula['total']:.2f}")

    if order.get("delivery_location"):
        lines.append(f"Delivery location: {order['delivery_location']}")
    if order.get("customer_email"):
        lines.append(f"Customer email: {order['customer_email']}")

    if admin_url:
        lines.append("")
        lines.append(f"Record the real price here: {admin_url}")

    return "\n".join(lines)


def send_admin_notification(order: dict, admin_url: str | None = None) -> tuple[bool, str | None]:
    """Best-effort send. Returns (sent, error) -- `sent` is False (never
    raises) for both "not configured" and any real API/network failure."""
    config = _bot_config()
    if config is None:
        return False, "Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset)"

    text = _format_order_message(order, admin_url)
    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{config['token']}/sendMessage",
            json={"chat_id": config["chat_id"], "text": text},
            timeout=10,
        )
        body = resp.json()
        if not body.get("ok"):
            error = body.get("description") or f"HTTP {resp.status_code}"
            logger.warning("[TELEGRAM] failed to notify admin about order #%s: %s", order.get("id"), error)
            return False, error
        return True, None
    except Exception as exc:  # noqa: BLE001 -- any network/API failure must degrade gracefully, not crash the request
        logger.warning("[TELEGRAM] failed to notify admin about order #%s: %s", order.get("id"), exc)
        return False, str(exc)
