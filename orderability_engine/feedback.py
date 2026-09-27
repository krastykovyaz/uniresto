"""Free-text feedback submitted from the Profile screen's "Send feedback"
field (Part 71) -- the one place in the app for a user to say anything
that doesn't fit an order comment (Part 55, which is scoped to a single
order and only ever reaches the admin placing THAT order). Stored so
nothing is lost even if the admin misses the Telegram ping
(telegram_notify.send_feedback_notification), and visible in full at
/admin/feedback. Never parsed or acted on automatically -- same
"free text is just relayed, never interpreted" rule as the order
comment field.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    contact_email TEXT,
    created_at TEXT NOT NULL
);
"""


class FeedbackStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # Same file as OrderStore/ComingSoonClickStore by default -- one
        # small extra table, not a separate file to keep track of.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "FeedbackStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record(self, message: str, contact_email: str | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback (message, contact_email, created_at) VALUES (?, ?, ?)",
                (message, contact_email, now),
            )
            self._conn.commit()

    def list_recent(self, limit: int = 200) -> list[dict]:
        """Newest first -- an admin reading a feedback inbox cares about
        what just came in, not the oldest entry."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, message, contact_email, created_at FROM feedback ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "message": r[1], "contact_email": r[2], "created_at": r[3]}
            for r in rows
        ]
