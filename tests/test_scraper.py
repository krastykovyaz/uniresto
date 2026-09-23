import argparse
import datetime

import pytest

from restopolis.config import load_restaurants
from scraper import resolve_restaurants, resolve_target_dates, slug_for, week_start


def test_slug_for():
    assert slug_for("UDL-CKB-ALTIUS") == "altius"
    assert slug_for("UDL-CKB-BRASSERIE-JOHNS") == "brasserie-johns"


def test_week_start():
    # Wednesday 2026-09-23 -> Monday 2026-09-21
    assert week_start(datetime.date(2026, 9, 23)) == datetime.date(2026, 9, 21)
    # Monday itself
    assert week_start(datetime.date(2026, 9, 21)) == datetime.date(2026, 9, 21)
    # Sunday 2026-09-27 -> still Monday 2026-09-21
    assert week_start(datetime.date(2026, 9, 27)) == datetime.date(2026, 9, 21)


def _ns(**kwargs):
    defaults = dict(date=None, date_from=None, date_to=None)
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_resolve_target_dates_single_date():
    dates = resolve_target_dates(_ns(date=datetime.date(2026, 9, 24)))
    assert dates == [datetime.date(2026, 9, 24)]


def test_resolve_target_dates_range_is_inclusive():
    dates = resolve_target_dates(
        _ns(date_from=datetime.date(2026, 9, 21), date_to=datetime.date(2026, 9, 23))
    )
    assert dates == [
        datetime.date(2026, 9, 21),
        datetime.date(2026, 9, 22),
        datetime.date(2026, 9, 23),
    ]


def test_resolve_target_dates_both_given_is_an_error():
    with pytest.raises(SystemExit):
        resolve_target_dates(_ns(date=datetime.date(2026, 9, 24), date_from=datetime.date(2026, 9, 21)))


def test_resolve_target_dates_to_before_from_is_an_error():
    with pytest.raises(SystemExit):
        resolve_target_dates(
            _ns(date_from=datetime.date(2026, 9, 24), date_to=datetime.date(2026, 9, 21))
        )


def test_resolve_target_dates_defaults_to_today():
    dates = resolve_target_dates(_ns())
    assert dates == [datetime.date.today()]


def test_resolve_restaurants_defaults_to_all():
    all_restaurants = load_restaurants()
    result = resolve_restaurants(argparse.Namespace(restaurant=None), all_restaurants)
    assert len(result) == 2


def test_resolve_restaurants_filters_by_slug():
    all_restaurants = load_restaurants()
    result = resolve_restaurants(argparse.Namespace(restaurant=["altius"]), all_restaurants)
    assert len(result) == 1
    assert result[0].code == "UDL-CKB-ALTIUS"


def test_restaurants_yaml_building_field_is_loaded():
    # NOT a Restopolis field (see RestaurantConfig.building's docstring) --
    # confirmed directly by the user, purely a display label.
    all_restaurants = load_restaurants()
    assert all_restaurants["UDL-CKB-ALTIUS"].building == "Main building"
    assert all_restaurants["UDL-CKB-BRASSERIE-JOHNS"].building == "JFK building"
