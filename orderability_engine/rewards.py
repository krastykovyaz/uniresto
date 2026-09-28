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
per email. Repeatable actions (an order, a delivery, an approved photo)
fold the specific order/pending id into the action string itself (e.g.
"order_placed:42"), so THAT specific order/delivery/photo still only
ever pays out once, while a DIFFERENT order/delivery/photo pays again."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

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

REWARD_POINTS = {
    UNIVERSITY_EMAIL_VERIFIED: 3,
    COMMUNICATION_EMAIL_ADDED: 1,
    PHONE_NUMBER_ADDED: 1,
    ORDER_PLACED: 1,
    DELIVERY_COMPLETED: 1,
    DISH_PHOTO_APPROVED: 1,
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
"""


class RewardStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

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

    def get_points(self, email: str) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT points FROM rewards WHERE email = ?", (email,)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _add_points(conn: sqlite3.Connection, email: str, delta: int) -> int:
        conn.execute(
            """
            INSERT INTO rewards (email, points, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET points = points + excluded.points, updated_at = excluded.updated_at
            """,
            (email, delta, datetime.now(timezone.utc).isoformat()),
        )
        return conn.execute("SELECT points FROM rewards WHERE email = ?", (email,)).fetchone()[0]

    def add_points(self, email: str, delta: int) -> int:
        """Adds `delta` (may be negative) to email's balance, creating
        the row at 0 first if this is their first-ever change. Returns
        the new total. Test/maintenance helper -- app.py should never
        call this directly (see module docstring), only award_once()."""
        with self._connect() as conn:
            return self._add_points(conn, email, delta)

    def award_once(self, email: str, action: str, points: int) -> bool:
        """Credits `points` to `email` for `action`, but only the FIRST
        time this exact (email, action) pair is ever seen -- a second
        call with the same pair is a silent no-op (returns False), so
        callers never need their own "did I already pay this out"
        bookkeeping. Returns True iff this call actually just paid it.
        The dedup row and the balance change commit in ONE transaction,
        so a crash between them can never record an award that was
        never paid (or pay one that was never recorded)."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO reward_awards (email, action, points, awarded_at) VALUES (?, ?, ?, ?)",
                (email, action, points, datetime.now(timezone.utc).isoformat()),
            )
            if cur.rowcount == 0:
                return False
            self._add_points(conn, email, points)
            return True
