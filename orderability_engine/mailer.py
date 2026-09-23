"""Order confirmation + email-verification messages -- OUR OWN
notifications, not a Restopolis feature (Restopolis has no
customer-email concept at all; see README.md Part 23/27). Entirely
optional: an order still succeeds with no email sent whenever either
the customer left the email field blank or SMTP simply isn't configured
on this server (no real secrets are ever hardcoded -- see the
module-level env vars below, read fresh on every send rather than
cached at import time, so an admin can fix a typo in .env and restart
the service without a code change).

Never blocks or fails the caller: both `send_order_confirmation` and
`send_verification_code` always return a (sent: bool, error: str | None)
pair and the caller (app.py) is expected to log the failure and
continue -- a flaky mail server must never turn a successful order, or
a verification-code request, into a 500.

Credentials come ONLY from environment variables (SMTP_USER/
SMTP_PASSWORD), typically via a git-ignored .env file loaded by
python-dotenv at app startup (see app.py) or a systemd EnvironmentFile
in production -- never committed, never hardcoded here.

Both message types are sent as MULTIPART (a plain-text part alongside a
lightly-branded HTML part matching the app's own colors) with a short,
plain, non-clickbait subject line and no links at all -- one real
concrete lever against landing in spam, not a guarantee. The bigger,
structural factor is entirely outside this code: SMTP_USER here is a
personal Gmail address, not a domain with its own SPF/DKIM/DMARC record
aligned to "UniResto", so campus mail servers (uni.lu/student.uni.lu)
may reasonably still flag it -- see README.md Part 27's "Verified live"
note and static/app.js's checkSpamFolder-labeled UI copy, which tells
the user to check their spam folder rather than pretending this is
solved by message content alone.
"""

from __future__ import annotations

import logging
import os
import secrets
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("uniresto.mailer")

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587

# Matches static/app.css's own --color-primary/--color-bg/--color-text,
# so the email at least LOOKS like it came from the same app, not a
# generic transactional-mail template.
_BRAND_GREEN = "#1aa860"
_BRAND_BG = "#f7f8fa"
_BRAND_TEXT = "#14171a"


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
    config = _smtp_config()
    if config is None:
        return False, "SMTP not configured (SMTP_USER/SMTP_PASSWORD unset)"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{config['from_name']} <{config['user']}>"
    msg["To"] = to_email
    msg.set_content(text_body)  # plain-text part first (multipart/alternative)
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as smtp:
            smtp.starttls()
            smtp.login(config["user"], config["password"])
            smtp.send_message(msg)
        return True, None
    except Exception as exc:  # noqa: BLE001 -- any SMTP/network failure must degrade gracefully, not crash the request
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
    config = _smtp_config()
    if config is None:
        return False, "SMTP not configured (SMTP_USER/SMTP_PASSWORD unset)"
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
    config = _smtp_config()
    if config is None:
        return False, "SMTP not configured (SMTP_USER/SMTP_PASSWORD unset)"
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
