"""Luni reward points (Part 87) -- keyed by a student's verified
University email, the only stable identity this "no accounts" app has
(see verified_emails.py's own docstring for why that's the identity of
choice elsewhere too). Starts at 0 for anyone with no row yet -- nothing
in this codebase awards points yet; this is just the balance itself,
read by Profile's "Reward" row. `add_points()` exists for whatever
earns Luni to be wired up later, without needing a schema change."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS rewards (
    email TEXT PRIMARY KEY,
    points INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


class RewardStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get_points(self, email: str) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT points FROM rewards WHERE email = ?", (email,)).fetchone()
        return row[0] if row else 0

    def add_points(self, email: str, delta: int) -> int:
        """Adds `delta` (may be negative) to email's balance, creating
        the row at 0 first if this is their first-ever change. Returns
        the new total."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rewards (email, points, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET points = points + excluded.points, updated_at = excluded.updated_at
                """,
                (email, delta, datetime.now(timezone.utc).isoformat()),
            )
            row = conn.execute("SELECT points FROM rewards WHERE email = ?", (email,)).fetchone()
        return row[0]
