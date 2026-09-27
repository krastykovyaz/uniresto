"""Interest-signal counter for the "coming soon" restaurant-list cards
(Food House/Café/Lab/Zone, Part 66) -- these aren't real, orderable
restaurants yet, so instead of the "COMING SOON" label that used to sit
printed on every card (removed, Part 69), a tap now just quietly counts
toward "how many people wanted this one", visible to the admin at
/admin/coming-soon-clicks. Every tap is recorded, not deduplicated per
visitor -- there's no account/session in this app to dedupe by anyway
(see delivery_subscribers.py's own note on the same minimal-auth
ethos), so this is a raw interest count, not a unique-visitor count.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS coming_soon_clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class ComingSoonClickStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # Same file as OrderStore/DeliverySubscriberStore by default --
        # one small extra table, not a separate file to keep track of.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ComingSoonClickStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record(self, location: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO coming_soon_clicks (location, created_at) VALUES (?, ?)", (location, now)
            )
            self._conn.commit()

    def counts(self) -> list[tuple[str, int]]:
        """[(location, count), ...], busiest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT location, COUNT(*) AS n FROM coming_soon_clicks GROUP BY location ORDER BY n DESC, location"
            ).fetchall()
        return [(r[0], r[1]) for r in rows]
