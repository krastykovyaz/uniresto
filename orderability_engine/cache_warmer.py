"""Proactively keeps the orderability/menu cache warm in the background,
so the live Restopolis fetch (the slow part -- see cache.py's own
docstring on why it's cached at all) is never something a real user's
click has to wait on.

Without this, the cache is only ever refreshed lazily: whoever's request
happens to land right after a TTL expires is the one who pays for a live
fetch, then everyone else for the next hour/15 minutes rides on their
result. That's fine for the DATA (still correct, still fresh), but it
means latency is uneven and falls on whoever's unlucky -- this module
moves that cost off the request path entirely by refreshing on its own
schedule, from a background thread, before any request needs it.

WARM_WINDOW_DAYS mirrors static/app.js's DATE_PICKER_DAYS (10) -- the
actual number of days the date picker ever asks about for one
restaurant, so warming exactly that window (no more, no less) keeps
every real "choose your day" load already warm without wasting fetches
on dates nothing in the UI ever requests.

WARM_INTERVAL_SECONDS (10 minutes) is shorter than both cache TTLs (the
15-minute orderability-status cache and the 1-hour week-HTML cache) on
purpose: waking up more often than the shortest TTL means an expiring
entry gets refreshed by THIS thread well before a real user's request
could land on the same gap, without hammering Restopolis (each wake-up
that finds everything still fresh is just a cache hit, no live fetch at
all -- see OrderabilityService.check_orderability/get_week_html).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from orderability_engine.service import OrderabilityService
from restopolis.models import RestaurantConfig

logger = logging.getLogger("orderability.cache_warmer")

WARM_WINDOW_DAYS = 10
WARM_INTERVAL_SECONDS = 10 * 60


def warm_cache_once(service: OrderabilityService, restaurants: list[RestaurantConfig]) -> None:
    """Calls check_orderability for every (restaurant, date) in the
    warm window -- the exact same call a real request makes, so this
    relies entirely on that method's own cache/TTL logic to decide
    whether a live fetch is actually needed. One bad restaurant/date
    (a Restopolis hiccup, a parse error) is logged and skipped, never
    allowed to stop the rest of the sweep."""
    today = service.today()
    for restaurant in restaurants:
        for offset in range(WARM_WINDOW_DAYS):
            target_date = today + timedelta(days=offset)
            try:
                service.check_orderability(restaurant, target_date)
            except Exception:  # noqa: BLE001 -- a warming sweep must never crash the background thread
                logger.warning("[CACHE-WARMER] failed to warm %s %s", restaurant.code, target_date, exc_info=True)


def start_cache_warmer(
    service: OrderabilityService,
    restaurants: list[RestaurantConfig],
    interval_seconds: int = WARM_INTERVAL_SECONDS,
) -> threading.Thread:
    """Warms once immediately (so the very first request after a fresh
    process start already sees a warm cache, not a cold one -- "hidden
    in the backend when first time open app"), then again every
    `interval_seconds` for as long as the process runs. A daemon thread:
    never blocks the process from exiting, and needs no coordination
    with other gunicorn worker processes -- they all share the same
    SQLite-backed cache file, so a wake-up that finds another worker
    already refreshed a given entry just sees a cache hit."""

    def loop() -> None:
        while True:
            warm_cache_once(service, restaurants)
            time.sleep(interval_seconds)

    thread = threading.Thread(target=loop, daemon=True, name="cache-warmer")
    thread.start()
    return thread
