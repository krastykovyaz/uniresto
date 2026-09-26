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


class DeliverySubscriberStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # Same file as OrderStore by default -- one small extra table in
        # the same SQLite database, not a separate file to keep track of.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DeliverySubscriberStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def add(self, email: str) -> None:
        """Idempotent: registering the same address twice is a no-op, not
        an error -- a courier re-registering (new device, cleared
        localStorage) must never fail."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO delivery_subscribers (email, created_at) VALUES (?, ?) ON CONFLICT(email) DO NOTHING",
                (email, now),
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

    def is_registered(self, email: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM delivery_subscribers WHERE email = ?", (email,)).fetchone()
        return row is not None
