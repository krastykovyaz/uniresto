"""Luni reward points (Part 87/90) -- keyed by a student's verified
University email, the only stable identity this "no accounts" app has
(see verified_emails.py's own docstring for why that's the identity of
choice elsewhere too).

Every point is granted through award_once(), never a bare add_points()
call from app.py -- each real-world action that earns Luni (verifying a
University email, adding a communication email/phone, placing an order,
completing a delivery, an approved dish photo) is idempotent per its own
`action` key, so a retried request, a toggled mark-delivered/mark-not-
delivered, or re-saving the same phone number twice can never double-pay
it. One-time actions (university_email_verified, communication_email_
added, phone_number_added) use a bare action name -- at most once ever,
per email. Repeatable actions (an order, a delivery, an approved photo, a penalty)
fold the specific order/pending id into the action string itself (e.g.
"order_placed:42"), so THAT specific order/delivery/photo still only
ever pays out once, while a DIFFERENT order/delivery/photo pays again."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from orderability_engine.identity import canonical_identity

# Point values per rule (the whole rule set, as given): kept here, not
# scattered as magic numbers through app.py, so the schedule is defined
# in exactly one place. Action names double as award_once()'s dedup key
# for the three one-time ones; the three repeatable ones below always
# have a specific order/pending id folded into the actual key app.py
# builds (e.g. f"{ORDER_PLACED}:{order_id}").
UNIVERSITY_EMAIL_VERIFIED = "university_email_verified"
COMMUNICATION_EMAIL_ADDED = "communication_email_added"
PHONE_NUMBER_ADDED = "phone_number_added"
ORDER_PLACED = "order_placed"
DELIVERY_COMPLETED = "delivery_completed"
DISH_PHOTO_APPROVED = "dish_photo_approved"
# A shared menu link that somebody else opened: a tenth of a Luni to the sharer for each different person, at most
# SHARE_OPEN_DAILY_CAP Luni a day. The action key folds the opener's anonymous id in, so one person opening the
# link (or any other link of the same sharer) again pays nothing.
SHARE_OPENED = "share_opened"
SHARE_OPEN_POINTS = 0.1
SHARE_OPEN_DAILY_CAP = 1.0
# Penalties (negative points), applied once per order by app.py's
# _apply_expired_order_penalties(): a customer who left a claimed order
# unconfirmed, and a courier who held a confirmed order and never picked
# it up. Keyed per order id like every repeatable award, so each order
# can cost each side at most one Luni.
ORDER_NOT_CONFIRMED = "order_not_confirmed"
COURIER_NO_SHOW = "courier_no_show"

REWARD_POINTS = {
    UNIVERSITY_EMAIL_VERIFIED: 3,
    COMMUNICATION_EMAIL_ADDED: 1,
    PHONE_NUMBER_ADDED: 1,
    ORDER_PLACED: 1,
    DELIVERY_COMPLETED: 1,
    DISH_PHOTO_APPROVED: 1,
    ORDER_NOT_CONFIRMED: -1,
    COURIER_NO_SHOW: -1,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS rewards (
    email TEXT PRIMARY KEY,
    points INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reward_awards (
    email TEXT NOT NULL,
    action TEXT NOT NULL,
    points INTEGER NOT NULL,
    awarded_at TEXT NOT NULL,
    PRIMARY KEY (email, action)
);
-- One personal share code per verified person (never the address itself: the code travels in links).
CREATE TABLE IF NOT EXISTS share_refs (
    code TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    visitor_id TEXT,
    created_at TEXT NOT NULL
);
-- A contact detail (a phone number, a communication email) that already
-- paid out, and to whom. One row per (action, normalised value): the same
-- number or address can never earn Luni twice, whichever identity presents it.
CREATE TABLE IF NOT EXISTS reward_claim_values (
    action TEXT NOT NULL,
    value_key TEXT NOT NULL,
    email TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    PRIMARY KEY (action, value_key)
);
"""

# Luni can be a tenth (a shared link that got opened). Balances and awards keep whole Luni in `points` and the
# leftover tenths (0..9) in `tenths`, so the whole-Luni numbers written before this existed stay exactly as they were.
_MIGRATIONS = (
    ("rewards", "tenths", "ALTER TABLE rewards ADD COLUMN tenths INTEGER NOT NULL DEFAULT 0"),
    ("reward_awards", "tenths", "ALTER TABLE reward_awards ADD COLUMN tenths INTEGER NOT NULL DEFAULT 0"),
)


def _tenths(points: float) -> int:
    """Luni as a whole number of tenths (0.1 -> 1), immune to float noise."""
    return int(round(points * 10))


def _split(tenths: int) -> tuple[int, int]:
    """Tenths -> (whole, leftover) with the leftover carrying the sign of the amount, e.g. -10 -> (-1, 0)."""
    whole = int(tenths / 10)
    return whole, tenths - whole * 10


def _luni(whole: int, tenths: int) -> int | float:
    """A balance as the number clients show: an int while it is whole, one decimal otherwise."""
    return whole if tenths == 0 else round(whole + tenths / 10, 1)


# claim_value() outcomes
CLAIM_AWARDED = "awarded"
CLAIM_ALREADY_AWARDED = "already_awarded"
CLAIM_VALUE_ALREADY_USED = "value_already_used"


class RewardStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            for table, column, statement in _MIGRATIONS:
                if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}:
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError as exc:  # another worker got there first
                        if "duplicate column name" not in str(exc):
                            raise

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """One transaction per `with` block, and the connection actually
        CLOSED afterwards -- sqlite3.Connection's own context manager only
        commits/rolls back, so the bare `with sqlite3.connect(...)` this
        replaces leaked a file handle on every call until GC got to it."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get_points(self, email: str) -> int | float:
        email = canonical_identity(email)
        with self._connect() as conn:
            row = conn.execute("SELECT points, tenths FROM rewards WHERE email = ?", (email,)).fetchone()
        return _luni(*row) if row else 0

    @staticmethod
    def _add_points(conn: sqlite3.Connection, email: str, delta: float) -> int | float:
        """A balance never drops below 0 -- a penalty on an empty balance
        costs nothing more than it can take."""
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR IGNORE INTO rewards (email, points, updated_at) VALUES (?, 0, ?)", (email, now))
        points, tenths = conn.execute("SELECT points, tenths FROM rewards WHERE email = ?", (email,)).fetchone()
        total = max(0, points * 10 + tenths + _tenths(delta))
        conn.execute("UPDATE rewards SET points = ?, tenths = ?, updated_at = ? WHERE email = ?", (total // 10, total % 10, now, email))
        return _luni(total // 10, total % 10)

    def add_points(self, email: str, delta: float) -> int | float:
        """Adds `delta` (may be negative) to email's balance, creating
        the row at 0 first if this is their first-ever change. Returns
        the new total. Test/maintenance helper -- app.py should never
        call this directly (see module docstring), only award_once()."""
        with self._connect() as conn:
            return self._add_points(conn, canonical_identity(email), delta)

    def award_once(self, email: str, action: str, points: float) -> bool:
        """Credits `points` to `email` for `action`, but only the FIRST
        time this exact (email, action) pair is ever seen -- a second
        call with the same pair is a silent no-op (returns False), so
        callers never need their own "did I already pay this out"
        bookkeeping. Returns True iff this call actually just paid it.
        The dedup row and the balance change commit in ONE transaction,
        so a crash between them can never record an award that was
        never paid (or pay one that was never recorded).

        `email` is folded through canonical_identity() first, so
        "name+x@uni.lu" and "name@student.uni.lu" all pay -- and read
        back -- as the one person they are."""
        email = canonical_identity(email)
        with self._connect() as conn:
            whole, leftover = _split(_tenths(points))
            cur = conn.execute(
                "INSERT OR IGNORE INTO reward_awards (email, action, points, tenths, awarded_at) VALUES (?, ?, ?, ?, ?)",
                (email, action, whole, leftover, datetime.now(timezone.utc).isoformat()),
            )
            if cur.rowcount == 0:
                return False
            self._add_points(conn, email, points)
            return True

    def award_once_capped(self, email: str, action: str, points: float, *, prefix: str, cap: float, since: datetime) -> bool:
        """award_once(), but refused once this person has already earned `cap` Luni from actions starting with
        `prefix` since `since` (e.g. today's midnight). The check and the payment share one transaction."""
        email = canonical_identity(email)
        with self._connect() as conn:
            earned = conn.execute(
                "SELECT COALESCE(SUM(points * 10 + tenths), 0) FROM reward_awards WHERE email = ? AND action LIKE ? AND awarded_at >= ?",
                (email, prefix.replace("%", "") + "%", since.astimezone(timezone.utc).isoformat()),
            ).fetchone()[0]
            if earned + _tenths(points) > _tenths(cap):
                return False
            whole, leftover = _split(_tenths(points))
            cur = conn.execute(
                "INSERT OR IGNORE INTO reward_awards (email, action, points, tenths, awarded_at) VALUES (?, ?, ?, ?, ?)",
                (email, action, whole, leftover, datetime.now(timezone.utc).isoformat()),
            )
            if cur.rowcount == 0:
                return False
            self._add_points(conn, email, points)
            return True

    def share_code(self, email: str, visitor_id: str | None = None) -> str:
        """The person's personal share code, made on first use and the same afterwards. It stands in for the address
        inside shared links; `visitor_id` is their browser's anonymous id, kept so opening their own link there pays nothing."""
        import secrets

        email = canonical_identity(email)
        with self._connect() as conn:
            row = conn.execute("SELECT code FROM share_refs WHERE email = ?", (email,)).fetchone()
            if row:
                if visitor_id:
                    conn.execute("UPDATE share_refs SET visitor_id = ? WHERE email = ?", (visitor_id, email))
                return row[0]
            code = secrets.token_urlsafe(8)
            conn.execute(
                "INSERT INTO share_refs (code, email, visitor_id, created_at) VALUES (?, ?, ?, ?)",
                (code, email, visitor_id, datetime.now(timezone.utc).isoformat()),
            )
            return code

    def share_owner(self, code: str) -> tuple[str, str | None] | None:
        """(email, visitor_id) behind a share code, or None for a code nobody was given."""
        with self._connect() as conn:
            row = conn.execute("SELECT email, visitor_id FROM share_refs WHERE code = ?", (code,)).fetchone()
        return (row[0], row[1]) if row else None

    def claim_value(self, email: str, action: str, value_key: str, points: int) -> str:
        """award_once() for an action tied to a contact detail (a phone
        number, a communication email): pays only if this identity hasn't
        earned `action` yet AND `value_key` -- the NORMALISED value -- has
        never earned it for anyone. Returns CLAIM_AWARDED,
        CLAIM_ALREADY_AWARDED (this identity already has it) or
        CLAIM_VALUE_ALREADY_USED (someone else's number/address). One
        transaction, so the claim row and the payment stand or fall
        together."""
        email = canonical_identity(email)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM reward_awards WHERE email = ? AND action = ?", (email, action)).fetchone():
                return CLAIM_ALREADY_AWARDED
            cur = conn.execute(
                "INSERT OR IGNORE INTO reward_claim_values (action, value_key, email, claimed_at) VALUES (?, ?, ?, ?)",
                (action, value_key, email, now),
            )
            if cur.rowcount == 0:
                return CLAIM_VALUE_ALREADY_USED
            conn.execute(
                "INSERT INTO reward_awards (email, action, points, awarded_at) VALUES (?, ?, ?, ?)",
                (email, action, points, now),
            )
            self._add_points(conn, email, points)
            return CLAIM_AWARDED
