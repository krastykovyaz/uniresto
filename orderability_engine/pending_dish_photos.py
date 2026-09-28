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
from collections.abc import Iterator
from contextlib import contextmanager
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

# `email` (Part 90): added after this table already existed on the live
# server (Part 84) -- CREATE TABLE IF NOT EXISTS is a no-op against it,
# so this needs an explicit migration, same reasoning/pattern as
# orders.py's own _MIGRATIONS. Records who submitted the photo, so
# approving/replacing it (see app.py's admin_approve_dish_photo/
# admin_replace_dish_photo) knows whose Luni balance to credit.
_MIGRATIONS = [
    ("email", "ALTER TABLE pending_dish_photos ADD COLUMN email TEXT"),
]


class PendingDishPhotoStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute(SCHEMA)
            self._migrate(conn)

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

    def _migrate(self, conn: sqlite3.Connection) -> None:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(pending_dish_photos)").fetchall()}
        for column_name, statement in _MIGRATIONS:
            if column_name not in existing:
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    # Both gunicorn workers can race to add this at boot --
                    # see orders.py's own _migrate() for the identical
                    # reasoning; already-added is exactly the state we want.
                    if "duplicate column name" not in str(exc):
                        raise

    def create(self, slug: str, category: str, name: str, photo_path: str, email: str | None = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO pending_dish_photos (slug, category, name, photo_path, submitted_at, email) VALUES (?, ?, ?, ?, ?, ?)",
                (slug, category, name, photo_path, datetime.now(timezone.utc).isoformat(), email),
            )
            return cur.lastrowid

    def get(self, pending_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, slug, category, name, photo_path, submitted_at, email FROM pending_dish_photos WHERE id = ?",
                (pending_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def all_pending(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, slug, category, name, photo_path, submitted_at, email FROM pending_dish_photos ORDER BY submitted_at ASC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete(self, pending_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM pending_dish_photos WHERE id = ?", (pending_id,))

    def pop_submitted_before(self, cutoff: datetime) -> list[dict]:
        """Deletes every submission older than `cutoff` that nobody ever
        decided on, and returns them so the caller can delete their files
        too -- otherwise an ignored Telegram ping leaves both the row and
        the file behind forever."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, slug, category, name, photo_path, submitted_at, email FROM pending_dish_photos WHERE submitted_at < ?",
                (cutoff.isoformat(),),
            ).fetchall()
            conn.execute("DELETE FROM pending_dish_photos WHERE submitted_at < ?", (cutoff.isoformat(),))
        return [self._row_to_dict(row) for row in rows]

    def pop_other_pending_for_dish(self, slug: str, category: str, name: str, keep_id: int) -> list[dict]:
        """Part 86: once ONE submission for this exact dish has just been
        approved/replaced, any OTHER still-pending submission for that
        same dish is now moot -- there's only one live photo a dish can
        have, so keeping a second (or third) copy sitting in the review
        queue (and its file on disk) forever, un-decided, is exactly the
        kind of orphaned duplicate this whole module exists to avoid.
        Deletes those rows and returns them so the caller can also delete
        their now-unreferenced files."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, slug, category, name, photo_path, submitted_at, email FROM pending_dish_photos "
                "WHERE slug = ? AND category = ? AND name = ? AND id != ?",
                (slug, category, name, keep_id),
            ).fetchall()
            conn.execute(
                "DELETE FROM pending_dish_photos WHERE slug = ? AND category = ? AND name = ? AND id != ?",
                (slug, category, name, keep_id),
            )
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "id": row[0],
            "slug": row[1],
            "category": row[2],
            "name": row[3],
            "photo_path": row[4],
            "submitted_at": row[5],
            "email": row[6],
        }
