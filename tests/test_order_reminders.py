"""Reminders before an order closes (orderability_engine/order_reminders.py)."""

from datetime import datetime, timedelta

import pytest

from orderability_engine.models import TZINFO
from orderability_engine.order_reminders import (
    REMINDER_LEAD_MINUTES,
    ROLE_COURIER,
    ROLE_CUSTOMER,
    OrderReminderStore,
    due_reminders,
    reminder_text,
    reminder_window,
)

DAY = "2026-10-12"


def _order(**fields):
    base = {
        "id": 19, "order_date": DAY, "status": "pending", "restaurant_name": "Brasserie John's",
        "claimed_at": "2026-10-12T09:24:00+00:00", "courier_email": "courier@uni.lu", "customer_email": "student@uni.lu",
        "picked_up_at": None, "handed_over_at": None, "delivered_at": None,
    }
    base.update(fields)
    return base


def _at(hour, minute, second=0, day=DAY):
    d = datetime.fromisoformat(day)
    return datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=TZINFO)


def test_the_window_opens_20_minutes_before_the_1330_close():
    start, end = reminder_window(datetime.fromisoformat(DAY).date())
    assert REMINDER_LEAD_MINUTES == 20
    assert (start.strftime("%H:%M"), end.strftime("%H:%M")) == ("13:10", "13:30")


@pytest.mark.parametrize("when, expected", [((13, 9, 59), False), ((13, 10, 0), True), ((13, 20), True), ((13, 29, 59), True), ((13, 30, 0), False), ((15, 12), False), ((9, 0), False)])
def test_only_inside_the_window(when, expected):
    assert bool(due_reminders([_order()], _at(*when))) is expected


def test_only_orders_for_today():
    assert due_reminders([_order(order_date="2026-10-11")], _at(13, 15)) == []   # yesterday's: already closed
    assert due_reminders([_order(order_date="2026-10-13")], _at(13, 15)) == []   # tomorrow's: its own window is tomorrow


@pytest.mark.parametrize("fields", [{"status": "cancelled"}, {"status": "expired"}, {"status": "confirmed"}, {"delivered_at": "2026-10-12T10:00:00+00:00"}, {"claimed_at": None}])
def test_orders_that_are_closed_finished_or_untaken_get_no_reminder(fields):
    assert due_reminders([_order(**fields)], _at(13, 15)) == []


def test_the_courier_is_reminded_while_the_order_is_taken_or_picked_up():
    for fields in ({}, {"picked_up_at": "2026-10-12T10:00:00+00:00"}):
        assert [(o["id"], role) for o, role in due_reminders([_order(**fields)], _at(13, 15))] == [(19, ROLE_COURIER)]


def test_once_handed_over_it_is_the_customer_who_is_reminded_not_the_courier():
    assert [(o["id"], role) for o, role in due_reminders([_order(handed_over_at="2026-10-12T10:30:00+00:00")], _at(13, 15))] == [(19, ROLE_CUSTOMER)]


def test_each_state_has_its_own_wording():
    taken = reminder_text(_order(), ROLE_COURIER)
    picked = reminder_text(_order(picked_up_at="x"), ROLE_COURIER)
    customer = reminder_text(_order(handed_over_at="x"), ROLE_CUSTOMER)
    assert taken[0] == "Your delivery is still open" and "I picked up the food" in taken[1] and "13:30" in taken[1] and "I can't deliver this" in taken[1]
    assert picked[0] == "Hand over your delivery" and "I delivered" in picked[1] and "13:30" in picked[1]
    assert customer[0] == "Did your order arrive?" and "Mark as delivered" in customer[1] and "Luni" in customer[1]
    assert all("#19" in text[1] and "Brasserie John's" in text[1] for text in (taken, picked)) and "#19" in customer[1]


def test_a_person_is_reminded_only_once_even_across_two_workers(tmp_path):
    first, second = OrderReminderStore(tmp_path / "orders.db"), OrderReminderStore(tmp_path / "orders.db")  # two worker processes
    assert first.claim(19, ROLE_COURIER) is True
    assert second.claim(19, ROLE_COURIER) is False
    assert first.claim(19, ROLE_CUSTOMER) is True   # the customer is a different person
    assert first.claim(20, ROLE_COURIER) is True    # another order
    first.release(19, ROLE_COURIER)
    assert second.claim(19, ROLE_COURIER) is True
