"""Registered delivery-notification recipients (Part 52+).

Deliberately NOT a real account system, matching this whole app's
minimal-auth ethos (see app.py's own note on ADMIN_TOKEN): no password,
no session, no login. Registering just proves the person can read mail
sent to that address (via the same email_verification.py code flow the
customer checkout email already uses -- see app.py's
/api/delivery/register/* routes) and persists it here so every future
order notifies it. There is no way to VIEW the Delivery screen's order
list gated behind this -- registering only controls whether an address
gets emailed, never who can look at the screen itself.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS delivery_subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""

# lang added after the original schema shipped -- see orders.py's own
# _MIGRATIONS for why this needs an explicit ALTER TABLE rather than just
# editing SCHEMA above. Whatever language the courier's OWN app happened
# to be in at the moment they registered (Part 72) -- not a profile
# setting kept in sync afterwards, so re-registering (e.g. after
# switching languages) is exactly how it gets updated; see add()'s
# ON CONFLICT clause below.
_MIGRATIONS = [
    ("lang", "ALTER TABLE delivery_subscribers ADD COLUMN lang TEXT NOT NULL DEFAULT 'en'"),
]


class DeliverySubscriberStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # Same file as OrderStore by default -- one small extra table in
        # the same SQLite database, not a separate file to keep track of.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _existing_columns(self) -> set[str]:
        return {row[1] for row in self._conn.execute("PRAGMA table_info(delivery_subscribers)").fetchall()}

    def _migrate(self) -> None:
        existing = self._existing_columns()
        for column_name, statement in _MIGRATIONS:
            if column_name not in existing:
                try:
                    self._conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    # Both gunicorn workers run this at the same moment on
                    # boot: each can see the column missing, then lose the
                    # race to ADD it. That used to crash the worker (and
                    # the whole gunicorn master) until systemd restarted
                    # it. Already-added is exactly the state we want.
                    if "duplicate column name" not in str(exc):
                        raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DeliverySubscriberStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def add(self, email: str, lang: str = "en") -> None:
        """Idempotent: registering the same address twice is a no-op (not
        an error -- a courier re-registering, e.g. new device or cleared
        localStorage, must never fail), EXCEPT for `lang`, which always
        gets updated to whatever was just given -- the whole point is
        this tracks the courier's current app language, not their
        language at first-ever registration."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO delivery_subscribers (email, lang, created_at) VALUES (?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET lang = excluded.lang
                """,
                (email, lang, now),
            )
            self._conn.commit()

    def remove(self, email: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM delivery_subscribers WHERE email = ?", (email,))
            self._conn.commit()

    def list_emails(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT email FROM delivery_subscribers ORDER BY id").fetchall()
        return [r[0] for r in rows]

    def list_subscribers(self) -> list[tuple[str, str]]:
        """[(email, lang), ...] -- used to personalize the per-order
        delivery notification (Part 72) to each courier's own language,
        unlike list_emails() above which is just the plain address list."""
        with self._lock:
            rows = self._conn.execute("SELECT email, lang FROM delivery_subscribers ORDER BY id").fetchall()
        return [(r[0], r[1]) for r in rows]

    def is_registered(self, email: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM delivery_subscribers WHERE email = ?", (email,)).fetchone()
        return row is not None
