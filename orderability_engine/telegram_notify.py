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
    # Grouped by Restopolis's OWN raw category string (e.g. "02.
    # Viennoiseries"), in the order each category first appears in the
    # order -- the admin's own Restopolis app groups dishes by this same
    # real taxonomy, so this is the one thing that actually helps them
    # find the exact items, independent of whether restopolis_url below
    # opens the website or (via the app's own link handling, outside
    # this codebase's visibility/control) its native app instead.
    by_category: dict[str, list[dict]] = {}
    for item in order["items"]:
        by_category.setdefault(item.get("category") or "Other", []).append(item)
    for category, items in by_category.items():
        lines.append(f"  {category}:")
        for item in items:
            lines.append(f"    - {item['name']} x{item['quantity']}")
    if restopolis_url:
        lines.append(f"  (place these on Restopolis: {restopolis_url})")

    if order.get("customer_note"):
        lines.append("")
        lines.append(f"Note from customer: {order['customer_note']}")

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
    the real Restopolis WEBSITE (its BtnChangeRestaurant endpoint
    redirects straight to a Menu page with that restaurant already
    selected -- verified live via a real HTTP request, see app.py's
    construction of it). It only selects the restaurant, not the
    specific date or items: Restopolis's site has no URL parameter for
    either (see restopolis/client.py's module docstring -- date
    navigation is done via NextWeek/PreviousWeek requests that shift a
    server-side pointer, not a link Restopolis itself exposes).

    The admin's day-to-day Restopolis use may actually be its native
    mobile app rather than this website (confirmed by the admin, not
    guessed) -- whether tapping this link opens that app instead (e.g.
    via an iOS/Android universal link Restopolis's own app may or may
    not register for this domain) is entirely governed by that app,
    which this codebase has no visibility into or control over, so it's
    never assumed either way. What IS guaranteed to help regardless of
    which one opens: _format_order_message() below groups the item list
    by each item's own real Restopolis category (e.g. "02.
    Viennoiseries"), the same taxonomy both the website and the app
    group dishes by -- claiming this link jumps straight to the exact
    order would be a promise this app can't back with real data, so it
    doesn't."""
    text = _format_order_message(order, admin_url, restopolis_url)
    buttons = []
    if restopolis_url:
        buttons.append([{"text": "Open on Restopolis", "url": restopolis_url}])
    if mark_reviewing_url:
        buttons.append([{"text": "I'm checking this order", "url": mark_reviewing_url}])
    return _send_message(text, buttons, log_context=f"order #{order.get('id')}")


def _send_message(text: str, buttons: list | None, log_context: str) -> tuple[bool, str | None]:
    """Shared by send_admin_notification and send_feedback_notification
    below -- the one thing that actually differs between admin
    notifications is what text/buttons they send, not how the Telegram
    API call itself works or degrades on failure."""
    config = _bot_config()
    if config is None:
        return False, "Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset)"

    payload = {"chat_id": config["chat_id"], "text": text}
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
            logger.warning("[TELEGRAM] failed to notify admin about %s: %s", log_context, error)
            return False, error
        return True, None
    except Exception as exc:  # noqa: BLE001 -- any network/API failure must degrade gracefully, not crash the request
        logger.warning("[TELEGRAM] failed to notify admin about %s: %s", log_context, exc)
        return False, str(exc)


def send_feedback_notification(message: str, contact_email: str | None, admin_url: str | None = None) -> tuple[bool, str | None]:
    """Best-effort send, same contract as send_admin_notification above --
    pings the admin the moment free-text feedback (Part 71) comes in from
    the Profile screen. `admin_url`, when given, links to /admin/feedback
    so the admin can see the full inbox, not just this one message."""
    lines = ["New feedback", "", message]
    if contact_email:
        lines += ["", f"Contact: {contact_email}"]
    if admin_url:
        lines += ["", f"See all feedback: {admin_url}"]
    return _send_message("\n".join(lines), buttons=None, log_context="new feedback")


def send_order_claimed_notification(order: dict, admin_url: str | None = None) -> tuple[bool, str | None]:
    """Best-effort send, same contract as send_admin_notification above --
    pings the admin the moment a courier taps "Take this delivery" (Part
    75) on the Delivery screen. No courier IDENTITY to report (this app
    has no accounts -- see delivery_subscribers.py's own docstring), just
    that order #X now has someone on it."""
    lines = [
        f"Order #{order['id']} claimed for delivery -- {order['restaurant_name']}",
        f"Delivery location: {order.get('delivery_location') or 'Not given'}",
    ]
    if admin_url:
        lines += ["", f"See it: {admin_url}"]
    return _send_message("\n".join(lines), buttons=None, log_context=f"order #{order.get('id')} claimed")


def send_daily_report(counts: dict, report_date) -> tuple[bool, str | None]:
    """Best-effort send, same contract as every other function here --
    the evening admin report (Part 74; see daily_report.py). `counts` is
    exactly daily_report.compute_report_counts()'s own dict, real numbers
    off page_views.py/OrderStore, never estimated."""
    lines = [
        f"Daily report -- {report_date.isoformat()}",
        "",
        f"Opened the app: {counts['home']}",
        f"Viewed a menu: {counts['menu']}",
        f"Orders placed: {counts['orders']}",
        f"Opened deliveries: {counts['delivery']}",
    ]
    return _send_message("\n".join(lines), buttons=None, log_context=f"daily report {report_date}")
