import datetime

from orderability_engine.delivery_rules import EARLY_CUTOFF_CONFIG, DeliveryRuleConfig, compute_our_deadline, evaluate_our_delivery
from orderability_engine.models import TZINFO


def test_compute_our_deadline_is_1300_the_same_day():
    deadline = compute_our_deadline(datetime.date(2026, 9, 24))
    assert deadline == datetime.datetime(2026, 9, 24, 13, 0, tzinfo=TZINFO)


def test_deadline_is_configurable():
    config = DeliveryRuleConfig(cutoff_time=datetime.time(18, 0), days_before=2)
    deadline = compute_our_deadline(datetime.date(2026, 9, 24), config)
    assert deadline == datetime.datetime(2026, 9, 22, 18, 0, tzinfo=TZINFO)


def test_delivery_available_when_restopolis_open_and_before_deadline():
    now = datetime.datetime(2026, 9, 24, 7, 0, tzinfo=TZINFO)  # before Thu 13:00 deadline, same day
    result = evaluate_our_delivery(
        datetime.date(2026, 9, 24), restopolis_ordering_available=True, restopolis_menu_available=True, now=now
    )
    assert result.available is True


def test_delivery_unavailable_once_our_deadline_passes():
    # Restopolis still orderable, but our same-day 13:00 cutoff passed.
    now = datetime.datetime(2026, 9, 24, 13, 15, tzinfo=TZINFO)
    result = evaluate_our_delivery(
        datetime.date(2026, 9, 24), restopolis_ordering_available=True, restopolis_menu_available=True, now=now
    )
    assert result.available is False
    assert result.deadline == datetime.datetime(2026, 9, 24, 13, 0, tzinfo=TZINFO)


def test_delivery_unavailable_when_restopolis_ordering_closed_even_before_our_deadline():
    now = datetime.datetime(2026, 9, 24, 7, 0, tzinfo=TZINFO)
    result = evaluate_our_delivery(
        datetime.date(2026, 9, 24), restopolis_ordering_available=False, restopolis_menu_available=True, now=now
    )
    assert result.available is False


def test_delivery_unavailable_when_menu_missing_even_if_ordering_open():
    now = datetime.datetime(2026, 9, 24, 7, 0, tzinfo=TZINFO)
    result = evaluate_our_delivery(
        datetime.date(2026, 9, 24), restopolis_ordering_available=True, restopolis_menu_available=False, now=now
    )
    assert result.available is False


def test_delivery_unavailable_when_restopolis_signals_unknown():
    now = datetime.datetime(2026, 9, 24, 7, 0, tzinfo=TZINFO)
    result = evaluate_our_delivery(
        datetime.date(2026, 9, 24), restopolis_ordering_available=None, restopolis_menu_available=None, now=now
    )
    assert result.available is False
    # Deadline is still reported even when unavailable -- callers need it for UI.
    assert result.deadline is not None


def test_multiple_dates_each_cut_off_the_same_day():
    # 24.09 cuts off at 13:00 on 24.09, 25.09 at 13:00 on 25.09, etc --
    # never bleeding into the neighboring date.
    assert compute_our_deadline(datetime.date(2026, 9, 24)) == datetime.datetime(2026, 9, 24, 13, 0, tzinfo=TZINFO)
    assert compute_our_deadline(datetime.date(2026, 9, 25)) == datetime.datetime(2026, 9, 25, 13, 0, tzinfo=TZINFO)


# --------------------------------------------------------------------------
# EARLY_CUTOFF_CONFIG (Part 59): the earlier 08:00 same-day cutoff that only
# specific dishes (grill/BBQ mains, salmon -- see menu_service.requires_early_order())
# need to respect, separate from the general 13:00 deadline above.
# --------------------------------------------------------------------------


def test_early_cutoff_deadline_is_0800_the_same_day():
    deadline = compute_our_deadline(datetime.date(2026, 9, 24), EARLY_CUTOFF_CONFIG)
    assert deadline == datetime.datetime(2026, 9, 24, 8, 0, tzinfo=TZINFO)


def test_early_cutoff_available_before_0800():
    now = datetime.datetime(2026, 9, 24, 7, 59, tzinfo=TZINFO)
    result = evaluate_our_delivery(
        datetime.date(2026, 9, 24),
        restopolis_ordering_available=True,
        restopolis_menu_available=True,
        now=now,
        config=EARLY_CUTOFF_CONFIG,
    )
    assert result.available is True


def test_early_cutoff_unavailable_after_0800_even_though_general_deadline_has_not_passed():
    # 09:00: general (13:00) deadline hasn't passed, but the early (08:00)
    # one has -- the two must be able to disagree.
    now = datetime.datetime(2026, 9, 24, 9, 0, tzinfo=TZINFO)
    general = evaluate_our_delivery(
        datetime.date(2026, 9, 24), restopolis_ordering_available=True, restopolis_menu_available=True, now=now
    )
    early = evaluate_our_delivery(
        datetime.date(2026, 9, 24),
        restopolis_ordering_available=True,
        restopolis_menu_available=True,
        now=now,
        config=EARLY_CUTOFF_CONFIG,
    )
    assert general.available is True
    assert early.available is False
