import datetime
import logging

import pytest

from orderability_engine.cache import OrderabilityCache
from orderability_engine.models import TZINFO
from orderability_engine.service import OrderabilityService
from tests.orderability_helpers import FakeRestopolisClient


@pytest.fixture
def cache(tmp_path):
    c = OrderabilityCache(tmp_path / "cache.db", ttl_seconds=900)
    yield c
    c.close()


def make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today, fail=False, max_weeks_ahead=6):
    client = FakeRestopolisClient(
        week_html_by_offset={0: altius_html, 1: altius_closed_week_html},
        max_weeks_ahead=max_weeks_ahead,
        fail=fail,
    )
    service = OrderabilityService(
        client=client,
        cache=cache,
        restaurants={altius_config.code: altius_config},
        today=fixture_today,
    )
    return service, client


# ---------------------------------------------------------------------------
# Status decision table, end to end
# ---------------------------------------------------------------------------


def test_available_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24))
    assert result.status == "available"
    assert result.reason is None
    assert result.menu_available is True
    assert result.ordering_available is True


def test_ordering_closed_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 23))
    assert result.status == "ordering_closed"
    assert "reservation button is disabled" in result.reason


def test_no_menu_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 26))
    assert result.status == "no_menu"


def test_closed_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 28))
    assert result.status == "closed"


def test_past_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 1))
    assert result.status == "past_date"
    assert client.calls == []  # never hit "the network" for a date we already know is unreachable


def test_horizon_exceeded_is_unknown_not_closed(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(
        cache, altius_html, altius_closed_week_html, altius_config, fixture_today, max_weeks_ahead=1
    )
    result = service.check_orderability(altius_config, datetime.date(2026, 10, 20))
    assert result.status == "unknown"
    assert result.status != "closed"  # the critical distinction the task requires
    assert result.horizon_exceeded is True


def test_network_failure_is_unknown_not_closed_or_available(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today, fail=True)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24))
    assert result.status == "unknown"
    assert "could not be checked" in result.reason.lower()


# ---------------------------------------------------------------------------
# OUR delivery rule combined with Restopolis's signal
# ---------------------------------------------------------------------------


def test_restopolis_orderable_but_our_deadline_passed(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    now = datetime.datetime(2026, 9, 24, 8, 15, tzinfo=TZINFO)  # after that same day's 08:00 deadline
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24), now=now)
    assert result.status == "available"          # Restopolis says yes
    assert result.our_delivery.available is False  # but our cutoff already passed


# ---------------------------------------------------------------------------
# Caching / refresh / week-level fetch reuse
# ---------------------------------------------------------------------------


def test_second_check_is_served_from_cache(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    r1 = service.check_orderability(altius_config, datetime.date(2026, 9, 24))
    r2 = service.check_orderability(altius_config, datetime.date(2026, 9, 24))
    assert r1.from_cache is False
    assert r2.from_cache is True
    assert client.calls == [0]  # only one real fetch


def test_refresh_bypasses_cache(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service.check_orderability(altius_config, datetime.date(2026, 9, 24))
    r2 = service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True)
    assert r2.from_cache is False
    assert client.calls == [0, 0]  # fetched twice


def test_two_dates_same_week_share_one_fetch(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service.check_orderability(altius_config, datetime.date(2026, 9, 23))
    service.check_orderability(altius_config, datetime.date(2026, 9, 24))
    service.check_orderability(altius_config, datetime.date(2026, 9, 26))
    assert client.calls == [0]  # all three dates are in week offset 0 -> fetched once


def test_menu_html_survives_a_new_service_instance_sharing_the_same_cache(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # Simulates a process restart (Part 22): the FIRST service's
    # in-process dict is what a real restart would wipe -- a brand-new
    # OrderabilityService, with its own fresh in-process dict but the
    # SAME underlying (SQLite) cache, must still find the menu HTML
    # there and never re-fetch it live.
    service1, client1 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service1.get_week_html(altius_config, datetime.date(2026, 9, 24))
    assert client1.calls == [0]

    service2, client2 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    html, weeks_ahead = service2.get_week_html(altius_config, datetime.date(2026, 9, 24))
    assert html == altius_html
    assert weeks_ahead == 0
    assert client2.calls == []  # never hit Restopolis -- served entirely from the persisted cache


def test_menu_html_refresh_still_bypasses_the_persisted_cache(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    service1, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service1.get_week_html(altius_config, datetime.date(2026, 9, 24))

    service2, client2 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service2.get_week_html(altius_config, datetime.date(2026, 9, 24), refresh=True)
    assert client2.calls == [0]  # refresh=True skips straight past both caches


def test_menu_cache_ttl_is_configurable_and_defaults_to_one_hour(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    from orderability_engine.service import WEEK_HTML_TTL_SECONDS

    assert WEEK_HTML_TTL_SECONDS == 60 * 60

    # An already-expired menu-cache TTL must force a fresh live fetch even
    # though the (persisted) entry technically exists.
    service1, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service1._week_html_ttl = -1
    service1.get_week_html(altius_config, datetime.date(2026, 9, 24))  # writes an already-expired entry

    service2, client2 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service2.get_week_html(altius_config, datetime.date(2026, 9, 24))
    assert client2.calls == [0]  # the expired persisted entry was correctly ignored


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------


def test_change_is_logged_when_signal_differs_from_cache(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today, caplog
):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    # Seed the cache with a stale value that disagrees with what the fixture will report.
    from orderability_engine.models import RestopolisDayStatus

    stale = RestopolisDayStatus(
        restaurant_code=altius_config.code,
        restaurant_name=altius_config.name,
        target_date=datetime.date(2026, 9, 24),
        menu_available=True,
        ordering_available=True,
        reservation_signal_text="Réserver",
        service_start="11:00",
        service_end="99:99",  # deliberately wrong, to force a detectable change
        restopolis_order_deadline=None,
        item_count=999,
        menu_hash="stale",
        source_url="https://example.test/Menu",
    )
    cache.set(stale, ttl_seconds=-1)  # expired, so the next check() call re-fetches

    with caplog.at_level(logging.INFO):
        service.check_orderability(altius_config, datetime.date(2026, 9, 24))

    assert "[CHANGED]" in caplog.text
    assert "service_end" in caplog.text
    assert "item_count" in caplog.text


# ---------------------------------------------------------------------------
# get_next_available_dates
# ---------------------------------------------------------------------------


def test_get_next_available_dates_finds_available_days_only(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    now = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=TZINFO)
    results = service.get_next_available_dates(altius_config, current_datetime=now, count=2)
    assert [r.target_date for r in results] == [datetime.date(2026, 9, 24), datetime.date(2026, 9, 25)]
    assert all(r.status == "available" for r in results)


def test_get_next_available_dates_stops_at_horizon_without_fabricating(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # Only week offsets 0 and 1 have fixtures; ask for far more than exist.
    service, _ = make_service(
        cache, altius_html, altius_closed_week_html, altius_config, fixture_today, max_weeks_ahead=1
    )
    now = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=TZINFO)
    results = service.get_next_available_dates(altius_config, current_datetime=now, count=10)
    # Real available days in week 0 (Thu/Fri) -- week 1 (the synthetic
    # fixture) is entirely closed, and the scan should stop at the horizon
    # rather than returning fabricated dates.
    assert len(results) < 10
    assert all(r.status == "available" for r in results)
