import datetime

from orderability_engine.cache import OrderabilityCache
from orderability_engine.cache_warmer import WARM_WINDOW_DAYS, warm_cache_once
from orderability_engine.service import OrderabilityService
from restopolis.models import RestaurantConfig
from tests.orderability_helpers import FakeRestopolisClient


def make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today, client=None):
    client = client or FakeRestopolisClient(week_html_by_offset={0: altius_html, 1: altius_closed_week_html})
    service = OrderabilityService(
        client=client,
        cache=OrderabilityCache(tmp_path / "cache.db", ttl_seconds=900),
        restaurants={altius_config.code: altius_config},
        today=fixture_today,
    )
    return service, client


def test_warm_cache_once_checks_every_date_in_the_window(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today):
    service, client = make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today)

    warm_cache_once(service, [altius_config])

    # Every date in the window resolved to a real status (not "unknown"
    # from never having been checked at all) -- confirms the sweep
    # actually reached all WARM_WINDOW_DAYS days, not just the first one.
    for offset in range(WARM_WINDOW_DAYS):
        target_date = fixture_today + datetime.timedelta(days=offset)
        cached = service.cache.get(altius_config.code, target_date)
        assert cached is not None


def test_warm_cache_once_reuses_the_cache_not_one_live_fetch_per_date(
    tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today
):
    # WARM_WINDOW_DAYS (10) days all fall within the same 1-2 Restopolis
    # weeks -- warming them must not cost 10 separate live fetches, only
    # one per distinct week actually spanned (see get_week_html's own
    # in-process + persisted cache).
    service, client = make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today)

    warm_cache_once(service, [altius_config])

    assert len(client.calls) <= 2


def test_warm_cache_once_survives_one_restaurant_raising(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today):
    # check_orderability() already turns ordinary Restopolis errors into
    # an "unknown"-status result rather than raising (see service.py) --
    # so this simulates the kind of genuine bug warm_cache_once must
    # still be resilient to: something raising an exception it never
    # expected to catch.
    service, _ = make_service(tmp_path, altius_html, altius_closed_week_html, altius_config, fixture_today)
    checked = []
    real_check = service.check_orderability

    def flaky_check(restaurant, target_date):
        if restaurant.code == "BROKEN":
            raise RuntimeError("simulated bug")
        checked.append((restaurant.code, target_date))
        return real_check(restaurant, target_date)

    service.check_orderability = flaky_check
    broken_restaurant = RestaurantConfig(code="BROKEN", name="Broken", restaurant_id=0, service_id=0)

    warm_cache_once(service, [broken_restaurant, altius_config])

    assert len(checked) == WARM_WINDOW_DAYS
    assert all(code == altius_config.code for code, _ in checked)
