"""Who is "the same person", for everything that limits or pays a person.

This app has no accounts: a person IS a verified email (see
verified_emails.py). That makes duplicates cheap unless the comparison is
smarter than string equality -- one mailbox can be several addresses:

- "name+anything@uni.lu" lands in the same inbox as "name@uni.lu", so every
  plus-tagged variant passes email verification as a "new" address;

canonical_identity() folds that together; the reward balances, the
per-day / per-date order limits and the courier-is-not-the-customer check
all compare on it. It can't see through genuinely different aliases
("first.last" vs "f.last") -- nothing here can -- but it closes the free,
unlimited ones.

uni.lu and student.uni.lu are deliberately NOT folded together: they are
different mailboxes on different domains, and the same local part there
can be two different people ("john.smith") -- merging them would let one
person's orders and Luni be limited by, or paid to, somebody else.

The same goes for the two contact details that earn Luni. A phone number or
communication email may pay out once EVER, across all identities, so
they're normalised (normalize_phone / normalize_contact_email) before being
remembered.
"""

from __future__ import annotations

_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
_LUXEMBOURG_PREFIX = "352"
MIN_PHONE_DIGITS = 6
MAX_PHONE_DIGITS = 15


def canonical_identity(email: str | None) -> str:
    """Lower-cased, plus-tag removed. Anything that isn't a plain local@domain comes back just lower-cased."""
    value = (email or "").strip().lower()
    if value.count("@") != 1:
        return value
    local, domain = value.split("@")
    local = local.split("+", 1)[0]
    return f"{local}@{domain}"


def normalize_contact_email(email: str | None) -> str:
    """canonical_identity() plus Gmail's own aliasing (dots in the local
    part are ignored, googlemail.com is gmail.com)."""
    value = canonical_identity(email)
    if value.count("@") != 1:
        return value
    local, domain = value.split("@")
    if domain in _GMAIL_DOMAINS:
        return f"{local.replace('.', '')}@gmail.com"
    return value


def normalize_phone(phone: str | None) -> str | None:
    """Digits only, international prefix ("+" / "00") and Luxembourg's 352
    country code dropped, so "+352 621 123 456", "00352621123456" and
    "621 123 456" are one number. None when it isn't a plausible number
    (6-15 digits, nothing but digits, spaces, "+", "-", "(" and ")")."""
    text = (phone or "").strip()
    if not text or any(ch not in "0123456789 +-()" for ch in text):
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not (MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS):
        return None
    if digits.startswith("00"):  # "00" is the international-call prefix, same as "+"
        digits = digits[2:]
    if digits.startswith(_LUXEMBOURG_PREFIX) and len(digits) - len(_LUXEMBOURG_PREFIX) >= MIN_PHONE_DIGITS:
        digits = digits[len(_LUXEMBOURG_PREFIX):]
    return digits
