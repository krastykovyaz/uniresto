"""Traffic counters for the admin's evening report (Part 74) -- how many
real visits each stage of the app saw today: opening the app at all
("home"), viewing a restaurant's menu ("menu"), and opening the Delivery
screen ("delivery"). Orders themselves aren't tracked here at all --
OrderStore already has that real count (Part 74's daily_report.py reads
it directly), so duplicating it into a second counter would just be
another place for the two numbers to drift apart.

Deliberately recorded from the client (a dedicated /api/track/home call
for "home"; "menu"/"delivery" are recorded server-side on their own
existing API routes, api_menu()/api_delivery_orders()) rather than at
GET / itself -- that route is also what link-preview crawlers
(Telegram/WhatsApp/Facebook, see mobile_app()'s own Open Graph comment)
fetch to build a share preview, and a crawler never runs this app's JS
or calls any /api/* route, so counting real "did the app actually open"
traffic there would silently inflate itself every time a link gets
shared -- exactly the class of bug that make analytics numbers
untrustworthy, which this app's whole ethos (see README) tries hard to
avoid.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS page_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

EVENTS = ("home", "menu", "delivery")


class PageViewStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # Same file as OrderStore by default -- one small extra table, not
        # a separate file to keep track of.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PageViewStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record(self, event: str) -> None:
        if event not in EVENTS:
            raise ValueError(f"Unknown page-view event {event!r}, expected one of {EVENTS}")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute("INSERT INTO page_views (event, created_at) VALUES (?, ?)", (event, now))
            self._conn.commit()

    def count_between(self, event: str, start: datetime, end: datetime) -> int:
        """Count of `event` rows in [start, end) -- both real, timezone-
        aware datetimes (the caller decides what "today" means; see
        daily_report.py's own local-midnight-to-midnight computation).
        Converted to UTC before comparing: `created_at` is always stored
        in UTC (record() above), and ISO8601 strings only sort correctly
        against each other when they share the same offset -- a caller
        passing e.g. Europe/Luxembourg-local bounds straight through
        would silently compare wrong once summer/winter time put its
        offset anywhere other than +00:00."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM page_views WHERE event = ? AND created_at >= ? AND created_at < ?",
                (event, start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()),
            ).fetchone()
        return row[0]
