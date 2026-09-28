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
#
# check_orderability() only ever performs a live fetch when refresh=True is
# passed explicitly (see service.py's own module docstring) -- these tests
# are about the parsing/decision logic, not caching itself, so they all pass
# refresh=True to simulate "the scheduler already ran" and get real parsed
# data back, same as a real request would see once menu_refresh.py has
# warmed the cache.
# ---------------------------------------------------------------------------


def test_available_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True)
    assert result.status == "available"
    assert result.reason is None
    assert result.menu_available is True
    assert result.ordering_available is True


def test_menu_present_but_restopolis_reservation_closed_is_still_available(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # Our courier buys food in person at the counter, not through
    # Restopolis's own reservation flow -- so its reservation button being
    # disabled must not block ordering as long as a menu exists.
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 23), refresh=True)
    assert result.status == "available"
    assert result.reason is None
    assert result.menu_available is True
    assert result.ordering_available is False


def test_no_menu_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 26), refresh=True)
    assert result.status == "no_menu"


def test_closed_date(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 28), refresh=True)
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
    result = service.check_orderability(altius_config, datetime.date(2026, 10, 20), refresh=True)
    assert result.status == "unknown"
    assert result.status != "closed"  # the critical distinction the task requires
    assert result.horizon_exceeded is True


def test_network_failure_is_unknown_not_closed_or_available(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today, fail=True)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True)
    assert result.status == "unknown"
    assert "could not be checked" in result.reason.lower()


def test_request_path_never_fetches_live_even_on_a_cold_cache(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # The whole point of menu_refresh.py's scheduled sweep: a plain
    # (refresh=False, the default -- what every real app.py route uses)
    # call against a totally empty cache must come back "unknown" rather
    # than ever touching the network itself.
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24))
    assert result.status == "unknown"
    assert client.calls == []


# ---------------------------------------------------------------------------
# OUR delivery rule combined with Restopolis's signal
# ---------------------------------------------------------------------------


def test_restopolis_orderable_but_our_deadline_passed(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    now = datetime.datetime(2026, 9, 24, 13, 15, tzinfo=TZINFO)  # after that same day's 13:00 deadline
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True, now=now)
    assert result.status == "available"          # Restopolis says yes
    assert result.our_delivery.available is False  # but our cutoff already passed


def test_early_cutoff_separately_reported_on_the_result(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    # 09:00: general (13:00) deadline hasn't passed, but the early
    # grill/BBQ/salmon-only one (08:00) has -- both are on the result,
    # never merged into one signal.
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    now = datetime.datetime(2026, 9, 24, 9, 0, tzinfo=TZINFO)
    result = service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True, now=now)
    assert result.our_delivery.available is True
    assert result.early_cutoff.available is False


# ---------------------------------------------------------------------------
# Caching / refresh / week-level fetch reuse
#
# refresh=True is now the ONLY thing that ever live-fetches (see
# service.py's module docstring) -- these tests use it to stand in for
# menu_refresh.py's scheduled sweep, then exercise the request path
# (refresh=False, the default) against whatever it wrote.
# ---------------------------------------------------------------------------


def test_second_check_is_served_from_cache(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    r1 = service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True)  # simulates the scheduler
    r2 = service.check_orderability(altius_config, datetime.date(2026, 9, 24))  # the request path
    assert r1.from_cache is False
    assert r2.from_cache is True
    assert client.calls == [0]  # only the explicit refresh actually fetched


def test_refresh_bypasses_cache(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True)
    r2 = service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True)
    assert r2.from_cache is False
    assert client.calls == [0, 0]  # fetched twice -- refresh=True never reuses what's cached


def test_two_dates_same_week_share_one_fetch(cache, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service.check_orderability(altius_config, datetime.date(2026, 9, 23), refresh=True)  # the one live fetch for week 0
    service.check_orderability(altius_config, datetime.date(2026, 9, 24))  # same week, request path
    service.check_orderability(altius_config, datetime.date(2026, 9, 26))  # same week, request path
    assert client.calls == [0]  # all three dates are in week offset 0 -> fetched once, by the explicit refresh


def test_menu_html_survives_a_new_service_instance_sharing_the_same_cache(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # Simulates a process restart (Part 22): the FIRST service's
    # in-process dict is what a real restart would wipe -- a brand-new
    # OrderabilityService, with its own fresh in-process dict but the
    # SAME underlying (SQLite) cache, must still find the menu HTML
    # there and never re-fetch it live.
    service1, client1 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service1.get_week_html(altius_config, datetime.date(2026, 9, 24), refresh=True)  # simulates the scheduler
    assert client1.calls == [0]

    service2, client2 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    html, weeks_ahead = service2.get_week_html(altius_config, datetime.date(2026, 9, 24))  # request path
    assert html == altius_html
    assert weeks_ahead == 0
    assert client2.calls == []  # never hit Restopolis -- served entirely from the persisted cache


def test_menu_html_refresh_still_bypasses_the_persisted_cache(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    service1, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service1.get_week_html(altius_config, datetime.date(2026, 9, 24), refresh=True)  # populate the persisted cache first

    service2, client2 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service2.get_week_html(altius_config, datetime.date(2026, 9, 24), refresh=True)
    assert client2.calls == [0]  # refresh=True skips straight past both caches


def test_expired_persisted_week_html_is_still_served_without_a_live_fetch(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    from orderability_engine.service import WEEK_HTML_TTL_SECONDS

    assert WEEK_HTML_TTL_SECONDS == 60 * 60

    # Age no longer gates a read at all (see cache.py's own module
    # docstring) -- even a persisted entry whose TTL has long since
    # "expired" is still served exactly as-is; only menu_refresh.py's
    # scheduled refresh=True sweep ever replaces it.
    service1, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service1._week_html_ttl = -1
    service1.get_week_html(altius_config, datetime.date(2026, 9, 24), refresh=True)  # writes an already-"expired" entry

    service2, client2 = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    html, _weeks_ahead = service2.get_week_html(altius_config, datetime.date(2026, 9, 24))
    assert html == altius_html
    assert client2.calls == []  # the "expired" persisted entry was still used, never re-fetched


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
    cache.set(stale, ttl_seconds=-1)

    # Change detection only ever runs during a real (refresh=True) fetch
    # -- the request path (refresh=False) just serves this stale entry
    # as-is (age doesn't gate it anymore) and never compares it against
    # anything, since it never re-fetches on its own. Only
    # menu_refresh.py's scheduled sweep can discover and log a real
    # change from Restopolis.
    with caplog.at_level(logging.INFO):
        service.check_orderability(altius_config, datetime.date(2026, 9, 24), refresh=True)

    assert "[CHANGED]" in caplog.text
    assert "service_end" in caplog.text
    assert "item_count" in caplog.text


# ---------------------------------------------------------------------------
# get_next_available_dates
#
# Like check_orderability, this never live-fetches on its own (it calls
# check_orderability with no explicit refresh) -- these tests warm the
# relevant weeks with refresh=True first, simulating menu_refresh.py's
# scheduled sweep having already run, then exercise the scan itself.
# ---------------------------------------------------------------------------


def test_get_next_available_dates_finds_available_days_only(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    service, _ = make_service(cache, altius_html, altius_closed_week_html, altius_config, fixture_today)
    service.check_orderability(altius_config, fixture_today, refresh=True)  # warms week 0 -- the only week these dates need
    now = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=TZINFO)
    results = service.get_next_available_dates(altius_config, current_datetime=now, count=2)
    # Wed 23.09 has a menu but Restopolis's own reservation is closed --
    # that no longer excludes it (see
    # test_menu_present_but_restopolis_reservation_closed_is_still_available
    # above), so it's the first result here, still before our 13:00 cutoff.
    assert [r.target_date for r in results] == [datetime.date(2026, 9, 23), datetime.date(2026, 9, 24)]
    assert all(r.status == "available" for r in results)


def test_get_next_available_dates_returns_fewer_than_requested_when_not_enough_are_available(
    cache, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # Only week offsets 0 and 1 are ever warmed here (matching what this
    # fake client has fixtures for); ask for far more days than can ever
    # come back "available".
    service, _ = make_service(
        cache, altius_html, altius_closed_week_html, altius_config, fixture_today, max_weeks_ahead=1
    )
    service.check_orderability(altius_config, fixture_today, refresh=True)  # warms week 0
    service.check_orderability(altius_config, fixture_today + datetime.timedelta(days=7), refresh=True)  # warms week 1 (closed)
    now = datetime.datetime(2026, 9, 23, 9, 0, tzinfo=TZINFO)
    results = service.get_next_available_dates(altius_config, current_datetime=now, count=10)
    # Real available days are only in week 0 -- week 1 (the synthetic
    # closed fixture) has none, and everything beyond what was warmed
    # reads as "unknown" (the request path never live-fetches, see
    # menu_refresh.py) rather than fabricating more available dates.
    assert len(results) < 10
    assert all(r.status == "available" for r in results)
