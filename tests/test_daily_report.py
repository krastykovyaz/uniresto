import datetime
from unittest.mock import patch

import pytest

from orderability_engine.daily_report import (
    DailyReportStore,
    _next_send_time,
    _seconds_until,
    compute_report_counts,
    local_day_bounds,
    run_report_with_retries,
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


def _stores(tmp_path):
    return (
        PageViewStore(tmp_path / "orders.db"),
        OrderStore(tmp_path / "orders.db"),
        DailyReportStore(tmp_path / "orders.db"),
    )


@pytest.fixture
def telegram_configured():
    with patch("orderability_engine.daily_report.is_configured", return_value=True):
        yield


def test_send_report_for_only_sends_once(tmp_path, telegram_configured):
    page_views, order_store, report_store = _stores(tmp_path)
    today = datetime.datetime.now(TZINFO).date()

    with patch("orderability_engine.daily_report.send_daily_report", return_value=(True, None)) as mock_send:
        first = send_report_for(page_views, order_store, report_store, today)
        second = send_report_for(page_views, order_store, report_store, today)

    assert first == "sent"
    assert second == "already_claimed"
    mock_send.assert_called_once()


def test_send_report_for_releases_the_claim_when_the_send_fails(tmp_path, telegram_configured):
    # The real bug: a failed send used to keep the claim, so no retry
    # (by this worker or the other one) could ever send that day's report.
    page_views, order_store, report_store = _stores(tmp_path)
    today = datetime.datetime.now(TZINFO).date()

    with patch("orderability_engine.daily_report.send_daily_report", return_value=(False, "telegram down")):
        assert send_report_for(page_views, order_store, report_store, today) == "failed"
    with patch("orderability_engine.daily_report.send_daily_report", return_value=(True, None)) as mock_send:
        assert send_report_for(page_views, order_store, report_store, today) == "sent"
    mock_send.assert_called_once()


def test_send_report_for_does_not_claim_when_telegram_is_unconfigured(tmp_path):
    page_views, order_store, report_store = _stores(tmp_path)
    today = datetime.datetime.now(TZINFO).date()
    with patch("orderability_engine.daily_report.is_configured", return_value=False), patch(
        "orderability_engine.daily_report.send_daily_report"
    ) as mock_send:
        assert send_report_for(page_views, order_store, report_store, today) == "not_configured"
    mock_send.assert_not_called()
    # Nothing was claimed, so a later (configured) attempt can still send.
    assert report_store.claim(today.isoformat()) is True


def test_run_report_with_retries_retries_until_it_sends(tmp_path, telegram_configured):
    page_views, order_store, report_store = _stores(tmp_path)
    day = datetime.date(2026, 9, 28)
    clock = [datetime.datetime(2026, 9, 28, 20, 0, tzinfo=TZINFO)]
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += datetime.timedelta(seconds=seconds)

    results = iter([(False, "down"), (False, "down"), (True, None)])
    with patch("orderability_engine.daily_report.send_daily_report", side_effect=lambda *a: next(results)) as mock_send:
        status = run_report_with_retries(
            page_views, order_store, report_store, day, retry_seconds=600, sleep=fake_sleep, now=lambda: clock[0]
        )

    assert status == "sent"
    assert mock_send.call_count == 3
    assert sleeps == [600, 600]


def test_run_report_with_retries_gives_up_when_the_day_ends(tmp_path, telegram_configured):
    page_views, order_store, report_store = _stores(tmp_path)
    day = datetime.date(2026, 9, 28)
    clock = [datetime.datetime(2026, 9, 28, 23, 45, tzinfo=TZINFO)]

    def fake_sleep(seconds):
        clock[0] += datetime.timedelta(seconds=seconds)

    with patch("orderability_engine.daily_report.send_daily_report", return_value=(False, "down")) as mock_send:
        status = run_report_with_retries(
            page_views, order_store, report_store, day, retry_seconds=600, sleep=fake_sleep, now=lambda: clock[0]
        )

    assert status == "failed"
    # 23:45 attempt, 23:55 retry; a third at 00:05 would be past the day.
    assert mock_send.call_count == 2


def test_run_report_with_retries_does_not_retry_when_another_worker_owns_it(tmp_path, telegram_configured):
    page_views, order_store, report_store = _stores(tmp_path)
    day = datetime.date(2026, 9, 28)
    report_store.claim(day.isoformat())  # the other worker already has it
    sleeps = []
    with patch("orderability_engine.daily_report.send_daily_report") as mock_send:
        status = run_report_with_retries(
            page_views, order_store, report_store, day, sleep=sleeps.append,
            now=lambda: datetime.datetime(2026, 9, 28, 20, 0, tzinfo=TZINFO),
        )
    assert status == "already_claimed"
    assert sleeps == []
    mock_send.assert_not_called()


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


def test_seconds_until_spans_the_october_fall_back_correctly():
    # 2026-10-25 clocks go back (CEST -> CET): from 20:30 on the 24th to
    # 20:00 on the 25th is 24.5 REAL hours. Plain same-tz subtraction said
    # 23.5 -- so the report used to go out at 19:00 that evening.
    now = datetime.datetime(2026, 10, 24, 20, 30, tzinfo=TZINFO)
    target = _next_send_time(now, 20)
    assert target == datetime.datetime(2026, 10, 25, 20, 0, tzinfo=TZINFO)
    assert _seconds_until(now, target) == 24.5 * 3600


def test_seconds_until_spans_the_march_spring_forward_correctly():
    # 2027-03-28 clocks go forward (CET -> CEST): 20:30 -> next 20:00 is
    # 22.5 real hours, not 23.5 (the report used to go out at 21:00).
    now = datetime.datetime(2027, 3, 27, 20, 30, tzinfo=TZINFO)
    target = _next_send_time(now, 20)
    assert _seconds_until(now, target) == 22.5 * 3600
