from datetime import datetime, timedelta, timezone

import pytest

from orderability_engine.admin_stats import STATS_PREVIOUS_DAYS, build_stats_message, collect_stats
from orderability_engine.models import TZINFO
from orderability_engine.orders import OrderStore
from orderability_engine.page_views import PageViewStore

NOW = datetime(2026, 9, 29, 15, 30, tzinfo=TZINFO)  # a Tuesday afternoon


@pytest.fixture
def stores(tmp_path):
    return PageViewStore(tmp_path / "orders.db"), OrderStore(tmp_path / "orders.db")


def _view(page_views, event, days_ago=0, source=None, hour=12):
    day = (NOW - timedelta(days=days_ago)).replace(hour=hour, minute=0)
    with page_views._lock:
        page_views._conn.execute(
            "INSERT INTO page_views (event, source, created_at) VALUES (?, ?, ?)",
            (event, source, day.astimezone(timezone.utc).isoformat()),
        )
        page_views._conn.commit()


def test_it_covers_today_and_the_three_days_before(stores):
    days = collect_stats(*stores, today=NOW.date())
    assert STATS_PREVIOUS_DAYS == 3
    assert [d["day"].isoformat() for d in days] == ["2026-09-29", "2026-09-28", "2026-09-27", "2026-09-26"]


def test_each_day_counts_only_its_own_views(stores):
    page_views, orders = stores
    for _ in range(3):
        _view(page_views, "home", days_ago=0)
    _view(page_views, "home", days_ago=1)
    _view(page_views, "home", days_ago=5)  # outside the window
    days = {d["day"].isoformat(): d for d in collect_stats(page_views, orders, NOW.date())}
    assert days["2026-09-29"]["home"] == 3
    assert days["2026-09-28"]["home"] == 1
    assert days["2026-09-27"]["home"] == 0


def test_days_follow_the_luxembourg_calendar_not_utc(stores):
    page_views, orders = stores
    # 23:30 UTC on the 28th is 01:30 on the 29th in Luxembourg (summer time)
    with page_views._lock:
        page_views._conn.execute(
            "INSERT INTO page_views (event, source, created_at) VALUES ('home', NULL, ?)",
            (datetime(2026, 9, 28, 23, 30, tzinfo=timezone.utc).isoformat(),),
        )
        page_views._conn.commit()
    days = {d["day"].isoformat(): d for d in collect_stats(page_views, orders, NOW.date())}
    assert days["2026-09-29"]["home"] == 1 and days["2026-09-28"]["home"] == 0


def test_every_qr_source_is_listed_in_every_day(stores):
    page_views, orders = stores
    _view(page_views, "home", 0, "flyer-a")
    _view(page_views, "home", 0, "flyer-a")
    _view(page_views, "home", 0, None)
    _view(page_views, "home", 2, "flyer-b")
    text = build_stats_message(page_views, orders, NOW)
    today_block = text.split("\n\n")[1]
    assert "flyer-a: 2" in today_block and "(direct): 1" in today_block
    assert "flyer-b: 0" in today_block  # scanned on another day of the window, so shown here as 0
    two_days_ago = next(b for b in text.split("\n\n") if b.startswith("Sun 27 Sep"))
    assert "flyer-b: 1" in two_days_ago and "flyer-a: 0" in two_days_ago


def test_a_qr_added_later_just_appears(stores):
    page_views, orders = stores
    _view(page_views, "home", 0, "flyer-a")
    assert "flyer-e" not in build_stats_message(page_views, orders, NOW)
    _view(page_views, "home", 0, "flyer-e")
    assert "flyer-e: 1" in build_stats_message(page_views, orders, NOW)


def test_sources_are_ordered_busiest_first_over_the_whole_window(stores):
    page_views, orders = stores
    _view(page_views, "home", 0, "flyer-b")
    for _ in range(3):
        _view(page_views, "home", 3, "flyer-c")
    for _ in range(2):
        _view(page_views, "home", 1, "flyer-a")
    labels = [line.strip().split(":")[0] for line in build_stats_message(page_views, orders, NOW).split("\n\n")[1].splitlines() if line.startswith("  ")]
    assert labels == ["flyer-c", "flyer-a", "flyer-b"]


def test_the_total_block_sums_everything(stores):
    page_views, orders = stores
    _view(page_views, "home", 0, "flyer-a")
    _view(page_views, "home", 1, "flyer-a")
    _view(page_views, "home", 3, None)
    _view(page_views, "menu", 0)
    _view(page_views, "menu", 2)
    _view(page_views, "delivery", 1)
    total = build_stats_message(page_views, orders, NOW).split("\n\n")[-1]
    assert total.startswith("Total, last 4 days")
    assert "Opened the app: 3" in total and "flyer-a: 2" in total and "(direct): 1" in total
    assert "Viewed a menu: 2" in total and "Opened deliveries: 1" in total


def test_orders_are_counted_per_day(stores, tmp_path):
    page_views, orders = stores
    from datetime import date

    orders.create_order("UDL-CKB-ALTIUS", "Altius", date(2026, 9, 30), [{"category": "x", "name": "y", "quantity": 1}], "Building A")
    text = build_stats_message(page_views, orders, datetime.now(TZINFO))
    assert "Orders placed: 1" in text.split("\n\n")[1]


def test_the_message_has_the_familiar_shape(stores):
    page_views, orders = stores
    text = build_stats_message(page_views, orders, NOW)
    assert text.startswith("UniResto stats -- Tue 29 Sep, 15:30")
    for expected in ("Tue 29 Sep (today, so far)", "Mon 28 Sep (yesterday)", "Sun 27 Sep", "Sat 26 Sep"):
        assert expected in text
    for line in ("Opened the app:", "Viewed a menu:", "Orders placed:", "Opened deliveries:"):
        assert text.count(line) == 5  # four days + the total
