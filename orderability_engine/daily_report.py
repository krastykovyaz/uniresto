"""Evening admin report (Part 74) -- once a day, pings the admin over
Telegram with real traffic/order counts for that day: how many people
opened the app, viewed a menu, placed an order, and opened the Delivery
screen. See page_views.py's own docstring for why "opened the app" is
tracked via a client-fired beacon rather than at GET / itself (link-
preview crawlers also hit that route).

Runs as a background thread (same shape as cache_warmer.py's), started
once per gunicorn WORKER PROCESS -- with 2 workers and no --preload,
that means two threads independently wake up at the same send time
every evening. DailyReportStore.claim() is what keeps that from sending
the report twice: it's a SQLite INSERT with ON CONFLICT DO NOTHING
keyed by the report's own date, so whichever worker's thread gets there
first "wins" the send and the other sees its insert affect 0 rows and
skips -- same shared-SQLite-as-the-only-cross-process coordination point
this app already relies on elsewhere (see email_verification.py's own
docstring for the original bug this same pattern fixed).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path

from orderability_engine.models import TZINFO
from orderability_engine.orders import OrderStore
from orderability_engine.page_views import PageViewStore
from orderability_engine.telegram_notify import send_daily_report

logger = logging.getLogger("uniresto.daily_report")

DEFAULT_SEND_HOUR = 20  # 20:00 Europe/Luxembourg -- see this feature's own request for why

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_reports_sent (
    report_date TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);
"""


class DailyReportStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DailyReportStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def claim(self, report_date: str) -> bool:
        """True the FIRST time this is called for a given report_date
        (across every process sharing this db file) -- False every time
        after, including from a different worker process. See this
        module's own docstring for why that's exactly the dedup this
        needs."""
        now = datetime.now(TZINFO).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO daily_reports_sent (report_date, sent_at) VALUES (?, ?) ON CONFLICT(report_date) DO NOTHING",
                (report_date, now),
            )
            self._conn.commit()
            return cur.rowcount > 0


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) for `day` as Europe/Luxembourg local midnight to the
    next day's local midnight, both real timezone-aware datetimes --
    stored `created_at` timestamps are UTC, but a courier/admin's own
    "today" is a LOCAL calendar day, not a UTC one."""
    start = datetime.combine(day, dt_time(0, 0), tzinfo=TZINFO)
    return start, start + timedelta(days=1)


def compute_report_counts(page_views: PageViewStore, order_store: OrderStore, report_date: date) -> dict:
    start, end = local_day_bounds(report_date)
    return {
        "home": page_views.count_between("home", start, end),
        "menu": page_views.count_between("menu", start, end),
        "orders": order_store.count_created_between(start, end),
        "delivery": page_views.count_between("delivery", start, end),
    }


def send_report_for(
    page_views: PageViewStore, order_store: OrderStore, report_store: DailyReportStore, report_date: date
) -> bool:
    """Computes and sends the report for `report_date`, but ONLY if
    report_store.claim() says this call is the one that gets to (see the
    module docstring). Returns whether it actually sent -- False both
    when another process already claimed it and when Telegram itself
    isn't configured (send_daily_report()'s own best-effort contract)."""
    if not report_store.claim(report_date.isoformat()):
        return False
    counts = compute_report_counts(page_views, order_store, report_date)
    sent, error = send_daily_report(counts, report_date)
    if not sent:
        logger.warning("[DAILY-REPORT] failed to send report for %s: %s", report_date, error)
    return sent


def _next_send_time(now: datetime, send_hour: int) -> datetime:
    candidate = now.replace(hour=send_hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def start_daily_report_scheduler(
    page_views: PageViewStore,
    order_store: OrderStore,
    report_store: DailyReportStore,
    send_hour: int = DEFAULT_SEND_HOUR,
) -> threading.Thread:
    """Sleeps until the next send_hour:00 Europe/Luxembourg, sends (or,
    on every worker process but one, no-ops via claim()), then sleeps
    until the day after. A daemon thread, same reasoning as
    cache_warmer.start_cache_warmer(): never blocks the process from
    exiting, needs no coordination beyond the shared SQLite file."""

    def loop() -> None:
        while True:
            now = datetime.now(TZINFO)
            next_send = _next_send_time(now, send_hour)
            time.sleep((next_send - now).total_seconds())
            try:
                send_report_for(page_views, order_store, report_store, next_send.date())
            except Exception:  # noqa: BLE001 -- one bad evening must never kill the thread for every evening after
                logger.warning("[DAILY-REPORT] unexpected failure sending report", exc_info=True)

    thread = threading.Thread(target=loop, daemon=True, name="daily-report")
    thread.start()
    return thread
