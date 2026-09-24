"""Order confirmation + email-verification messages -- OUR OWN
notifications, not a Restopolis feature (Restopolis has no
customer-email concept at all; see README.md Part 23/27). Entirely
optional: an order still succeeds with no email sent whenever either
the customer left the email field blank or Resend simply isn't
configured on this server (no real secrets are ever hardcoded -- see
the module-level env vars below, read fresh on every send rather than
cached at import time, so an admin can fix a typo in .env and restart
the service without a code change).

Never blocks or fails the caller: both `send_order_confirmation` and
`send_verification_code` always return a (sent: bool, error: str | None)
pair and the caller (app.py) is expected to log the failure and
continue -- a flaky mail API must never turn a successful order, or a
verification-code request, into a 500.

Credentials come ONLY from environment variables (RESEND_API_KEY),
typically via a git-ignored .env file loaded by python-dotenv at app
startup (see app.py) or a systemd EnvironmentFile in production --
never committed, never hardcoded here.

Sent via Resend's HTTPS API (https://api.resend.com/emails) rather than
raw SMTP -- see README.md Part 31: the original Gmail-SMTP sender had no
domain-level SPF/DKIM/DMARC alignment, so campus mail servers
(uni.lu/student.uni.lu) were silently discarding messages with no
bounce. Resend's `RESEND_FROM_EMAIL` lives on unilu.space, a domain
with verified DKIM/SPF/DMARC records specifically for this purpose.

Both message types are sent as MULTIPART (a plain-text part alongside a
lightly-branded HTML part matching the app's own colors) with a short,
plain, non-clickbait subject line and no links at all in the
verification-code message -- one real concrete lever against landing in
spam, not a guarantee.
"""

from __future__ import annotations

import logging
import os
import secrets

import requests

logger = logging.getLogger("uniresto.mailer")

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_FROM_EMAIL = "noreply@unilu.space"
DEFAULT_FROM_NAME = "UniResto"
# Resend's own domain-verification endpoint sits behind Cloudflare, which
# blocks the default python-requests/urllib user-agent string as a bot
# (HTTP 403, Cloudflare error 1010) -- a plain browser-shaped one avoids that.
_USER_AGENT = "Mozilla/5.0 (compatible; UniResto-Mailer/1.0)"

# Matches static/app.css's own --color-primary/--color-bg/--color-text,
# so the email at least LOOKS like it came from the same app, not a
# generic transactional-mail template.
_BRAND_GREEN = "#1aa860"
_BRAND_BG = "#f7f8fa"
_BRAND_TEXT = "#14171a"


def _mail_config() -> dict | None:
    """Reads config fresh from the environment on every call (not cached
    at import time) so a corrected .env only needs a process restart, not
    a code change. Returns None if the API key isn't set -- that's the
    normal "email not configured yet" state, not an error."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "from_email": os.environ.get("RESEND_FROM_EMAIL", DEFAULT_FROM_EMAIL),
        "from_name": os.environ.get("RESEND_FROM_NAME", DEFAULT_FROM_NAME),
    }


def is_configured() -> bool:
    return _mail_config() is not None


def _html_shell(preheader: str, body_html: str, config: dict) -> str:
    """Wraps `body_html` in the same minimal branded shell for every
    message type -- a green header bar (--color-primary), light page
    background (--color-bg), one card, one footer. `preheader` is the
    hidden preview text most mail clients show next to the subject
    line -- kept short and genuinely descriptive (not stuffed with
    keywords), another small, honest anti-spam signal."""
    return f"""\
<!doctype html>
<html>
<body style="margin:0;padding:0;background:{_BRAND_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_BRAND_BG};padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;">
        <tr><td style="background:{_BRAND_GREEN};padding:20px 28px;">
          <span style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:0.02em;">UniResto</span>
          <span style="color:#ffffff;font-size:12px;opacity:0.85;display:block;margin-top:2px;">Campus Kirchberg</span>
        </td></tr>
        <tr><td style="padding:28px;color:{_BRAND_TEXT};font-size:15px;line-height:1.55;">
          {body_html}
        </td></tr>
        <tr><td style="padding:16px 28px 24px;color:#6b7280;font-size:12px;line-height:1.5;border-top:1px solid #eef0f2;">
          This is an automated message from UniResto, a student project for University of Luxembourg Campus Kirchberg.
          No payment is taken and no order is placed with Restopolis or delivered.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send(to_email: str, subject: str, text_body: str, html_body: str) -> tuple[bool, str | None]:
    config = _mail_config()
    if config is None:
        return False, "Email not configured (RESEND_API_KEY unset)"

    payload = {
        "from": f"{config['from_name']} <{config['from_email']}>",
        "to": [to_email],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }

    try:
        resp = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {config['api_key']}", "User-Agent": _USER_AGENT},
            timeout=10,
        )
        if resp.status_code >= 400:
            error = resp.json().get("message") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            error = error or f"HTTP {resp.status_code}"
            logger.warning("[MAIL] failed to send %r to %s: %s", subject, to_email, error)
            return False, error
        return True, None
    except Exception as exc:  # noqa: BLE001 -- any API/network failure must degrade gracefully, not crash the request
        logger.warning("[MAIL] failed to send %r to %s: %s", subject, to_email, exc)
        return False, str(exc)


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


def _format_order_html(order: dict) -> str:
    rows = []
    for item in order["items"]:
        price = f"€{item['line_price']:.2f}" if item.get("line_price") is not None else "price not available"
        rows.append(
            f'<tr><td style="padding:6px 0;">{item["name"]} × {item["quantity"]}</td>'
            f'<td style="padding:6px 0;text-align:right;color:#6b7280;">{price}</td></tr>'
        )

    formula = order["totals"].get("formula") or {}
    total_row = ""
    if formula.get("total") is not None:
        total_row = (
            '<tr><td style="padding:10px 0 0;font-weight:700;border-top:1px solid #eef0f2;">Total</td>'
            f'<td style="padding:10px 0 0;text-align:right;font-weight:700;border-top:1px solid #eef0f2;">€{formula["total"]:.2f}</td></tr>'
        )

    delivery = (
        f'<p style="margin:16px 0 0;color:#6b7280;">Delivery location: {order["delivery_location"]}</p>'
        if order.get("delivery_location")
        else ""
    )

    return f"""\
        <p style="margin:0 0 4px;font-size:17px;font-weight:700;">Order confirmed</p>
        <p style="margin:0 0 20px;color:#6b7280;">{order['restaurant_name']} &middot; {order['order_date']}</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
          {''.join(rows)}
          {total_row}
        </table>
        {delivery}
        <p style="margin:20px 0 0;color:#6b7280;font-size:13px;">Order #{order['id']}</p>"""


def send_order_confirmation(to_email: str, order: dict) -> tuple[bool, str | None]:
    """Best-effort send. Returns (sent, error) -- `sent` is False (never
    raises) for both "not configured" and any real SMTP failure, so
    app.py can log either case without special-casing them."""
    config = _mail_config()
    if config is None:
        return False, "Email not configured (RESEND_API_KEY unset)"
    subject = f"UniResto order confirmed -- {order['restaurant_name']}"
    text_body = _format_order_text(order)
    html_body = _html_shell(f"Your order at {order['restaurant_name']} is confirmed.", _format_order_html(order), config)
    return _send(to_email, subject, text_body, html_body)


def generate_verification_code() -> str:
    """A 6-digit numeric code, zero-padded -- generated with `secrets`
    (cryptographically random), not `random`, since this gates writing a
    real address into the app the same way any confirmation code would."""
    return f"{secrets.randbelow(1_000_000):06d}"


def send_verification_code(to_email: str, code: str) -> tuple[bool, str | None]:
    """Best-effort send, same (sent, error) contract as
    send_order_confirmation. The code itself is generated by the caller
    (app.py, which also owns matching it back against what the user
    types in -- see orderability_engine/email_verification.py) so this
    function stays a pure "format and send" step, consistent with how
    send_order_confirmation never computes the order it's asked to send."""
    config = _mail_config()
    if config is None:
        return False, "Email not configured (RESEND_API_KEY unset)"
    subject = "Your UniResto verification code"
    text_body = (
        f"Your UniResto verification code is: {code}\n\n"
        "Enter it in the app to confirm this email address. It expires in 10 minutes.\n\n"
        "If you didn't request this, you can ignore this email -- no account or order is affected."
    )
    body_html = f"""\
        <p style="margin:0 0 4px;font-size:17px;font-weight:700;">Confirm your email</p>
        <p style="margin:0 0 20px;color:#6b7280;">Enter this code in the app to confirm this address.</p>
        <p style="margin:0 0 20px;text-align:center;">
          <span style="display:inline-block;padding:14px 22px;background:{_BRAND_BG};border-radius:10px;font-size:28px;font-weight:700;letter-spacing:0.3em;color:{_BRAND_TEXT};">{code}</span>
        </p>
        <p style="margin:0;color:#6b7280;font-size:13px;">This code expires in 10 minutes. If you didn't request it, you can ignore this email.</p>"""
    html_body = _html_shell(f"Your UniResto verification code is {code}.", body_html, config)
    return _send(to_email, subject, text_body, html_body)


def send_order_needs_confirmation(
    to_email: str, order: dict, real_price: float, confirm_url: str, cancel_url: str
) -> tuple[bool, str | None]:
    """Part 30: sent once an admin has actually placed the matching
    reservation in real Restopolis and recorded what it really charged
    (`real_price` -- a supplied FACT, never derived). Deliberately shows
    BOTH numbers side by side -- the approximate price the customer saw
    in the app (order['totals']['formula']['total'], OUR OWN course
    pricing, Part 18/26) and the real one -- rather than silently
    replacing one with the other, so a mismatch is visible, not hidden.
    `confirm_url`/`cancel_url` are one-time links (see
    OrderStore.confirm_order/cancel_order's token requirement) styled as
    real buttons -- the closest a plain email can get to an interactive
    widget, since no mail client runs the app's own JavaScript."""
    approx = (order["totals"].get("formula") or {}).get("total")
    approx_line = f"Approximate price shown in the app: €{approx:.2f}\n" if approx is not None else ""
    text_body = (
        f"Your order at {order['restaurant_name']} ({order['order_date']}) has been placed with Restopolis.\n\n"
        f"{approx_line}"
        f"Real price: €{real_price:.2f}\n\n"
        f"Confirm: {confirm_url}\n"
        f"Cancel: {cancel_url}\n\n"
        f"Order #{order['id']}. If you don't respond, the order stays unconfirmed."
    )

    approx_row = (
        f'<tr><td style="padding:4px 0;color:#6b7280;">Approximate price you saw</td>'
        f'<td style="padding:4px 0;text-align:right;color:#6b7280;">€{approx:.2f}</td></tr>'
        if approx is not None
        else ""
    )
    body_html = f"""\
        <p style="margin:0 0 4px;font-size:17px;font-weight:700;">Confirm your order's real price</p>
        <p style="margin:0 0 20px;color:#6b7280;">{order['restaurant_name']} &middot; {order['order_date']}</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;margin-bottom:20px;">
          {approx_row}
          <tr><td style="padding:6px 0 0;font-weight:700;">Real price (Restopolis)</td>
          <td style="padding:6px 0 0;text-align:right;font-weight:700;">€{real_price:.2f}</td></tr>
        </table>
        <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">
          <tr>
            <td style="padding:0 6px 0 0;width:50%;">
              <a href="{confirm_url}" style="display:block;text-align:center;background:{_BRAND_GREEN};color:#ffffff;text-decoration:none;font-weight:700;padding:14px 0;border-radius:10px;">Confirm</a>
            </td>
            <td style="padding:0 0 0 6px;width:50%;">
              <a href="{cancel_url}" style="display:block;text-align:center;background:#ffffff;color:{_BRAND_TEXT};text-decoration:none;font-weight:700;padding:14px 0;border-radius:10px;border:1px solid #e2e5e9;">Cancel</a>
            </td>
          </tr>
        </table>
        <p style="margin:20px 0 0;color:#6b7280;font-size:13px;">Order #{order['id']}. If you don't respond, the order stays unconfirmed.</p>"""

    config = _mail_config()
    if config is None:
        return False, "Email not configured (RESEND_API_KEY unset)"
    subject = f"Confirm your UniResto order -- {order['restaurant_name']}"
    html_body = _html_shell(f"Real price for order #{order['id']} is €{real_price:.2f} -- please confirm.", body_html, config)
    return _send(to_email, subject, text_body, html_body)
