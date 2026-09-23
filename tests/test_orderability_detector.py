import datetime

import pytest

from orderability_engine.detector import (
    HorizonExceededError,
    PastDateError,
    fetch_week_html_for_date,
    get_restopolis_day_status,
    parse_day_status_from_html,
    weeks_ahead_for,
)
from restopolis.parser import MenuParseError
from tests.orderability_helpers import FakeRestopolisClient


# ---------------------------------------------------------------------------
# weeks_ahead_for / PastDateError
# ---------------------------------------------------------------------------


def test_weeks_ahead_for_same_week_is_zero(fixture_today):
    assert weeks_ahead_for(datetime.date(2026, 9, 24), today=fixture_today) == 0


def test_weeks_ahead_for_next_week_is_one(fixture_today):
    assert weeks_ahead_for(datetime.date(2026, 9, 28), today=fixture_today) == 1


def test_weeks_ahead_for_past_date_raises(fixture_today):
    with pytest.raises(PastDateError):
        weeks_ahead_for(datetime.date(2026, 9, 1), today=fixture_today)


def test_weeks_ahead_for_yesterday_in_same_week_is_not_past(fixture_today):
    # fixture_today is Wed 23 Sep; Mon 21 is in the same week and is
    # reachable (Restopolis clamps PreviousWeek at the current *week*, not
    # at "today" within the week).
    assert weeks_ahead_for(datetime.date(2026, 9, 21), today=fixture_today) == 0


# ---------------------------------------------------------------------------
# fetch_week_html_for_date / HorizonExceededError
# ---------------------------------------------------------------------------


def test_fetch_week_html_for_date_past_raises_without_network_call(fixture_today):
    client = FakeRestopolisClient(week_html_by_offset={})
    with pytest.raises(PastDateError):
        fetch_week_html_for_date(client, object(), datetime.date(2026, 9, 1), today=fixture_today)
    assert client.calls == []  # never even tried to hit the network


def test_fetch_week_html_for_date_beyond_horizon_raises(altius_html, fixture_today, altius_config):
    client = FakeRestopolisClient(week_html_by_offset={0: altius_html}, max_weeks_ahead=0)
    with pytest.raises(HorizonExceededError):
        fetch_week_html_for_date(client, altius_config, datetime.date(2026, 10, 5), today=fixture_today)


def test_fetch_week_html_for_date_within_range_returns_html(altius_html, fixture_today, altius_config):
    client = FakeRestopolisClient(week_html_by_offset={0: altius_html})
    html = fetch_week_html_for_date(client, altius_config, datetime.date(2026, 9, 24), today=fixture_today)
    assert html == altius_html


# ---------------------------------------------------------------------------
# parse_day_status_from_html: the four (menu, ordering) signal combinations
# ---------------------------------------------------------------------------


def test_status_available_menu_and_ordering_open(altius_html, altius_config):
    status = parse_day_status_from_html(altius_html, altius_config, datetime.date(2026, 9, 24))
    assert status.menu_available is True
    assert status.ordering_available is True
    assert status.reservation_signal_text == "Réserver"
    assert status.service_start == "11:00"
    assert status.service_end == "14:30"
    assert status.item_count > 0


def test_status_ordering_closed_menu_present_ordering_shut(altius_html, altius_config):
    # Wed 23 Sep is "today" in this fixture: menu exists, reservation is closed.
    status = parse_day_status_from_html(altius_html, altius_config, datetime.date(2026, 9, 23))
    assert status.menu_available is True
    assert status.ordering_available is False
    assert status.reservation_signal_text == "Réservation clôturée"


def test_status_no_menu_ordering_still_open(altius_html, altius_config):
    # Sat 26 Sep: no menu items, but the reservation button is enabled.
    status = parse_day_status_from_html(altius_html, altius_config, datetime.date(2026, 9, 26))
    assert status.menu_available is False
    assert status.ordering_available is True
    assert status.item_count == 0


def test_status_closed_no_menu_and_ordering_shut(altius_closed_week_html, altius_config):
    status = parse_day_status_from_html(altius_closed_week_html, altius_config, datetime.date(2026, 9, 28))
    assert status.menu_available is False
    assert status.ordering_available is False


def test_menu_hash_changes_when_signals_change(altius_html, altius_config):
    available = parse_day_status_from_html(altius_html, altius_config, datetime.date(2026, 9, 24))
    closed = parse_day_status_from_html(altius_html, altius_config, datetime.date(2026, 9, 23))
    assert available.menu_hash != closed.menu_hash


def test_wrong_date_not_in_week_raises(altius_html, altius_config):
    with pytest.raises(MenuParseError):
        parse_day_status_from_html(altius_html, altius_config, datetime.date(2026, 10, 5))


def test_restopolis_order_deadline_is_always_none(altius_html, altius_config):
    # Documented finding: no cutoff *time* is exposed publicly anywhere.
    for d in [datetime.date(2026, 9, 23), datetime.date(2026, 9, 24), datetime.date(2026, 9, 26)]:
        status = parse_day_status_from_html(altius_html, altius_config, d)
        assert status.restopolis_order_deadline is None


# ---------------------------------------------------------------------------
# get_restopolis_day_status: end-to-end convenience wrapper
# ---------------------------------------------------------------------------


def test_get_restopolis_day_status_end_to_end(altius_html, fixture_today, altius_config):
    client = FakeRestopolisClient(week_html_by_offset={0: altius_html})
    status = get_restopolis_day_status(client, altius_config, datetime.date(2026, 9, 24), today=fixture_today)
    assert status.menu_available is True
    assert status.ordering_available is True
