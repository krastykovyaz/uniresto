import datetime

import pytest

from orderability_engine.cache import OrderabilityCache
from orderability_engine.models import RestopolisDayStatus


@pytest.fixture
def cache(tmp_path):
    c = OrderabilityCache(tmp_path / "cache.db", ttl_seconds=900)
    yield c
    c.close()


def _status(**overrides) -> RestopolisDayStatus:
    defaults = dict(
        restaurant_code="UDL-CKB-ALTIUS",
        restaurant_name="UDL-CKB - Altius - Restaurant",
        target_date=datetime.date(2026, 9, 24),
        menu_available=True,
        ordering_available=True,
        reservation_signal_text="Réserver",
        service_start="11:00",
        service_end="14:30",
        restopolis_order_deadline=None,
        item_count=12,
        menu_hash="abc123",
        source_url="https://example.test/Menu",
    )
    defaults.update(overrides)
    return RestopolisDayStatus(**defaults)


def test_get_on_empty_cache_returns_none(cache):
    assert cache.get("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24)) is None
    assert cache.get_raw("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24)) is None


def test_set_then_get_round_trips(cache):
    cache.set(_status())
    result = cache.get("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24))
    assert result is not None
    status, checked_at = result
    assert status.menu_available is True
    assert status.item_count == 12


def test_expired_entry_is_not_returned_by_get_but_get_raw_still_sees_it(cache):
    cache.set(_status(), ttl_seconds=-1)  # already expired
    assert cache.get("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24)) is None
    raw = cache.get_raw("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24))
    assert raw is not None
    assert raw.item_count == 12


def test_set_overwrites_previous_entry(cache):
    cache.set(_status(item_count=12))
    cache.set(_status(item_count=5))
    _status_result, _ = cache.get("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24))
    assert _status_result.item_count == 5


def test_different_dates_are_independent(cache):
    cache.set(_status(target_date=datetime.date(2026, 9, 24), item_count=12))
    cache.set(_status(target_date=datetime.date(2026, 9, 25), item_count=13))
    r1, _ = cache.get("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24))
    r2, _ = cache.get("UDL-CKB-ALTIUS", datetime.date(2026, 9, 25))
    assert r1.item_count == 12
    assert r2.item_count == 13


def test_tri_state_none_round_trips(cache):
    cache.set(_status(menu_available=None, ordering_available=None, fetch_error="boom"))
    status, _ = cache.get("UDL-CKB-ALTIUS", datetime.date(2026, 9, 24))
    assert status.menu_available is None
    assert status.ordering_available is None
    assert status.fetch_error == "boom"


# ---------------------------------------------------------------------------
# Week HTML cache (backs the menu itself, Part 22) -- separate table, same db
# ---------------------------------------------------------------------------


def test_week_html_get_on_empty_cache_returns_none(cache):
    assert cache.get_week_html("UDL-CKB-ALTIUS", 0) is None


def test_week_html_set_then_get_round_trips(cache):
    cache.set_week_html("UDL-CKB-ALTIUS", 0, "<html>week 0</html>", ttl_seconds=3600)
    assert cache.get_week_html("UDL-CKB-ALTIUS", 0) == "<html>week 0</html>"


def test_week_html_expired_entry_is_not_returned(cache):
    cache.set_week_html("UDL-CKB-ALTIUS", 0, "<html>stale</html>", ttl_seconds=-1)  # already expired
    assert cache.get_week_html("UDL-CKB-ALTIUS", 0) is None


def test_week_html_set_overwrites_previous_entry(cache):
    cache.set_week_html("UDL-CKB-ALTIUS", 0, "<html>v1</html>", ttl_seconds=3600)
    cache.set_week_html("UDL-CKB-ALTIUS", 0, "<html>v2</html>", ttl_seconds=3600)
    assert cache.get_week_html("UDL-CKB-ALTIUS", 0) == "<html>v2</html>"


def test_week_html_different_weeks_and_restaurants_are_independent(cache):
    cache.set_week_html("UDL-CKB-ALTIUS", 0, "<html>altius week0</html>", ttl_seconds=3600)
    cache.set_week_html("UDL-CKB-ALTIUS", 1, "<html>altius week1</html>", ttl_seconds=3600)
    cache.set_week_html("UDL-CKB-JOHNS", 0, "<html>johns week0</html>", ttl_seconds=3600)
    assert cache.get_week_html("UDL-CKB-ALTIUS", 0) == "<html>altius week0</html>"
    assert cache.get_week_html("UDL-CKB-ALTIUS", 1) == "<html>altius week1</html>"
    assert cache.get_week_html("UDL-CKB-JOHNS", 0) == "<html>johns week0</html>"


def test_week_html_survives_a_fresh_cache_instance_on_the_same_db_file(tmp_path):
    # Simulates a process restart: a brand-new OrderabilityCache object
    # pointed at the SAME sqlite file must still see what an earlier
    # instance wrote -- this is the whole point of persisting it here
    # instead of only in OrderabilityService's in-process dict.
    db_path = tmp_path / "cache.db"
    first = OrderabilityCache(db_path, ttl_seconds=900)
    first.set_week_html("UDL-CKB-ALTIUS", 0, "<html>persisted</html>", ttl_seconds=3600)
    first.close()

    second = OrderabilityCache(db_path, ttl_seconds=900)
    try:
        assert second.get_week_html("UDL-CKB-ALTIUS", 0) == "<html>persisted</html>"
    finally:
        second.close()
