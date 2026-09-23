"""Orderability Service: combines the Restopolis Availability Detector,
the cache, and OUR delivery rule into one structured decision.

Status decision table (see README.md "Status decision table" for the
full rationale and the exact evidence behind each row -- nothing here is
guessed):

    weeks_ahead < 0                                  -> past_date
    Restopolis fetch/parse fails, or horizon exceeded -> unknown
    menu_available is None or ordering_available None -> unknown
    menu=False, ordering=False                        -> closed
    menu=True,  ordering=False                        -> ordering_closed
    menu=False, ordering=True                         -> no_menu
    menu=True,  ordering=True                         -> available

`not_yet_published` is a recognized status value (see orderability/models.py)
but is intentionally never emitted automatically: Restopolis's public page
does not expose any signal that distinguishes "this weekday's menu simply
isn't uploaded yet" from "this restaurant doesn't serve on this date"
(both render as `no-products` with an otherwise-open reservation button,
i.e. `no_menu`). Inventing that distinction would violate the "don't
guess" requirement. If Restopolis ever exposes such a signal (e.g. a
different placeholder message), wire it in here.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from restopolis.client import RestopolisClient, RestopolisError
from restopolis.config import load_restaurants
from restopolis.models import RestaurantConfig
from restopolis.parser import MenuParseError

from orderability_engine.cache import OrderabilityCache
from orderability_engine.delivery_rules import DEFAULT_RULE_CONFIG, DeliveryRuleConfig, evaluate_our_delivery
from orderability_engine.detector import (
    HorizonExceededError,
    PastDateError,
    fetch_week_html_for_date,
    parse_day_status_from_html,
    weeks_ahead_for,
)
from orderability_engine.models import OrderabilityResult, RestopolisDayStatus, TIMEZONE_NAME, TZINFO

logger = logging.getLogger("orderability.service")

_CHANGE_TRACKED_FIELDS = ["menu_available", "ordering_available", "service_start", "service_end", "item_count"]


def _log_changes(restaurant_code: str, target_date: date, old: RestopolisDayStatus | None, new: RestopolisDayStatus) -> None:
    if old is None:
        return
    for f in _CHANGE_TRACKED_FIELDS:
        old_val = getattr(old, f)
        new_val = getattr(new, f)
        if old_val != new_val:
            logger.info(
                "[CHANGED]\n%s\n%s\n%s:\n%s -> %s",
                restaurant_code, target_date, f, old_val, new_val,
            )


def _status_from_signals(menu_available: bool | None, ordering_available: bool | None) -> tuple[str, str | None]:
    if menu_available is None or ordering_available is None:
        return "unknown", "Restopolis returned this date's page but a signal (menu or reservation state) could not be read from it."
    if not menu_available and not ordering_available:
        return "closed", "Restopolis has no menu and reservation is closed for this date."
    if menu_available and not ordering_available:
        return "ordering_closed", "Restopolis has a menu for this date but its reservation button is disabled (closed)."
    if not menu_available and ordering_available:
        return "no_menu", "Restopolis shows no menu items for this date, though its reservation button is still open."
    return "available", None


WEEK_HTML_TTL_SECONDS = 60 * 60  # 1 hour -- the menu itself changes far less often than open/closed signals


class OrderabilityService:
    def __init__(
        self,
        client: RestopolisClient | None = None,
        cache: OrderabilityCache | None = None,
        restaurants: dict[str, RestaurantConfig] | None = None,
        delivery_config: DeliveryRuleConfig = DEFAULT_RULE_CONFIG,
        cache_ttl_seconds: int | None = None,
        menu_cache_ttl_seconds: int | None = None,
        today: date | None = None,
    ):
        self.client = client or RestopolisClient()
        self.cache = cache if cache is not None else OrderabilityCache(
            ttl_seconds=cache_ttl_seconds if cache_ttl_seconds is not None else 15 * 60
        )
        self.restaurants = restaurants or load_restaurants()
        self.delivery_config = delivery_config
        # Overridable so tests can pin "today" instead of depending on the
        # real system clock (which would make date-relative fixtures --
        # e.g. "the current week" -- flaky depending on when tests run).
        self._today_override = today

        # In-process cache of raw week HTML, keyed by (restaurant_code,
        # weeks_ahead). Several dates in the same week (e.g. a scan in
        # get_next_available_dates, or a --from/--to CLI range) would
        # otherwise each trigger their own full fetch_week_html session --
        # this collapses them into one fetch per (restaurant, week) within
        # THIS process. Behind it sits self.cache's SQLite
        # week_html_cache table (Part 22), which persists the same data
        # across process restarts -- without that, every restart wiped
        # this dict and the next menu load re-fetched live from
        # Restopolis, however recently the menu had actually been
        # fetched. Its own TTL is deliberately separate from
        # cache_ttl_seconds (the 15-minute orderability-status TTL above):
        # the menu changes far less often than open/closed signals do.
        self._week_html_cache: dict[tuple[str, int], tuple[str, float]] = {}
        self._week_html_ttl = menu_cache_ttl_seconds if menu_cache_ttl_seconds is not None else WEEK_HTML_TTL_SECONDS

    def _today(self) -> date:
        return self._today_override or date.today()

    def get_week_html(self, restaurant: RestaurantConfig, target_date: date, refresh: bool = False) -> tuple[str, int]:
        """Raises PastDateError / HorizonExceededError. Returns (html, weeks_ahead).

        Checked in order: (1) the in-process dict (cheapest, no I/O at
        all), (2) the persistent SQLite cache (self.cache), which is what
        makes the menu survive a process restart without a live
        Restopolis fetch, (3) only then a real live fetch -- which is
        stored back into BOTH caches so the next call, in this process or
        a future one, hits (1) or (2) instead. `refresh=True` skips
        straight to (3), matching check_orderability's own --refresh."""
        today = self._today()
        weeks_ahead = weeks_ahead_for(target_date, today)
        key = (restaurant.code, weeks_ahead)

        if not refresh:
            cached = self._week_html_cache.get(key)
            if cached is not None:
                html, expires_at = cached
                if time.monotonic() < expires_at:
                    return html, weeks_ahead

            persisted = self.cache.get_week_html(restaurant.code, weeks_ahead)
            if persisted is not None:
                self._week_html_cache[key] = (persisted, time.monotonic() + self._week_html_ttl)
                return persisted, weeks_ahead

        html = fetch_week_html_for_date(self.client, restaurant, target_date, today)
        self._week_html_cache[key] = (html, time.monotonic() + self._week_html_ttl)
        self.cache.set_week_html(restaurant.code, weeks_ahead, html, ttl_seconds=self._week_html_ttl)
        return html, weeks_ahead

    def check_orderability(
        self,
        restaurant: RestaurantConfig,
        target_date: date,
        refresh: bool = False,
        now: datetime | None = None,
    ) -> OrderabilityResult:
        now = now or datetime.now(TZINFO)
        logger.info("[CHECK]\n%s\n%s", restaurant.code, target_date)

        previous = self.cache.get_raw(restaurant.code, target_date)

        cached = None if refresh else self.cache.get(restaurant.code, target_date)
        if cached is not None:
            status, checked_at = cached
            logger.info("[CACHE] hit for %s %s (checked_at=%s)", restaurant.code, target_date, checked_at)
            return self._build_result(restaurant, target_date, status, now, from_cache=True)

        try:
            html, _weeks_ahead = self.get_week_html(restaurant, target_date, refresh=refresh)
            status = parse_day_status_from_html(html, restaurant, target_date)
        except PastDateError as exc:
            return self._error_result(restaurant, target_date, now, "past_date", str(exc))
        except HorizonExceededError as exc:
            return self._error_result(restaurant, target_date, now, "unknown", str(exc), horizon_exceeded=True)
        except (RestopolisError, MenuParseError) as exc:
            logger.error("[UNKNOWN]\nCould not determine Restopolis ordering status.\n%s", exc)
            return self._error_result(
                restaurant, target_date, now, "unknown",
                f"Restopolis could not be checked: {exc}",
            )

        _log_changes(restaurant.code, target_date, previous, status)
        self.cache.set(status)

        logger.info(
            "[RESTOPOLIS]\nrestaurant_open=%s\nmenu_available=%s\nordering_available=%s",
            True, status.menu_available, status.ordering_available,
        )

        return self._build_result(restaurant, target_date, status, now, from_cache=False)

    def _build_result(
        self,
        restaurant: RestaurantConfig,
        target_date: date,
        status: RestopolisDayStatus,
        now: datetime,
        from_cache: bool,
    ) -> OrderabilityResult:
        final_status, reason = _status_from_signals(status.menu_available, status.ordering_available)
        if status.fetch_error:
            final_status, reason = "unknown", status.fetch_error

        our_delivery = evaluate_our_delivery(
            target_date, status.ordering_available, status.menu_available, now=now, config=self.delivery_config
        )
        logger.info(
            "[OUR RULE]\ndeadline=%s\ndelivery_orderable=%s",
            self.delivery_config.cutoff_time, our_delivery.available,
        )
        logger.info("[RESULT]\n%s", final_status.upper())

        return OrderabilityResult(
            restaurant_code=restaurant.code,
            restaurant_name=restaurant.name,
            target_date=target_date,
            timezone=TIMEZONE_NAME,
            restaurant_open=True if status.menu_available is not None or status.ordering_available is not None else None,
            menu_available=status.menu_available,
            ordering_available=status.ordering_available,
            order_deadline=status.restopolis_order_deadline,
            service_start=status.service_start,
            service_end=status.service_end,
            status=final_status,
            reason=reason,
            our_delivery=our_delivery,
            checked_at=now,
            from_cache=from_cache,
        )

    def _error_result(
        self,
        restaurant: RestaurantConfig,
        target_date: date,
        now: datetime,
        status: str,
        reason: str,
        horizon_exceeded: bool = False,
    ) -> OrderabilityResult:
        logger.info("[RESULT]\n%s", status.upper())
        our_delivery = evaluate_our_delivery(target_date, None, None, now=now, config=self.delivery_config)
        return OrderabilityResult(
            restaurant_code=restaurant.code,
            restaurant_name=restaurant.name,
            target_date=target_date,
            timezone="Europe/Luxembourg",
            restaurant_open=None,
            menu_available=None,
            ordering_available=None,
            order_deadline=None,
            service_start=None,
            service_end=None,
            status=status,
            reason=reason,
            our_delivery=our_delivery,
            checked_at=now,
            from_cache=False,
            horizon_exceeded=horizon_exceeded,
        )

    def get_next_available_dates(
        self,
        restaurant: RestaurantConfig,
        current_datetime: datetime | None = None,
        count: int = 5,
        max_days_to_scan: int = 60,
    ) -> list[OrderabilityResult]:
        """Scan forward day by day, actually checking Restopolis for each
        candidate (via check_orderability, so cache/refresh still apply),
        keeping only status == 'available'. Stops once `count` are found,
        `max_days_to_scan` calendar days have been tried, or Restopolis's
        browsable horizon is exhausted (status stays 'unknown' because of
        HorizonExceededError) for several consecutive days."""
        now = current_datetime or datetime.now(TZINFO)
        start = now.date()

        found: list[OrderabilityResult] = []
        for offset in range(max_days_to_scan):
            candidate = start + timedelta(days=offset)
            result = self.check_orderability(restaurant, candidate)

            if result.horizon_exceeded:
                # Horizon is a fixed number of weeks ahead of "today" (see
                # detector.py), so once one date exceeds it every later
                # date will too -- no point scanning further.
                logger.info(
                    "[INFO] Stopping search: reached Restopolis's browsable horizon at %s",
                    candidate,
                )
                break

            if result.status == "available":
                found.append(result)
                if len(found) >= count:
                    break

        return found

    def close(self) -> None:
        self.cache.close()
