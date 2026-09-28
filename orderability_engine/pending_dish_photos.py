"""A student's freshly-submitted dish photo (Part 84) sits here, not yet
in DishPhotoStore, until the admin reviews it over Telegram (see
telegram_notify.send_dish_photo_review) or the /admin/dish-photos pages.
Deliberately a SEPARATE table/file from a "live" concept in
DishPhotoStore itself: a row here is a decision waiting to be made, not
a fact about the world, and the two must never be confused -- approving
just copies the (slug, category, name, photo_path) over into
DishPhotoStore and deletes the row here; rejecting deletes the row (and
its file) with nothing carried over.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_dish_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    photo_path TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
"""


class PendingDishPhotoStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def create(self, slug: str, category: str, name: str, photo_path: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO pending_dish_photos (slug, category, name, photo_path, submitted_at) VALUES (?, ?, ?, ?, ?)",
                (slug, category, name, photo_path, datetime.now(timezone.utc).isoformat()),
            )
            return cur.lastrowid

    def get(self, pending_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, slug, category, name, photo_path, submitted_at FROM pending_dish_photos WHERE id = ?",
                (pending_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def all_pending(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, slug, category, name, photo_path, submitted_at FROM pending_dish_photos ORDER BY submitted_at ASC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete(self, pending_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_dish_photos WHERE id = ?", (pending_id,))

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "id": row[0],
            "slug": row[1],
            "category": row[2],
            "name": row[3],
            "photo_path": row[4],
            "submitted_at": row[5],
        }
