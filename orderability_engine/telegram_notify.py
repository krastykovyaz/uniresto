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


def _format_order_message(order: dict, admin_url: str | None, restopolis_url: str | None) -> str:
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
    if restopolis_url:
        lines.append(f"  (place these on Restopolis: {restopolis_url})")

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


def send_admin_notification(
    order: dict,
    admin_url: str | None = None,
    mark_reviewing_url: str | None = None,
    restopolis_url: str | None = None,
) -> tuple[bool, str | None]:
    """Best-effort send. Returns (sent, error) -- `sent` is False (never
    raises) for both "not configured" and any real API/network failure.

    `mark_reviewing_url` (Part 37) and `restopolis_url` (Part 38), when
    given, are each attached as a tappable inline button -- plain URL
    buttons, not callback_query, so this needs no webhook/polling setup
    on our side at all: Telegram just opens the link when the admin taps
    it.

    `restopolis_url` deep-links straight to this order's RESTAURANT on
    the real Restopolis site (its BtnChangeRestaurant endpoint redirects
    straight to a Menu page with that restaurant already selected --
    verified live, see app.py's construction of it). It only selects the
    restaurant, not the specific date or items: Restopolis's site has no
    URL parameter for either (see restopolis/client.py's module
    docstring -- date navigation is done via NextWeek/PreviousWeek
    requests that shift a server-side pointer, not a link Restopolis
    itself exposes), so the admin still has to pick the right day and
    dishes once there, same as visiting Restopolis directly always
    required. Landing on the restaurant, one tap away, is the real
    improvement -- claiming this jumps straight to the exact order would
    be a UI promise this app can't back with real data."""
    config = _bot_config()
    if config is None:
        return False, "Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset)"

    text = _format_order_message(order, admin_url, restopolis_url)
    payload = {"chat_id": config["chat_id"], "text": text}
    buttons = []
    if restopolis_url:
        buttons.append([{"text": "Open on Restopolis", "url": restopolis_url}])
    if mark_reviewing_url:
        buttons.append([{"text": "I'm checking this order", "url": mark_reviewing_url}])
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{config['token']}/sendMessage",
            json=payload,
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
