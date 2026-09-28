"""Evening admin report (Part 74) -- once a day, pings the admin over
Telegram with real traffic/order counts for that day: how many people
opened the app, viewed a menu, placed an order, and opened the Delivery
screen. See page_views.py's own docstring for why "opened the app" is
tracked via a client-fired beacon rather than at GET / itself (link-
preview crawlers also hit that route).

Runs as a background thread (same shape as menu_refresh.py's), started
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
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

from orderability_engine.models import TZINFO
from orderability_engine.orders import OrderStore
from orderability_engine.page_views import PageViewStore
from orderability_engine.telegram_notify import is_configured, send_daily_report

logger = logging.getLogger("uniresto.daily_report")

DEFAULT_SEND_HOUR = 20  # 20:00 Europe/Luxembourg -- see this feature's own request for why
RETRY_INTERVAL_SECONDS = 10 * 60

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

    def release(self, report_date: str) -> None:
        """Gives a claim back after a failed send, so a later retry (by
        this process or any other) can claim and send it -- otherwise one
        Telegram hiccup at send time would lose that day's report."""
        with self._lock:
            self._conn.execute("DELETE FROM daily_reports_sent WHERE report_date = ?", (report_date,))
            self._conn.commit()


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
        # Per-QR-code breakdown of that same "home" count (Part 82) --
        # e.g. [("flyer-c", 12), ("(direct)", 5)] -- so the admin can see
        # which printed/digital flyer is actually driving visits, not
        # just the aggregate total. Same source strings /admin/sources
        # shows (all-time); this is just scoped to report_date.
        "home_by_source": page_views.source_counts_between("home", start, end),
        "menu": page_views.count_between("menu", start, end),
        "orders": order_store.count_created_between(start, end),
        "delivery": page_views.count_between("delivery", start, end),
    }


def send_report_for(
    page_views: PageViewStore, order_store: OrderStore, report_store: DailyReportStore, report_date: date
) -> str:
    """Computes and sends the report for `report_date`, but ONLY if
    report_store.claim() says this call is the one that gets to (see the
    module docstring). Returns one of:
      "sent"             -- this call sent it
      "already_claimed"  -- another call/process owns (or sent) it
      "not_configured"   -- no Telegram credentials; nothing claimed
      "failed"           -- the send itself failed; the claim is released
                            so a retry can take it (run_report_with_retries)"""
    if not is_configured():
        return "not_configured"
    key = report_date.isoformat()
    if not report_store.claim(key):
        return "already_claimed"
    counts = compute_report_counts(page_views, order_store, report_date)
    sent, error = send_daily_report(counts, report_date)
    if sent:
        return "sent"
    report_store.release(key)
    logger.warning("[DAILY-REPORT] failed to send report for %s: %s", report_date, error)
    return "failed"


def run_report_with_retries(
    page_views: PageViewStore,
    order_store: OrderStore,
    report_store: DailyReportStore,
    report_date: date,
    retry_seconds: int = RETRY_INTERVAL_SECONDS,
    sleep=time.sleep,
    now=lambda: datetime.now(TZINFO),
) -> str:
    """send_report_for(), retried every `retry_seconds` while it keeps
    failing, until the report's own day is over -- a late report beats
    none. Only a "failed" result retries: "already_claimed" means another
    worker owns it, and "not_configured" won't change by waiting. The
    retrying process always re-claims first, so this can't double-send
    either. `sleep`/`now` are injectable for tests."""
    _, day_end = local_day_bounds(report_date)
    status = send_report_for(page_views, order_store, report_store, report_date)
    while status == "failed" and _seconds_until(now(), day_end) > retry_seconds:
        sleep(retry_seconds)
        status = send_report_for(page_views, order_store, report_store, report_date)
    return status


def _seconds_until(now: datetime, target: datetime) -> float:
    """Real elapsed seconds from `now` to `target`. Plain `target - now`
    is WRONG when both share the same tzinfo: Python then subtracts wall
    clock times and ignores the UTC offset changing in between -- so a
    sleep spanning a daylight-saving change came out an hour off (the
    report went out at 19:00 on the October fall-back day, 21:00 in
    March). Going through UTC measures what the clock actually does."""
    return (target.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()


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
    menu_refresh.start_menu_refresh_scheduler(): never blocks the
    process from exiting, needs no coordination beyond the shared
    SQLite file."""

    def loop() -> None:
        last_send: datetime | None = None
        while True:
            now = datetime.now(TZINFO)
            # time.sleep() can wake a few ms EARLY (seen live: 19:59:59.995),
            # and a fast run (e.g. "already_claimed") can finish before the
            # send instant itself -- without this, the next target would be
            # the very same 20:00 and that evening would run twice.
            if last_send is not None and _seconds_until(now, last_send) >= 0:
                now = last_send
            next_send = _next_send_time(now, send_hour)
            time.sleep(max(0.0, _seconds_until(datetime.now(TZINFO), next_send)))
            last_send = next_send
            try:
                run_report_with_retries(page_views, order_store, report_store, next_send.date())
            except Exception:  # noqa: BLE001 -- one bad evening must never kill the thread for every evening after
                logger.warning("[DAILY-REPORT] unexpected failure sending report", exc_info=True)

    thread = threading.Thread(target=loop, daemon=True, name="daily-report")
    thread.start()
    return thread
