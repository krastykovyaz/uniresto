import datetime
from unittest.mock import MagicMock, patch

from orderability_engine.daily_report import (
    DailyReportStore,
    _next_send_time,
    compute_report_counts,
    local_day_bounds,
    send_report_for,
)
from orderability_engine.models import TZINFO
from orderability_engine.orders import OrderStore
from orderability_engine.page_views import PageViewStore


def test_claim_true_the_first_time(tmp_path):
    store = DailyReportStore(tmp_path / "reports.db")
    assert store.claim("2026-09-28") is True


def test_claim_false_every_time_after(tmp_path):
    # Simulates two gunicorn worker processes racing for the same
    # evening -- only the first claim() call may succeed.
    store = DailyReportStore(tmp_path / "reports.db")
    assert store.claim("2026-09-28") is True
    assert store.claim("2026-09-28") is False
    assert store.claim("2026-09-28") is False


def test_claim_is_independent_per_date(tmp_path):
    store = DailyReportStore(tmp_path / "reports.db")
    assert store.claim("2026-09-28") is True
    assert store.claim("2026-09-29") is True


def test_claim_survives_a_reopened_store(tmp_path):
    # Two SEPARATE DailyReportStore instances (as two worker processes
    # would each construct their own) against the SAME db file -- this is
    # the actual scenario the dedup has to work under.
    db_path = tmp_path / "reports.db"
    assert DailyReportStore(db_path).claim("2026-09-28") is True
    assert DailyReportStore(db_path).claim("2026-09-28") is False


def test_local_day_bounds_is_24_hours_in_luxembourg_time():
    start, end = local_day_bounds(datetime.date(2026, 9, 28))
    assert start.tzinfo == TZINFO
    assert (end - start) == datetime.timedelta(days=1)
    assert start.hour == 0 and start.minute == 0


def test_compute_report_counts_reads_real_numbers(tmp_path):
    page_views = PageViewStore(tmp_path / "orders.db")
    order_store = OrderStore(tmp_path / "orders.db")
    today = datetime.datetime.now(TZINFO).date()

    page_views.record("home")
    page_views.record("home")
    page_views.record("menu")
    page_views.record("delivery")
    order_store.create_order("altius", "Altius", today, [{"category": "c", "name": "n", "quantity": 1}])

    counts = compute_report_counts(page_views, order_store, today)
    assert counts == {"home": 2, "menu": 1, "orders": 1, "delivery": 1}


def test_compute_report_counts_excludes_other_days(tmp_path):
    page_views = PageViewStore(tmp_path / "orders.db")
    order_store = OrderStore(tmp_path / "orders.db")
    today = datetime.datetime.now(TZINFO).date()
    yesterday = today - datetime.timedelta(days=1)

    page_views.record("home")  # recorded "now", i.e. today
    order_store.create_order("altius", "Altius", today, [{"category": "c", "name": "n", "quantity": 1}])

    counts = compute_report_counts(page_views, order_store, yesterday)
    assert counts == {"home": 0, "menu": 0, "orders": 0, "delivery": 0}


def test_send_report_for_only_sends_once(tmp_path):
    page_views = PageViewStore(tmp_path / "orders.db")
    order_store = OrderStore(tmp_path / "orders.db")
    report_store = DailyReportStore(tmp_path / "orders.db")
    today = datetime.datetime.now(TZINFO).date()

    with patch("orderability_engine.daily_report.send_daily_report", return_value=(True, None)) as mock_send:
        first = send_report_for(page_views, order_store, report_store, today)
        second = send_report_for(page_views, order_store, report_store, today)

    assert first is True
    assert second is False
    mock_send.assert_called_once()


def test_send_report_for_reports_unsent_when_telegram_fails(tmp_path):
    page_views = PageViewStore(tmp_path / "orders.db")
    order_store = OrderStore(tmp_path / "orders.db")
    report_store = DailyReportStore(tmp_path / "orders.db")
    today = datetime.datetime.now(TZINFO).date()

    with patch("orderability_engine.daily_report.send_daily_report", return_value=(False, "not configured")):
        result = send_report_for(page_views, order_store, report_store, today)
    assert result is False


def test_next_send_time_same_day_when_before_the_hour():
    now = datetime.datetime(2026, 9, 28, 10, 0, tzinfo=TZINFO)
    next_send = _next_send_time(now, send_hour=20)
    assert next_send == datetime.datetime(2026, 9, 28, 20, 0, tzinfo=TZINFO)


def test_next_send_time_rolls_to_tomorrow_when_already_past():
    now = datetime.datetime(2026, 9, 28, 20, 5, tzinfo=TZINFO)
    next_send = _next_send_time(now, send_hour=20)
    assert next_send == datetime.datetime(2026, 9, 29, 20, 0, tzinfo=TZINFO)


def test_next_send_time_rolls_to_tomorrow_exactly_at_the_hour():
    # A restart landing exactly at the send instant must not re-send an
    # already-completed slot -- next_send always looks strictly forward.
    now = datetime.datetime(2026, 9, 28, 20, 0, tzinfo=TZINFO)
    next_send = _next_send_time(now, send_hour=20)
    assert next_send == datetime.datetime(2026, 9, 29, 20, 0, tzinfo=TZINFO)
