import datetime

from orderability_engine.cache import OrderabilityCache
from orderability_engine.menu_refresh import (
    REFRESH_TIMES,
    REFRESH_WINDOW_DAYS,
    _next_refresh_time,
    _seconds_until,
    refresh_all_once,
)
from orderability_engine.models import TZINFO
from orderability_engine.service import OrderabilityService
from restopolis.models import RestaurantConfig
from tests.orderability_helpers import FakeRestopolisClient


def make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today, client=None):
    client = client or FakeRestopolisClient(
        week_html_by_offset={0: altius_html, 1: altius_closed_week_html},
        max_weeks_ahead=6,
    )
    service = OrderabilityService(
        client=client,
        cache=OrderabilityCache(tmp_path / "cache.db", ttl_seconds=900),
        restaurants={altius_config.code: altius_config},
        today=fixture_today,
    )
    return service, client


# ---------------------------------------------------------------------------
# refresh_all_once
# ---------------------------------------------------------------------------


def test_refresh_all_once_covers_every_date_in_the_window(
    tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # This fake client only has real fixture HTML for weeks 0 and 1 --
    # weeks beyond that raise "no fixture registered" (a stand-in for a
    # genuine Restopolis gap), which refresh_all_once must log and skip
    # rather than let stop the rest of the sweep (see
    # test_refresh_all_once_survives_one_restaurant_raising below for
    # the same resilience against a harder failure). Every date within
    # the fixture-backed weeks must still come back real, cached data.
    service, _ = make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today)

    refresh_all_once(service, [altius_config])

    from orderability_engine.detector import weeks_ahead_for

    for offset in range(REFRESH_WINDOW_DAYS):
        target_date = fixture_today + datetime.timedelta(days=offset)
        if weeks_ahead_for(target_date, fixture_today) > 1:
            continue  # no fixture for this week -- correctly "unknown", not this test's concern
        result = service.check_orderability(altius_config, target_date)
        assert result.status != "unknown", f"{target_date} was never warmed"


def test_refresh_all_once_forces_a_live_fetch_even_if_something_is_already_cached(
    tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # Unlike the request path, this sweep IS the live-fetch mechanism --
    # it must never skip a date just because it happens to already be
    # cached from an earlier sweep (that would leave a real Restopolis
    # change undiscovered until the entry aged out, which -- per
    # cache.py's own docstring -- never happens anymore).
    service, client = make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today)
    refresh_all_once(service, [altius_config])
    first_sweep_calls = len(client.calls)

    refresh_all_once(service, [altius_config])

    assert len(client.calls) == first_sweep_calls * 2


def test_refresh_all_once_only_one_live_fetch_per_distinct_week(
    tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # REFRESH_WINDOW_DAYS (42) spans several Restopolis weeks -- warming
    # them must not cost 42 separate live fetches, only one per distinct
    # week actually spanned (get_week_html's own week-level cache, forced
    # fresh once per week by this sweep's own per-week dedup).
    service, client = make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today)

    refresh_all_once(service, [altius_config])

    from orderability_engine.detector import weeks_ahead_for

    expected_weeks = {
        weeks_ahead_for(fixture_today + datetime.timedelta(days=offset), fixture_today)
        for offset in range(REFRESH_WINDOW_DAYS)
    }
    assert len(client.calls) == len(expected_weeks)


def test_refresh_all_once_survives_one_restaurant_raising(
    tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    service, _ = make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today)
    checked = []
    real_check = service.check_orderability

    def flaky_check(restaurant, target_date, refresh=False, now=None):
        if restaurant.code == "BROKEN":
            raise RuntimeError("simulated bug")
        checked.append((restaurant.code, target_date))
        return real_check(restaurant, target_date, refresh=refresh, now=now)

    service.check_orderability = flaky_check
    broken_restaurant = RestaurantConfig(code="BROKEN", name="Broken", restaurant_id=0, service_id=0)

    refresh_all_once(service, [broken_restaurant, altius_config])

    assert len(checked) == REFRESH_WINDOW_DAYS
    assert all(code == altius_config.code for code, _ in checked)


# ---------------------------------------------------------------------------
# _next_refresh_time
# ---------------------------------------------------------------------------


def test_next_refresh_time_picks_the_soonest_upcoming_time_today():
    now = datetime.datetime(2026, 9, 28, 7, 0, tzinfo=TZINFO)  # between 06:00 and 09:00
    assert _next_refresh_time(now) == datetime.datetime(2026, 9, 28, 9, 0, tzinfo=TZINFO)


def test_next_refresh_time_rolls_to_tomorrows_earliest_time_once_all_of_todays_have_passed():
    now = datetime.datetime(2026, 9, 28, 22, 0, tzinfo=TZINFO)  # after 21:00, before midnight
    assert _next_refresh_time(now) == datetime.datetime(2026, 9, 29, 0, 0, tzinfo=TZINFO)


def test_next_refresh_time_exactly_at_a_scheduled_instant_looks_strictly_forward():
    # A restart landing exactly at a scheduled instant must not re-run an
    # already-completed slot -- next_refresh_time always looks forward.
    now = datetime.datetime(2026, 9, 28, 14, 0, tzinfo=TZINFO)
    assert _next_refresh_time(now) == datetime.datetime(2026, 9, 28, 18, 0, tzinfo=TZINFO)


def test_next_refresh_time_covers_every_configured_time_in_order():
    # Starting just after midnight, walking _next_refresh_time forward
    # len(REFRESH_TIMES) times must visit the rest of today's times in
    # order, then wrap to tomorrow's 00:00 -- a rotation of sorted(
    # REFRESH_TIMES), not sorted(REFRESH_TIMES) itself (that would start
    # from 00:00, which just happened, not from "now").
    now = datetime.datetime(2026, 9, 28, 0, 0, 1, tzinfo=TZINFO)  # just after midnight
    seen = []
    for _ in range(len(REFRESH_TIMES)):
        nxt = _next_refresh_time(now)
        seen.append(nxt.time())
        now = nxt
    today_s_remaining_times = sorted(t for t in REFRESH_TIMES if t != datetime.time(0, 0))
    assert seen == today_s_remaining_times + [datetime.time(0, 0)]


def test_seconds_until_spans_the_october_fall_back_correctly():
    # 2026-10-25 clocks go back (CEST -> CET) at 03:00: from 20:30 on the
    # 24th to 20:00 on the 25th is 24.5 REAL hours, not 23.5 -- plain
    # same-tz subtraction gets this wrong (see daily_report.py's own
    # copy of this exact function, which is where this was first caught
    # live, and its own identical test for this date).
    now = datetime.datetime(2026, 10, 24, 20, 30, tzinfo=TZINFO)
    target = datetime.datetime(2026, 10, 25, 20, 0, tzinfo=TZINFO)
    assert _seconds_until(now, target) == 24.5 * 3600
