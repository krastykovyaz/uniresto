"""SQLite cache for Restopolis availability checks, with change detection,
plus a separate SQLite cache for the raw week HTML the menu is parsed
from.

Restopolis is polite-scraped (rate-limited, see restopolis/client.py) and
we additionally cache each (restaurant, date) check for a TTL so repeated
UI/API calls don't re-hit the live site. `--refresh` (CLI) / `refresh=True`
(service) bypasses the cache for that one check, but the *comparison*
against the previous cached value still happens, so genuine changes are
logged (see `[CHANGED]` in service.py) even when force-refreshing.

The week-HTML table (`week_html_cache`) is what backs the menu itself
(dish names/descriptions/allergens -- see menu_service.py): it's kept in
this same SQLite file, PERSISTED ACROSS PROCESS RESTARTS, and on a much
longer TTL (1 hour, see service.py's WEEK_HTML_TTL_SECONDS) than the
15-minute orderability-status cache above, since the menu itself changes
far less often than open/closed signals do. Before this, the menu was
only ever cached in an in-process Python dict (OrderabilityService's
`_week_html_cache`), which is lost on every restart -- every restart
meant every single menu load re-fetched live from Restopolis. That
in-process dict still exists as a fast first check; this table is the
persistent fallback behind it, not a replacement for it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from orderability_engine.models import RestopolisDayStatus

logger = logging.getLogger("orderability.cache")

DEFAULT_TTL_SECONDS = 15 * 60  # 15 minutes

SCHEMA = """
CREATE TABLE IF NOT EXISTS orderability_cache (
    restaurant_code TEXT NOT NULL,
    target_date TEXT NOT NULL,
    menu_available INTEGER,       -- 0/1/NULL (tri-state: NULL = unknown)
    ordering_available INTEGER,
    reservation_signal_text TEXT,
    service_start TEXT,
    service_end TEXT,
    restopolis_order_deadline TEXT,
    item_count INTEGER,
    menu_hash TEXT,
    source_url TEXT,
    fetch_error TEXT,
    checked_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (restaurant_code, target_date)
);

CREATE TABLE IF NOT EXISTS week_html_cache (
    restaurant_code TEXT NOT NULL,
    weeks_ahead INTEGER NOT NULL,   -- 0 = this week, 1 = next week, etc (see detector.weeks_ahead_for)
    html TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (restaurant_code, weeks_ahead)
);
"""


def _to_tri_bool(v: int | None) -> bool | None:
    return None if v is None else bool(v)


def _from_tri_bool(v: bool | None) -> int | None:
    return None if v is None else int(v)


class OrderabilityCache:
    def __init__(self, db_path: str | Path = "orderability.db", ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        # check_same_thread=False + an explicit lock: verified live that
        # Flask's dev server CAN dispatch two requests concurrently (two
        # parallel fetch() calls from the browser triggered a genuine
        # `sqlite3.InterfaceError: bad parameter or other API misuse` from
        # two threads hitting this connection at once). check_same_thread
        # alone only relaxes the "created in another thread" check; it
        # does not make one connection safe for concurrent use, so every
        # public method below takes self._lock before touching self._conn.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "OrderabilityCache":
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

    def get_raw(self, restaurant_code: str, target_date: date) -> RestopolisDayStatus | None:
        """Return the cached entry regardless of expiry (used for change
        detection even on a forced refresh)."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT menu_available, ordering_available, reservation_signal_text,
                       service_start, service_end, restopolis_order_deadline,
                       item_count, menu_hash, source_url, fetch_error
                FROM orderability_cache WHERE restaurant_code = ? AND target_date = ?
                """,
                (restaurant_code, target_date.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return RestopolisDayStatus(
            restaurant_code=restaurant_code,
            restaurant_name="",  # not stored, caller already has it
            target_date=target_date,
            menu_available=_to_tri_bool(row[0]),
            ordering_available=_to_tri_bool(row[1]),
            reservation_signal_text=row[2],
            service_start=row[3],
            service_end=row[4],
            restopolis_order_deadline=row[5],
            item_count=row[6] or 0,
            menu_hash=row[7] or "",
            source_url=row[8] or "",
            fetch_error=row[9],
        )

    def get(self, restaurant_code: str, target_date: date) -> tuple[RestopolisDayStatus, datetime] | None:
        """Return (status, checked_at) if a *non-expired* entry exists."""
        with self._lock:
            row = self._conn.execute(
                "SELECT checked_at, expires_at FROM orderability_cache WHERE restaurant_code = ? AND target_date = ?",
                (restaurant_code, target_date.isoformat()),
            ).fetchone()
        if row is None:
            return None
        checked_at = datetime.fromisoformat(row[0])
        expires_at = datetime.fromisoformat(row[1])
        if datetime.now(timezone.utc) >= expires_at:
            return None
        return self.get_raw(restaurant_code, target_date), checked_at

    def set(self, status: RestopolisDayStatus, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl)

        with self._lock, self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO orderability_cache
                    (restaurant_code, target_date, menu_available, ordering_available,
                     reservation_signal_text, service_start, service_end,
                     restopolis_order_deadline, item_count, menu_hash, source_url,
                     fetch_error, checked_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(restaurant_code, target_date) DO UPDATE SET
                    menu_available=excluded.menu_available,
                    ordering_available=excluded.ordering_available,
                    reservation_signal_text=excluded.reservation_signal_text,
                    service_start=excluded.service_start,
                    service_end=excluded.service_end,
                    restopolis_order_deadline=excluded.restopolis_order_deadline,
                    item_count=excluded.item_count,
                    menu_hash=excluded.menu_hash,
                    source_url=excluded.source_url,
                    fetch_error=excluded.fetch_error,
                    checked_at=excluded.checked_at,
                    expires_at=excluded.expires_at
                """,
                (
                    status.restaurant_code,
                    status.target_date.isoformat(),
                    _from_tri_bool(status.menu_available),
                    _from_tri_bool(status.ordering_available),
                    status.reservation_signal_text,
                    status.service_start,
                    status.service_end,
                    status.restopolis_order_deadline,
                    status.item_count,
                    status.menu_hash,
                    status.source_url,
                    status.fetch_error,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )

    # ----------------------------------------------------- Week HTML cache
    #
    # Backs the menu itself (see this module's docstring). Keyed by
    # (restaurant_code, weeks_ahead) -- the same key OrderabilityService's
    # in-process dict already uses -- rather than by individual date, since
    # one week's HTML covers every date in that week (Restopolis's own
    # page shape, see restopolis/parser.py).

    def get_week_html(self, restaurant_code: str, weeks_ahead: int) -> str | None:
        """Returns the cached HTML if a *non-expired* entry exists, else None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT html, expires_at FROM week_html_cache WHERE restaurant_code = ? AND weeks_ahead = ?",
                (restaurant_code, weeks_ahead),
            ).fetchone()
        if row is None:
            return None
        html, expires_at = row[0], datetime.fromisoformat(row[1])
        if datetime.now(timezone.utc) >= expires_at:
            return None
        return html

    def set_week_html(self, restaurant_code: str, weeks_ahead: int, html: str, ttl_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._lock, self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO week_html_cache (restaurant_code, weeks_ahead, html, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(restaurant_code, weeks_ahead) DO UPDATE SET
                    html=excluded.html,
                    fetched_at=excluded.fetched_at,
                    expires_at=excluded.expires_at
                """,
                (restaurant_code, weeks_ahead, html, now.isoformat(), expires_at.isoformat()),
            )
