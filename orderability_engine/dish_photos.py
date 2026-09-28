"""Durable, crowd-sourced dish photos -- a student can submit a real photo
for a menu item via the food card's upload tile (see static/app.js's
food-card-photo-input), and from then on everyone sees that photo instead
of the generic plate illustration, on every date this exact dish reappears.

Keyed by (restaurant slug, category, name) -- the same identity favorites
already use (see toggleFavorite()/isFavorite() in static/app.js). item.id
is NOT usable as a key: it's only a stable sequential index within one
response, re-derived fresh on every request (see
menu_service.flatten_menu_items's own docstring)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dish_photos (
    slug TEXT NOT NULL,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    photo_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY (slug, category, name)
);
"""


class DishPhotoStore:
    def __init__(self, db_path: str | Path = "dish_photos.db"):
        self.db_path = str(db_path)
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def set_photo(self, slug: str, category: str, name: str, photo_path: str) -> str | None:
        """Sets this dish's live photo, returning whatever photo_path it
        had before (or None if it had none). This store only ever keeps
        ONE row per (slug, category, name), so once this returns, nothing
        in DISH_PHOTO_STORE points at that old path anymore -- the
        caller (app.py's admin_approve_dish_photo/admin_replace_dish_photo,
        Part 86) deletes the now-orphaned FILE, so a dish's storage never
        accumulates more than one photo on disk no matter how many times
        it gets re-approved across however many days it reappears on."""
        with self._connect() as conn:
            previous = conn.execute(
                "SELECT photo_path FROM dish_photos WHERE slug = ? AND category = ? AND name = ?",
                (slug, category, name),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO dish_photos (slug, category, name, photo_path, uploaded_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slug, category, name)
                DO UPDATE SET photo_path = excluded.photo_path, uploaded_at = excluded.uploaded_at
                """,
                (slug, category, name, photo_path, datetime.now(timezone.utc).isoformat()),
            )
        return previous[0] if previous else None

    def photos_for_restaurant(self, slug: str) -> dict[str, dict[str, str]]:
        """Returns {category: {name: photo_path}} for this restaurant --
        the shape the frontend indexes straight from item.category/item.name."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, name, photo_path FROM dish_photos WHERE slug = ?",
                (slug,),
            ).fetchall()
        result: dict[str, dict[str, str]] = {}
        for category, name, photo_path in rows:
            result.setdefault(category, {})[name] = photo_path
        return result
