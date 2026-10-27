"""A nudge BEFORE an order closes, for the person who forgot to tap.

At DELIVERY_EXPIRY_TIME (13:30 Luxembourg, delivery_rules.py) every order for today that is still not
delivered is closed as "expired". A courier who took an order and simply forgot to tap "I picked up the
food" / "I delivered" used to find it silently gone. Twenty minutes before the close, this module works
out who should be reminded:

- the COURIER who took an order that is still open (not yet picked up, or picked up but not handed over);
- the CUSTOMER of an order the courier says is handed over but who has not confirmed it yet (that
  confirmation is what pays the courier's Luni).

Each person is reminded at most ONCE per order, however the order moves on afterwards, so a courier who
picks the food up at 13:12 is not nagged again at 13:13. The "once" is a row in the shared SQLite file
(like daily_report.py's claim), so it holds across both gunicorn workers and across restarts.

Pure functions for what to send and to whom; the actual sending (push, email) and the thread that calls
this every minute live in app.py, which owns those channels.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from orderability_engine.delivery_rules import DELIVERY_EXPIRY_TIME
from orderability_engine.models import TZINFO
from orderability_engine.sqlite_util import connect

logger = logging.getLogger("uniresto.reminders")

# How long before the close the reminder goes out.
REMINDER_LEAD_MINUTES = 20
# Orders in these states are the ones the 13:30 close actually closes.
EXPIRABLE_STATUSES = ("pending", "reviewing", "awaiting_confirmation")
ROLE_COURIER, ROLE_CUSTOMER = "courier", "customer"

SCHEMA = """
CREATE TABLE IF NOT EXISTS order_reminders_sent (
    order_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (order_id, role)
);
"""


class OrderReminderStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        self._conn = connect(db_path)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def claim(self, order_id: int, role: str) -> bool:
        """True the FIRST time for this (order, person) across every process sharing the file; False after."""
        now = datetime.now(TZINFO).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO order_reminders_sent (order_id, role, sent_at) VALUES (?, ?, ?) ON CONFLICT(order_id, role) DO NOTHING",
                (order_id, role, now),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def release(self, order_id: int, role: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM order_reminders_sent WHERE order_id = ? AND role = ?", (order_id, role))
            self._conn.commit()


def reminder_window(order_date) -> tuple[datetime, datetime]:
    """[start, end) on `order_date`: from LEAD minutes before the close until the close itself."""
    end = datetime.combine(order_date, DELIVERY_EXPIRY_TIME, tzinfo=TZINFO)
    return end - timedelta(minutes=REMINDER_LEAD_MINUTES), end


def due_reminders(orders: list[dict], now: datetime) -> list[tuple[dict, str]]:
    """[(order, role)] to remind right now. An order qualifies when it is dated today, still open (an
    expirable status, taken, not delivered) and `now` is inside its reminder window."""
    due = []
    for order in orders:
        if order.get("status") not in EXPIRABLE_STATUSES or order.get("delivered_at") or not order.get("claimed_at"):
            continue
        start, end = reminder_window(datetime.fromisoformat(str(order["order_date"])).date())
        if not (start <= now < end):
            continue
        if order.get("handed_over_at"):
            due.append((order, ROLE_CUSTOMER))  # handed over, waiting for the customer's confirmation
        elif order.get("courier_email"):
            due.append((order, ROLE_COURIER))
    return due


def reminder_text(order: dict, role: str) -> tuple[str, str]:
    """(title, body) in English, like the other pushes. The state of the order decides the wording."""
    closes = DELIVERY_EXPIRY_TIME.strftime("%H:%M")
    place = order.get("restaurant_name") or "your order"
    if role == ROLE_CUSTOMER:
        return (
            "Did your order arrive?",
            f"Your courier says order #{order['id']} from {place} was handed over. Tap \"Mark as delivered\" before {closes}, "
            "so the order is closed properly and your courier gets their Luni.",
        )
    if order.get("picked_up_at"):
        return (
            "Hand over your delivery",
            f"Order #{order['id']} ({place}) closes at {closes}. Tap \"I delivered\" once it is handed over.",
        )
    return (
        "Your delivery is still open",
        f"Order #{order['id']} ({place}) closes at {closes}. Tap \"I picked up the food\" once you have it, "
        "or \"I can't deliver this\" to give it back.",
    )


def start_order_reminder_scheduler(run_once, interval_seconds: int = 60) -> threading.Thread:
    """Calls run_once() every minute on a daemon thread. Every worker process runs one; the claim() inside
    run_once is what makes sure a person is reminded only once."""

    def loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                run_once()
            except Exception:  # noqa: BLE001 -- one bad tick must never kill the thread for every tick after
                logger.warning("[REMINDERS] unexpected failure", exc_info=True)

    thread = threading.Thread(target=loop, daemon=True, name="order-reminders")
    thread.start()
    return thread
