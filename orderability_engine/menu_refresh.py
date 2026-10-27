"""Refreshes the orderability/menu cache from real Restopolis on a FIXED
daily schedule -- 06:00, 09:00, 14:00, 18:00, 21:00, 00:00 Europe/
Luxembourg (an explicit admin request, not a guessed cadence) -- and
nothing else ever does. A real user's request (see app.py's /api routes,
via OrderabilityService.check_orderability/get_week_html) now only ever
reads whatever this module last wrote, however old that is: it NEVER
performs a live Restopolis fetch itself, no matter how stale or even
entirely missing the cached entry is. That's the explicit tradeoff asked
for -- "do not load every time the menu for everyone, show the last
state for everyone" -- traded for a request path that's fast and
uniform for every visitor, at the cost of the very first entry (before
this scheduler's first sweep completes, e.g. moments after a fresh
deploy) staying "unknown" rather than triggering a fetch on someone's
click.

Replaces the earlier cache_warmer.py, which warmed on a rolling 10-
minute interval instead of fixed times, and only covered the first 10
days -- silently out of sync with static/app.js's DATE_PICKER_DAYS once
that grew to 42 (see this module's REFRESH_WINDOW_DAYS comment for why
that drift matters and how it's avoided this time).

Runs as a background thread, same shape as daily_report.py's -- started
once per gunicorn WORKER PROCESS. With 2 workers and no --preload, two
threads wake up at the same 6 times every day, and both at every reload
(a deploy): twice the requests to Restopolis, which is polite to nobody,
and two ~400 KB-per-row writers fighting over the same cache file. So a
sweep is run under a cross-process file lock (run_sweep_if_due): whichever
worker gets it sweeps; the other sees the lock taken, or sees that a sweep
finished after the moment IT was due to run, and skips.
"""

from __future__ import annotations

import fcntl
import logging
import os
import threading
import time
from datetime import datetime, time as dt_time, timedelta, timezone

from orderability_engine.detector import PastDateError, weeks_ahead_for
from orderability_engine.models import TZINFO
from orderability_engine.service import OrderabilityService
from restopolis.models import RestaurantConfig

logger = logging.getLogger("orderability.menu_refresh")

# Europe/Luxembourg, explicitly requested -- not evenly spaced, not a
# guessed cadence. Order doesn't matter; _next_refresh_time() below sorts
# by proximity to `now`, not by this list's own order.
REFRESH_TIMES = [dt_time(6, 0), dt_time(9, 0), dt_time(14, 0), dt_time(18, 0), dt_time(21, 0), dt_time(0, 0)]

# Mirrors static/app.js's DATE_PICKER_DAYS (42) -- the actual number of
# days the date picker ever asks about for one restaurant, so refreshing
# exactly that window (no more, no less) keeps every real "choose your
# day" load already warm without wasting fetches on dates nothing in the
# UI ever requests. IMPORTANT: keep these two in sync by hand -- one is
# JS, one is Python, there is no single shared source of truth between
# them. This drifted once already (the OLD cache_warmer.py's
# WARM_WINDOW_DAYS stayed at 10 after DATE_PICKER_DAYS grew to 42,
# silently leaving days 11-42 never proactively warmed) -- that's part
# of why real requests were slow before this module existed -- and again
# when yesterday was added to the picker (DATE_PICKER_PAST_DAYS) without
# being added here.
REFRESH_WINDOW_DAYS = 42
# Mirrors static/app.js's DATE_PICKER_PAST_DAYS: the picker also shows
# yesterday (greyed out as CLOSED, its menu still opens read-only), so the
# sweep keeps yesterday's status warm on the same schedule as everything
# else. On a Monday yesterday is Sunday, which is in a week Restopolis's
# clamped PreviousWeek can never reach -- refresh_all_once() skips it then.
REFRESH_PAST_DAYS = 1


def refresh_all_once(service: OrderabilityService, restaurants: list[RestaurantConfig]) -> None:
    """Live-refreshes every (restaurant, date) in the window -- always a
    real Restopolis fetch (refresh=True), since the entire point of this
    sweep is "download the latest", unlike the old cache_warmer's
    TTL-driven warming. Only ONE live fetch per distinct Restopolis week
    actually spanned per restaurant (matching get_week_html's own one-
    fetch-per-week shape): the first date seen in a given week forces a
    fetch, and every other date in the same week is RE-PARSED (reparse=True)
    out of the week HTML that fetch just stored -- not fetched again, and not
    answered from its old cached status either, which would keep a date's
    first-ever result (weeks old) until the day was over. One bad restaurant/date
    (a Restopolis hiccup, a parse error) is logged and skipped, never
    allowed to stop the rest of the sweep."""
    today = service.today()
    for restaurant in restaurants:
        refreshed_weeks: set[int] = set()
        for offset in range(-REFRESH_PAST_DAYS, REFRESH_WINDOW_DAYS):
            target_date = today + timedelta(days=offset)
            try:
                weeks_ahead = weeks_ahead_for(target_date, today)
                force = weeks_ahead not in refreshed_weeks
                refreshed_weeks.add(weeks_ahead)
                service.check_orderability(restaurant, target_date, refresh=force, reparse=not force)
            except PastDateError:
                continue  # yesterday, when it falls in a week before the current one -- unreachable, not a failure
            except Exception:  # noqa: BLE001 -- a refresh sweep must never crash the background thread
                logger.warning("[MENU-REFRESH] failed to refresh %s %s", restaurant.code, target_date, exc_info=True)


def _sweep_lock_path(service: OrderabilityService) -> str | None:
    path = getattr(service.cache, "db_path", None)
    return None if not path or path == ":memory:" else f"{path}.sweep"


def run_sweep_if_due(service: OrderabilityService, restaurants: list[RestaurantConfig], due_at: datetime) -> bool:
    """Runs refresh_all_once() unless another worker process already did the sweep that was due at `due_at`
    (True if this call swept). `due_at` is the instant this worker's sweep was meant to happen -- the scheduled
    time, or for the startup sweep the moment the worker started. The lock file also holds when a sweep last
    finished: a sweep that ended after `due_at` covers it (for a startup sweep that is the whole point of
    sweeping at all -- a deploy still gets exactly one fresh sweep), while one that ended before it does not."""
    lock_path = _sweep_lock_path(service)
    if lock_path is None:  # in-memory cache (tests, dev): nobody to share a sweep with
        refresh_all_once(service, restaurants)
        return True
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info("[MENU-REFRESH] another worker is sweeping right now, skipping this one")
            return False
        try:
            finished = float(lock.read().strip() or 0)
        except ValueError:
            finished = 0.0
        if finished >= due_at.timestamp():
            logger.info("[MENU-REFRESH] a sweep already finished after %s, skipping this one", due_at.isoformat())
            return False
        refresh_all_once(service, restaurants)
        lock.seek(0)
        lock.truncate()
        lock.write(repr(time.time()))
        lock.flush()
        return True


def _seconds_until(now: datetime, target: datetime) -> float:
    """Real elapsed seconds from `now` to `target`. Plain `target - now`
    is WRONG when both share the same tzinfo: Python then subtracts wall
    clock times and ignores the UTC offset changing in between -- see
    daily_report.py's own copy of this exact function for the live bug
    (a send an hour off across a DST change) that first caught this."""
    return (target.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()


def _next_refresh_time(now: datetime) -> datetime:
    """The soonest of today's/tomorrow's REFRESH_TIMES that's still
    strictly after `now` -- each of the 6 times gets its own candidate
    (today at that time, or tomorrow if today's has already passed), and
    this returns whichever candidate is earliest."""
    candidates = []
    for t in REFRESH_TIMES:
        candidate = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)


def start_menu_refresh_scheduler(
    service: OrderabilityService,
    restaurants: list[RestaurantConfig],
) -> threading.Thread:
    """Refreshes once immediately (so the very first request after a
    fresh process start already sees real data, not "unknown" for
    everyone until the next scheduled time), then sleeps until each of
    REFRESH_TIMES in turn, forever. A daemon thread: never blocks the
    process from exiting. The gunicorn workers share the same SQLite-backed
    cache file, so one worker's sweep is what the others' requests read too;
    run_sweep_if_due() makes sure each sweep is done by only one of them."""

    started_at = datetime.now(TZINFO)

    def loop() -> None:
        try:
            run_sweep_if_due(service, restaurants, started_at)
        except Exception:  # noqa: BLE001 -- the startup sweep must never stop the thread from scheduling later ones
            logger.warning("[MENU-REFRESH] startup sweep failed", exc_info=True)

        last_run: datetime | None = None
        while True:
            now = datetime.now(TZINFO)
            # time.sleep() can wake a few ms EARLY, and a fast sweep can
            # finish before the target instant itself -- without this,
            # the next target would be the very same time and that slot
            # would run twice (same reasoning as daily_report.py's own
            # last_send tracking).
            if last_run is not None and _seconds_until(now, last_run) >= 0:
                now = last_run
            next_run = _next_refresh_time(now)
            time.sleep(max(0.0, _seconds_until(datetime.now(TZINFO), next_run)))
            last_run = next_run
            try:
                run_sweep_if_due(service, restaurants, next_run)
            except Exception:  # noqa: BLE001 -- one bad sweep must never kill the thread for every sweep after
                logger.warning("[MENU-REFRESH] scheduled sweep failed", exc_info=True)

    thread = threading.Thread(target=loop, daemon=True, name="menu-refresh")
    thread.start()
    return thread
