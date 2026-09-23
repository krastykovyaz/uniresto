"""SQLite storage for scraped menus.

Schema (see README.md for the full rationale):

    restaurants(id, code UNIQUE, name, restaurant_id, service_id, created_at, updated_at)
    menus(id, restaurant_id -> restaurants.id, menu_date, service_name, service_time,
          source_url, scraped_at, UNIQUE(restaurant_id, menu_date, service_name))
    menu_items(id, menu_id -> menus.id, category, name, description, price,
               allergens_json, dietary_json, raw_text, sort_order,
               UNIQUE(menu_id, category, name, sort_order))

Re-running the scraper for a (restaurant, date, service) that's already in
the database does not create duplicates: `upsert_daily_menu` updates the
`menus` row in place and replaces its `menu_items` rows atomically (delete
+ re-insert within one transaction), rather than trying to diff individual
items. This is deliberate: if a dish is removed from Restopolis between two
scrapes, delete+re-insert makes it disappear from the DB too, whereas a
naive "insert or ignore" upsert would leave a stale row behind forever.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from restopolis.models import DailyMenu, RestaurantConfig

logger = logging.getLogger("restopolis.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS restaurants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    restaurant_id INTEGER NOT NULL,
    service_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS menus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id),
    menu_date TEXT NOT NULL,
    service_name TEXT NOT NULL,
    service_time TEXT,
    source_url TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    UNIQUE(restaurant_id, menu_date, service_name)
);

CREATE TABLE IF NOT EXISTS menu_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_id INTEGER NOT NULL REFERENCES menus(id),
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    price REAL,
    allergens_json TEXT NOT NULL,
    dietary_json TEXT NOT NULL,
    raw_text TEXT,
    sort_order INTEGER NOT NULL,
    weight_value REAL,
    weight_unit TEXT,
    UNIQUE(menu_id, category, name, sort_order)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RestopolisDatabase:
    def __init__(self, db_path: str | Path = "restopolis.db"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RestopolisDatabase":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @contextmanager
    def _transaction(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert_restaurant(self, cfg: RestaurantConfig) -> int:
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO restaurants (code, name, restaurant_id, service_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name=excluded.name,
                    restaurant_id=excluded.restaurant_id,
                    service_id=excluded.service_id,
                    updated_at=excluded.updated_at
                """,
                (cfg.code, cfg.name, cfg.restaurant_id, cfg.service_id, now, now),
            )
            row = conn.execute(
                "SELECT id FROM restaurants WHERE code = ?", (cfg.code,)
            ).fetchone()
        return row[0]

    def upsert_daily_menu(self, restaurant_db_id: int, menu: DailyMenu) -> int:
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO menus (restaurant_id, menu_date, service_name, service_time, source_url, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(restaurant_id, menu_date, service_name) DO UPDATE SET
                    service_time=excluded.service_time,
                    source_url=excluded.source_url,
                    scraped_at=excluded.scraped_at
                """,
                (
                    restaurant_db_id,
                    menu.menu_date.isoformat(),
                    menu.service_name,
                    menu.service_time,
                    menu.source_url,
                    now,
                ),
            )
            menu_id = conn.execute(
                "SELECT id FROM menus WHERE restaurant_id = ? AND menu_date = ? AND service_name = ?",
                (restaurant_db_id, menu.menu_date.isoformat(), menu.service_name),
            ).fetchone()[0]

            conn.execute("DELETE FROM menu_items WHERE menu_id = ?", (menu_id,))
            conn.executemany(
                """
                INSERT INTO menu_items
                    (menu_id, category, name, description, price, allergens_json, dietary_json, raw_text, sort_order, weight_value, weight_unit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        menu_id,
                        item.category,
                        item.name,
                        item.description,
                        item.price,
                        json.dumps(item.allergens, ensure_ascii=False),
                        json.dumps(item.dietary, ensure_ascii=False),
                        item.raw_text,
                        item.sort_order,
                        item.weight_value,
                        item.weight_unit,
                    )
                    for item in menu.items
                ],
            )
        return menu_id

    def count_menu_items(self, menu_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM menu_items WHERE menu_id = ?", (menu_id,)
        ).fetchone()
        return row[0]

    def fetch_menus(
        self,
        restaurant_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        """Return menus (with nested items) for JSON export or inspection."""
        query = """
            SELECT m.id, r.code, r.name, m.menu_date, m.service_name, m.service_time,
                   m.source_url, m.scraped_at
            FROM menus m
            JOIN restaurants r ON r.id = m.restaurant_id
            WHERE 1=1
        """
        params: list = []
        if restaurant_code:
            query += " AND r.code = ?"
            params.append(restaurant_code)
        if start_date:
            query += " AND m.menu_date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND m.menu_date <= ?"
            params.append(end_date.isoformat())
        query += " ORDER BY r.code, m.menu_date, m.service_name"

        menus = []
        for row in self._conn.execute(query, params).fetchall():
            (menu_id, code, name, menu_date, service_name, service_time,
             source_url, scraped_at) = row
            items = self._conn.execute(
                """
                SELECT category, name, description, price, allergens_json, dietary_json, sort_order, weight_value, weight_unit
                FROM menu_items WHERE menu_id = ? ORDER BY sort_order
                """,
                (menu_id,),
            ).fetchall()
            menus.append(
                {
                    "restaurant_code": code,
                    "restaurant_name": name,
                    "date": menu_date,
                    "service": service_name,
                    "service_time": service_time,
                    "source_url": source_url,
                    "scraped_at": scraped_at,
                    "items": [
                        {
                            "category": it[0],
                            "name": it[1],
                            "description": it[2],
                            "price": it[3],
                            "allergens": json.loads(it[4]),
                            "dietary": json.loads(it[5]),
                            "sort_order": it[6],
                            "weight_value": it[7],
                            "weight_unit": it[8],
                        }
                        for it in items
                    ],
                }
            )
        return menus
