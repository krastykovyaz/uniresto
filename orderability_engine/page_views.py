"""Traffic counters for the admin's evening report (Part 74) -- how many
real visits each stage of the app saw today: opening the app at all
("home"), viewing a restaurant's menu ("menu"), and opening the Delivery
screen ("delivery"). Orders themselves aren't tracked here at all --
OrderStore already has that real count (Part 74's daily_report.py reads
it directly), so duplicating it into a second counter would just be
another place for the two numbers to drift apart.

"home" and "menu" are recorded from the client (/api/track/<event>);
"delivery" server-side in api_delivery_orders(). "menu" can't be counted
at api_menu() because the date picker prefetches every orderable day's
menu in the background -- one real view read as ~5 there. "home" isn't
counted at GET / itself because that route is also what link-preview crawlers
(Telegram/WhatsApp/Facebook, see mobile_app()'s own Open Graph comment)
fetch to build a share preview, and a crawler never runs this app's JS
or calls any /api/* route, so counting real "did the app actually open"
traffic there would silently inflate itself every time a link gets
shared -- exactly the class of bug that make analytics numbers
untrustworthy, which this app's whole ethos (see README) tries hard to
avoid.

`source` (Part 78) is the optional `?src=` a "home" open arrived with --
e.g. two different QR codes on two different printed flyers, each
encoding its own resto.unilu.space/?src=<label>, so scans of one can be
told apart from the other (see /admin/sources). It's whatever label the
flyer/QR was made with, an open string, not a fixed registry -- a new
campaign needs no code change, just a QR encoding a new ?src= value.
Recorded once, from the client, at the SAME init() beacon as "home"
itself: never re-derived or re-attributed to a later action in the same
visit.
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
    source TEXT,
    created_at TEXT NOT NULL
);
"""

# source added after the original schema shipped -- see orders.py's own
# _MIGRATIONS for the ALTER TABLE pattern this mirrors, including the
# "another gunicorn worker already added it" race handled in _migrate()
# below.
_MIGRATIONS = [
    ("source", "ALTER TABLE page_views ADD COLUMN source TEXT"),
]

EVENTS = ("home", "menu", "delivery")

# A QR code is a physical object -- no way to ever edit what it encodes
# once printed, so this stays short and forgiving rather than a strict
# format. Long enough for a real label ("flyer-kirchberg-noticeboard"),
# capped so a malformed/malicious value can't bloat the table.
MAX_SOURCE_LENGTH = 60


class PageViewStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # Same file as OrderStore by default -- one small extra table, not
        # a separate file to keep track of.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _existing_columns(self) -> set[str]:
        return {row[1] for row in self._conn.execute("PRAGMA table_info(page_views)").fetchall()}

    def _migrate(self) -> None:
        existing = self._existing_columns()
        for column_name, statement in _MIGRATIONS:
            if column_name not in existing:
                try:
                    self._conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc):
                        raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PageViewStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def record(self, event: str, source: str | None = None) -> None:
        if event not in EVENTS:
            raise ValueError(f"Unknown page-view event {event!r}, expected one of {EVENTS}")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO page_views (event, source, created_at) VALUES (?, ?, ?)", (event, source, now)
            )
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

    def source_counts(self, event: str = "home") -> list[tuple[str, int]]:
        """[(source, count), ...], busiest first, all-time -- one row per
        DISTINCT source actually seen (never a fixed list: a new QR's
        label shows up here the first time it's scanned, nothing to
        register in advance). A "home" open with no ?src= at all (opened
        the site directly, not through a tracked QR) groups under the
        literal string "(direct)"."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT COALESCE(source, '(direct)') AS src, COUNT(*) AS n FROM page_views "
                "WHERE event = ? GROUP BY src ORDER BY n DESC, src",
                (event,),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]
