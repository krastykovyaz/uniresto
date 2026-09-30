"""Internal order storage + server-side price/weight recalculation.

No payment, no real Restopolis order placement by the APP itself -- but
Part 30 adds a real human-in-the-loop workflow around that boundary: an
admin manually places the matching reservation in real Restopolis (see
orderability_engine/telegram_notify.py's admin ping), records what
Restopolis actually charged (`real_price`, a genuinely different number
from `totals.formula`'s own approximate/OUR-pricing estimate -- never
conflated), and the customer confirms or cancels that real price by
email (see orderability_engine/mailer.py's send_order_needs_confirmation
and app.py's /o/<id>/confirm|cancel routes). The order's own `status`
now tracks that flow:

    pending               -- just placed, admin not yet actioned it
    reviewing             -- admin has seen it and is checking the dishes
                             (Part 37) -- purely a courtesy status shown to
                             the customer; the admin can still record a
                             real price straight from 'pending' too, this
                             step is never required
    awaiting_confirmation -- admin recorded a real price, customer emailed
    confirmed             -- customer confirmed the real price
    cancelled             -- customer declined, or never confirmed

Per the task's explicit requirement, the browser is never trusted for
price or weight: `recalculate_order` takes only {id, quantity} from the
client and looks up price/weight/name/allergens from the live menu items
the backend itself just fetched (see app.py's /api/orders handler), so a
tampered or stale client payload can't affect what gets charged/recorded.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from orderability_engine.identity import canonical_identity
from orderability_engine.menu_service import requires_early_order
from orderability_engine.pricing import compute_formula_total

# Per line: one unique dish can be ordered at most twice, so a cart can
# hold many different dishes (2 mains, 2 salads, 2 desserts ...) but never
# ten of the same one.
MAX_QUANTITY = 2
MIN_QUANTITY = 1
# How many not-cancelled orders one client may have for a given
# order_date. Last night's abuse (5 orders in 5 minutes, 10 of every dish
# each) shows both caps are needed.
MAX_ORDERS_PER_DAY = 2
# ...and on how many DIFFERENT upcoming dates one client may have live
# orders at once -- any two of the days on offer, not just the next two.
MAX_ORDER_DATES = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_code TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    order_date TEXT NOT NULL,          -- the delivery/menu date being ordered for
    delivery_location TEXT,
    customer_email TEXT,               -- optional (Part 23); persisted since Part 30 needs
                                        -- to email the customer again later, once a real
                                        -- price is on file -- unlike Part 23's original
                                        -- one-shot confirmation, this can't be "use once,
                                        -- then discard" anymore.
    status TEXT NOT NULL DEFAULT 'pending',  -- see this module's docstring for the state machine
    real_price REAL,                   -- what Restopolis actually charged (Part 30) -- an
                                        -- admin-recorded FACT, never derived/guessed, and
                                        -- never overwrites totals.formula's own separate estimate
    confirmation_token TEXT,           -- required to confirm/cancel via the emailed links;
                                        -- prevents guessing an order id to act on someone else's order
    customer_note TEXT,                -- optional free-text note (Part 55), e.g. "no onion" --
                                        -- relayed as-is to the admin/mailer, never parsed or acted
                                        -- on by this app itself
    customer_lang TEXT,                -- whatever language the customer's OWN app was in at the
                                        -- moment they placed this order (Part 72) -- used to
                                        -- personalize the courier's delivery-notification email,
                                        -- never re-derived/guessed later
    delivered_at TEXT,                 -- NULL until a courier marks it delivered (Part 73) --
                                        -- a courier-reported FACT, independent of `status` above
                                        -- (which tracks the admin's real-price workflow, an
                                        -- orthogonal concern: an order can be confirmed AND not
                                        -- yet delivered, or delivered before it's confirmed)
    claimed_at TEXT,                   -- NULL until a courier taps "Take this delivery" (Part 75)
                                        -- -- pings the admin (Telegram) and the customer (email)
                                        -- the FIRST time this is set
    on_way_emailed_at TEXT,            -- when the customer got the "picked up, on its way" email
                                        -- (now sent at pickup time, not claim time -- see
                                        -- picked_up_at below) -- set at most ONCE per order, so
                                        -- releasing/re-claiming or re-confirming pickup can't
                                        -- email them again
    customer_phone TEXT,               -- optional (unlike customer_email, which became required
                                        -- after a real delivery got stuck with no way to reach the
                                        -- customer) -- another admin-only contact channel, same
                                        -- courier-privacy treatment as customer_email: stripped
                                        -- before the Delivery screen ever sees it (see app.py's
                                        -- api_delivery_orders())
    courier_email TEXT,                -- the claiming courier's own email (now required to claim,
                                        -- Part 81) -- used once, right at claim time, to send THEM
                                        -- the order description (dish names, in courier_lang) via
                                        -- the same email every registered subscriber already gets
                                        -- at order-creation time; persisted (unlike the original
                                        -- one-shot customer_email pattern) for admin visibility/
                                        -- support, same reasoning customer_email itself now has
    courier_lang TEXT,                 -- whatever language the CLAIMING courier's own app was in
                                        -- at the moment they claimed (Part 81) -- distinct from
                                        -- delivery_subscribers.lang, which is each broadcast
                                        -- recipient's own language, not necessarily this order's
                                        -- actual claimant
    picked_up_at TEXT,                 -- NULL until a courier confirms they've physically grabbed
                                        -- the food from the canteen counter (Part 81) -- a SEPARATE,
                                        -- later fact than claimed_at (claiming is just "I'll do
                                        -- this", not "I have it in hand"); this is what actually
                                        -- triggers the customer's "on its way" email now
    accepted_emailed_at TEXT,          -- when the customer got the "order accepted" email (Part 81,
                                        -- sent at claim time) -- same ever-once-per-order dedup
                                        -- reasoning as on_way_emailed_at above, so a claim/release
                                        -- loop can't spam the customer with repeated "accepted"
                                        -- emails
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    price REAL,
    weight_value REAL,
    weight_unit TEXT,
    allergens_json TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1
);
"""

# Columns added after the original schema shipped -- CREATE TABLE IF NOT
# EXISTS is a no-op against an already-existing table (verified: this is
# exactly the "orders" table on the live server, created back in Part 6),
# so these need an explicit migration rather than just editing SCHEMA
# above. (column_name, "ALTER TABLE ... ADD COLUMN ..." definition).
_MIGRATIONS = [
    ("customer_email", "ALTER TABLE orders ADD COLUMN customer_email TEXT"),
    ("real_price", "ALTER TABLE orders ADD COLUMN real_price REAL"),
    ("confirmation_token", "ALTER TABLE orders ADD COLUMN confirmation_token TEXT"),
    ("customer_note", "ALTER TABLE orders ADD COLUMN customer_note TEXT"),
    ("customer_lang", "ALTER TABLE orders ADD COLUMN customer_lang TEXT"),
    ("delivered_at", "ALTER TABLE orders ADD COLUMN delivered_at TEXT"),
    ("claimed_at", "ALTER TABLE orders ADD COLUMN claimed_at TEXT"),
    ("on_way_emailed_at", "ALTER TABLE orders ADD COLUMN on_way_emailed_at TEXT"),
    ("customer_phone", "ALTER TABLE orders ADD COLUMN customer_phone TEXT"),
    ("courier_email", "ALTER TABLE orders ADD COLUMN courier_email TEXT"),
    ("courier_lang", "ALTER TABLE orders ADD COLUMN courier_lang TEXT"),
    ("picked_up_at", "ALTER TABLE orders ADD COLUMN picked_up_at TEXT"),
    ("accepted_emailed_at", "ALTER TABLE orders ADD COLUMN accepted_emailed_at TEXT"),
    # The customer's verified University email, when it differs from
    # customer_email (which defaults to their Communication Email, often
    # a personal address) -- the only address Profile's Luni balance
    # reads, so the order's Luni has to land here to be visible at all.
    ("reward_email", "ALTER TABLE orders ADD COLUMN reward_email TEXT"),
]


class DailyOrderLimitError(Exception):
    """This client already has MAX_ORDERS_PER_DAY live orders for that date."""


class OrderDatesLimitError(Exception):
    """This client already has live orders on MAX_ORDER_DATES other upcoming dates."""


class OrderValidationError(Exception):
    """Raised when a selection references a dish that isn't on the live
    menu, or an out-of-range quantity -- the frontend must not be trusted."""


def _line_total(price: float | None, quantity: int) -> float | None:
    return None if price is None else round(price * quantity, 2)


def _line_weight(weight_value: float | None, quantity: int) -> float | None:
    return None if weight_value is None else weight_value * quantity


def validate_selection_shape(selection) -> None:
    """Raises OrderValidationError unless `selection` is a list of
    {"id": int, ...} dicts with no dish listed twice. Checked before anything
    reads the entries: a string or a non-dict entry used to crash the order
    routes with a 500, and a repeated id let one dish past MAX_QUANTITY
    (two lines of 2 = 4)."""
    if not isinstance(selection, list):
        raise OrderValidationError("'items' must be a list of {id, quantity}")
    seen = set()
    for entry in selection:
        if not isinstance(entry, dict):
            raise OrderValidationError("Each entry in 'items' must be an object {id, quantity}")
        item_id = entry.get("id")
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            raise OrderValidationError(f"Menu item id must be an integer, got {item_id!r}")
        if item_id in seen:
            raise OrderValidationError(f"Menu item id {item_id} is listed more than once")
        seen.add(item_id)


def recalculate_order(menu_items: list[dict], selection: list[dict]) -> dict:
    """menu_items: the live, backend-fetched menu (each dict has at least
    id/category/name/description/price/weight_value/weight_unit/allergens).
    selection: client-supplied [{"id": int, "quantity": int}, ...] -- the
    ONLY two fields trusted from the browser; everything else is looked
    up server-side. Raises OrderValidationError for an unknown id or a
    quantity outside [MIN_QUANTITY, MAX_QUANTITY]."""
    validate_selection_shape(selection)
    by_id = {item["id"]: item for item in menu_items}

    line_items = []
    for entry in selection:
        item_id = entry.get("id")
        quantity = entry.get("quantity", 1)

        if item_id not in by_id:
            raise OrderValidationError(f"Menu item id {item_id!r} is not on the current menu for this date")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not (MIN_QUANTITY <= quantity <= MAX_QUANTITY):
            raise OrderValidationError(
                f"Quantity for item {item_id} must be an integer between {MIN_QUANTITY} and {MAX_QUANTITY}, got {quantity!r}"
            )

        menu_item = by_id[item_id]
        line_items.append(
            {
                "id": item_id,
                "category": menu_item["category"],
                "name": menu_item["name"],
                "description": menu_item.get("description"),
                "price": menu_item.get("price"),
                "weight_value": menu_item.get("weight_value"),
                "weight_unit": menu_item.get("weight_unit"),
                "allergens": menu_item.get("allergens", []),
                "quantity": quantity,
                "line_price": _line_total(menu_item.get("price"), quantity),
                "line_weight": _line_weight(menu_item.get("weight_value"), quantity),
            }
        )

    return {"items": line_items, "totals": aggregate_totals(line_items)}


def aggregate_totals(line_items: list[dict]) -> dict:
    """item_count = distinct dishes selected; total_quantity = sum of
    quantities (a quantity-2 item counts as 2 toward weight, per the
    task's explicit "Do not double-count quantities incorrectly" / "250 g
    x 2 = 500 g" example). Unknown weight/price never silently becomes 0:
    each total carries its own "_fully_known" flag plus a count of the
    portions that couldn't be included.

    Weight is summed PER UNIT (`weight_by_unit`), never into one flat
    number: real Restopolis data mixes g (food), ml (drinks), and
    occasionally piece in the same order, and adding e.g. 250 g + 200 ml
    into a single "450" would be meaningless, not just imprecise."""
    item_count = len(line_items)
    total_quantity = sum(it["quantity"] for it in line_items)

    weight_by_unit: dict[str, float] = {}
    for it in line_items:
        if it["line_weight"] is not None:
            unit = it["weight_unit"]
            weight_by_unit[unit] = round(weight_by_unit.get(unit, 0) + it["line_weight"], 3)
    unknown_weight_portions = sum(it["quantity"] for it in line_items if it["line_weight"] is None)

    known_price = sum(it["line_price"] for it in line_items if it["line_price"] is not None)
    unknown_price_portions = sum(it["quantity"] for it in line_items if it["line_price"] is None)

    return {
        "item_count": item_count,
        "total_quantity": total_quantity,
        "weight_by_unit": weight_by_unit,
        "weight_fully_known": unknown_weight_portions == 0,
        "unknown_weight_portions": unknown_weight_portions,
        # Per-dish price, from Restopolis -- always null in practice (see
        # orderability_engine/pricing.py's module docstring); kept
        # separate from "formula" below on purpose.
        "total_price_known": round(known_price, 2) if known_price else (0 if item_count else None),
        "price_fully_known": unknown_price_portions == 0,
        "unknown_price_portions": unknown_price_portions,
        # OUR OWN per-course price (main/starter/dessert/sandwich, each
        # priced and summed independently), NOT from Restopolis -- see
        # orderability_engine/pricing.py.
        "formula": compute_formula_total(line_items),
    }


class OrderStore:
    def __init__(self, db_path: str | Path = "orders.db"):
        # See orderability_engine/cache.py's __init__ docstring: verified
        # live that Flask's dev server can dispatch requests concurrently,
        # so a lock (not just check_same_thread=False) is required.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _existing_columns(self) -> set[str]:
        return {row[1] for row in self._conn.execute("PRAGMA table_info(orders)").fetchall()}

    def _migrate(self) -> None:
        existing = self._existing_columns()
        for column_name, statement in _MIGRATIONS:
            if column_name not in existing:
                try:
                    self._conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    # Both gunicorn workers run this at the same moment on
                    # boot: each can see the column missing, then lose the
                    # race to ADD it. That used to crash the worker (and
                    # the whole gunicorn master) until systemd restarted
                    # it. Already-added is exactly the state we want.
                    if "duplicate column name" not in str(exc):
                        raise

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "OrderStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @contextmanager
    def _transaction(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def create_order(
        self,
        restaurant_code: str,
        restaurant_name: str,
        order_date: date,
        items: list[dict],
        delivery_location: str | None = None,
        customer_email: str | None = None,
        customer_note: str | None = None,
        customer_lang: str | None = None,
        customer_phone: str | None = None,
        reward_email: str | None = None,
        max_orders_per_day: int | None = None,
        max_order_dates: int | None = None,
        today: date | None = None,
    ) -> int:
        """items: recalculate_order()'s "items" list (server-priced/weighed).
        With max_orders_per_day set, raises DailyOrderLimitError instead of
        inserting when customer_email/reward_email already have that many
        non-cancelled orders for order_date -- checked inside the same
        write transaction as the INSERT, so two simultaneous requests
        (even on different gunicorn workers) can't both slip under it.
        max_order_dates (with `today`) likewise raises OrderDatesLimitError
        when this would be a new date on top of that many other upcoming
        ones the client already has live orders for."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            if max_orders_per_day is not None or max_order_dates is not None:
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                emails = [customer_email, reward_email]
                if max_orders_per_day is not None and self._count_live_orders_for_day(conn, order_date, emails) >= max_orders_per_day:
                    raise DailyOrderLimitError()
                if max_order_dates is not None:
                    dates = self._live_order_dates(conn, emails, today or order_date)
                    if order_date.isoformat() not in dates and len(dates) >= max_order_dates:
                        raise OrderDatesLimitError()
            cur = conn.execute(
                """
                INSERT INTO orders (restaurant_code, restaurant_name, order_date, delivery_location, customer_email, customer_note, customer_lang, customer_phone, reward_email, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (restaurant_code, restaurant_name, order_date.isoformat(), delivery_location, customer_email, customer_note, customer_lang, customer_phone, reward_email, now),
            )
            order_id = cur.lastrowid
            conn.executemany(
                """
                INSERT INTO order_items
                    (order_id, category, name, description, price, weight_value, weight_unit, allergens_json, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        order_id,
                        it["category"],
                        it["name"],
                        it.get("description"),
                        it.get("price"),
                        it.get("weight_value"),
                        it.get("weight_unit"),
                        json.dumps(it.get("allergens", []), ensure_ascii=False),
                        it.get("quantity", 1),
                    )
                    for it in items
                ],
            )
        return order_id

    @staticmethod
    def _identity_addresses(emails: list[str | None]) -> list[str]:
        """Every form a client's address can be stored in: as typed
        (lower-cased) AND its canonical identity, so "name+2@uni.lu" and
        "name@student.uni.lu" count against the same person's limits (the
        order's reward_email is stored canonical, see api_create_order)."""
        found: set[str] = set()
        for e in emails:
            if e and e.strip():
                found.add(e.strip().lower())
                found.add(canonical_identity(e))
        return sorted(found)

    @staticmethod
    def _count_live_orders_for_day(conn: sqlite3.Connection, order_date: date, emails: list[str | None]) -> int:
        addresses = OrderStore._identity_addresses(emails)
        if not addresses:
            return 0
        marks = ",".join("?" * len(addresses))
        return conn.execute(
            f"SELECT COUNT(*) FROM orders WHERE order_date = ? AND status != 'cancelled' "
            f"AND (lower(customer_email) IN ({marks}) OR lower(reward_email) IN ({marks}))",
            (order_date.isoformat(), *addresses, *addresses),
        ).fetchone()[0]

    @staticmethod
    def _live_order_dates(conn: sqlite3.Connection, emails: list[str | None], from_date: date) -> set[str]:
        """Distinct order_dates (today onward) this client has non-cancelled
        orders for -- past days stop counting, or two old orders would
        block ordering forever."""
        addresses = OrderStore._identity_addresses(emails)
        if not addresses:
            return set()
        marks = ",".join("?" * len(addresses))
        rows = conn.execute(
            f"SELECT DISTINCT order_date FROM orders WHERE order_date >= ? AND status != 'cancelled' "
            f"AND (lower(customer_email) IN ({marks}) OR lower(reward_email) IN ({marks}))",
            (from_date.isoformat(), *addresses, *addresses),
        ).fetchall()
        return {r[0] for r in rows}

    def count_live_orders_for_day(self, order_date: date, emails: list[str | None]) -> int:
        with self._lock:
            return self._count_live_orders_for_day(self._conn, order_date, emails)

    def get_order(self, order_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, restaurant_code, restaurant_name, order_date, delivery_location, customer_email, "
                "status, real_price, created_at, customer_note, customer_lang, delivered_at, claimed_at, customer_phone, "
                "courier_email, courier_lang, picked_up_at, reward_email FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            if row is None:
                return None
            rows = self._conn.execute(
                "SELECT category, name, description, price, weight_value, weight_unit, allergens_json, quantity "
                "FROM order_items WHERE order_id = ?",
                (order_id,),
            ).fetchall()

        line_items = []
        for it in rows:
            price, weight_value, quantity = it[3], it[4], it[7]
            line_items.append(
                {
                    "category": it[0],
                    "name": it[1],
                    "description": it[2],
                    "price": price,
                    "weight_value": weight_value,
                    "weight_unit": it[5],
                    "allergens": json.loads(it[6]),
                    "quantity": quantity,
                    "line_price": _line_total(price, quantity),
                    "line_weight": _line_weight(weight_value, quantity),
                    # Re-derived from the item's own (category, name), same
                    # rule the food card badge uses (Part 59) -- never
                    # stored, so it can't go stale against a menu_service
                    # rule change the way a persisted flag could.
                    "requires_early_order": requires_early_order(it[0], it[1]),
                }
            )

        return {
            "id": row[0],
            "restaurant_code": row[1],
            "restaurant_name": row[2],
            "order_date": row[3],
            "delivery_location": row[4],
            "customer_email": row[5],
            "status": row[6],
            # What Restopolis actually charged, once an admin has recorded
            # it (Part 30) -- None until then. Deliberately separate from
            # totals.formula's own estimate, never merged into one number.
            "real_price": row[7],
            "created_at": row[8],
            "customer_note": row[9],
            "customer_lang": row[10],
            "delivered_at": row[11],
            "claimed_at": row[12],
            "customer_phone": row[13],
            "courier_email": row[14],
            "courier_lang": row[15],
            "picked_up_at": row[16],
            "reward_email": row[17],
            "items": line_items,
            "totals": aggregate_totals(line_items),
        }

    def list_orders_by_status(self, status: str) -> list[dict]:
        """Used by the admin page (Part 30) -- e.g. status='pending' for
        orders an admin still needs to place in real Restopolis and
        record a price for. Returns full order dicts (via get_order()),
        newest first."""
        with self._lock:
            ids = [r[0] for r in self._conn.execute("SELECT id FROM orders WHERE status = ? ORDER BY id DESC", (status,)).fetchall()]
        return [self.get_order(i) for i in ids]

    def list_recent_orders(self, limit: int = 100) -> list[dict]:
        """Part 52+: real orders for the in-app Delivery (courier) screen,
        newest first -- EVERY status, including 'cancelled' (Part 73):
        the screen itself buckets these into Pending/Expired/Closed/
        Delivered sections (static/app.js's deliveryOrderSections()), and
        a cancelled order belongs in "Closed" there rather than
        disappearing outright -- a courier who already started planning a
        pickup benefits from seeing it was called off, not just silence.
        Unlike list_orders_by_status() this deliberately isn't scoped to
        one status: a courier benefits from seeing an order the moment
        it's placed ('pending'), not only once an admin has actioned it."""
        with self._lock:
            ids = [r[0] for r in self._conn.execute("SELECT id FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        return [self.get_order(i) for i in ids]

    def list_open_claimed_orders(self) -> list[dict]:
        """Orders a courier claimed that were never delivered and are
        still live (awaiting the customer's confirmation, or confirmed) --
        the only orders that can still earn a no-show penalty. Small by
        construction, so app.py re-checks it on every relevant request."""
        with self._lock:
            ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT id FROM orders WHERE claimed_at IS NOT NULL AND delivered_at IS NULL "
                    "AND status IN ('awaiting_confirmation', 'confirmed')"
                ).fetchall()
            ]
        return [self.get_order(i) for i in ids]

    def list_orders_for_courier(self, courier_email: str, limit: int = 100) -> list[dict]:
        """Every order this courier currently holds or has delivered --
        claimed (a released order has claimed_at cleared, so it's not
        theirs any more) -- newest claim first. Matched on the canonical
        identity, so plus-tag variants of the same address are one courier."""
        wanted = canonical_identity(courier_email)
        if not wanted:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, courier_email FROM orders WHERE claimed_at IS NOT NULL AND courier_email IS NOT NULL "
                "ORDER BY claimed_at DESC"
            ).fetchall()
        ids = [r[0] for r in rows if canonical_identity(r[1]) == wanted][:limit]
        return [self.get_order(i) for i in ids]

    def count_created_between(self, start: datetime, end: datetime) -> int:
        """How many orders were actually placed in [start, end) -- both
        real, timezone-aware datetimes. Used by daily_report.py's evening
        admin report (Part 74) for a real "orders today" count -- reads
        directly off `orders` rather than a separate tracked counter, so
        there's exactly one place this number can come from. Converted
        to UTC before comparing -- see page_views.py's count_between()
        for why a non-UTC offset would otherwise compare wrong."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM orders WHERE created_at >= ? AND created_at < ?",
                (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()),
            ).fetchone()
        return row[0]

    def mark_claimed(self, order_id: int, courier_email: str | None = None, courier_lang: str | None = None) -> bool:
        """Part 75 (courier_email/courier_lang added Part 81): True only
        the FIRST time this succeeds for a given order (the WHERE clause
        below only matches while claimed_at is still NULL) -- app.py uses
        that to decide whether to actually notify the admin/customer/
        courier, so two couriers tapping "Take this delivery" at nearly
        the same moment only trigger one notification round, not two.
        False for an order that's already claimed (not an error -- the
        second courier just sees it was already taken) or that doesn't
        exist. courier_email/courier_lang are only ever WRITTEN here (on
        the winning claim) -- a losing call's values are simply dropped,
        never overwrite the winner's."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET claimed_at = ?, courier_email = ?, courier_lang = ? WHERE id = ? AND claimed_at IS NULL",
                (now, courier_email, courier_lang, order_id),
            )
            return cur.rowcount > 0

    def mark_unclaimed(self, order_id: int) -> bool:
        """Part 76: a courier who took an order but can't do it after all
        gives it back, so it reads as open again for everyone else. True
        only if it was actually claimed AND not yet physically picked up
        (Part 81 -- once the food is in hand, "release" no longer makes
        real-world sense) and not yet delivered -- False otherwise, so
        the caller only pings the admin about a real release."""
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET claimed_at = NULL WHERE id = ? AND claimed_at IS NOT NULL "
                "AND picked_up_at IS NULL AND delivered_at IS NULL",
                (order_id,),
            )
            return cur.rowcount > 0

    def mark_picked_up(self, order_id: int) -> bool:
        """Part 81: a courier confirms they've physically grabbed the food
        from the canteen counter -- a separate, later fact than
        claimed_at (claiming is just "I'll do this", not "I have it in
        hand"). True only the FIRST time this succeeds for a given order
        (claimed_at must already be set, picked_up_at must still be NULL,
        and it must not already be delivered) -- app.py uses that to
        decide whether to send the customer's "on its way" email, so a
        double-tap can't send it twice."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET picked_up_at = ? WHERE id = ? AND claimed_at IS NOT NULL "
                "AND picked_up_at IS NULL AND delivered_at IS NULL",
                (now, order_id),
            )
            return cur.rowcount > 0

    def mark_on_way_emailed(self, order_id: int) -> bool:
        """True only the FIRST time for a given order (same WHERE-IS-NULL
        pattern as mark_claimed()) -- the caller sends the customer's "on
        its way" email (now sent at pickup time, Part 81 -- see
        picked_up_at's own schema comment) only when this says so, so it
        goes out at most once per order no matter how many times pickup
        is (attempted to be) confirmed."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET on_way_emailed_at = ? WHERE id = ? AND on_way_emailed_at IS NULL", (now, order_id)
            )
            return cur.rowcount > 0

    def mark_accepted_emailed(self, order_id: int) -> bool:
        """Part 81: same ever-once-per-order pattern as
        mark_on_way_emailed() above, for the customer's "order accepted"
        email (sent at claim time) -- goes out at most once per order no
        matter how many times it's claimed/released/re-claimed."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET accepted_emailed_at = ? WHERE id = ? AND accepted_emailed_at IS NULL", (now, order_id)
            )
            return cur.rowcount > 0

    def mark_delivered(self, order_id: int) -> bool:
        """Part 73: a courier-reported fact ("I physically handed this
        over"), independent of `status`'s own admin-workflow state
        machine -- see delivered_at's own schema comment. Idempotent:
        marking an already-delivered order delivered again just refreshes
        the timestamp, never an error."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            cur = conn.execute("UPDATE orders SET delivered_at = ? WHERE id = ?", (now, order_id))
            return cur.rowcount > 0

    def mark_not_delivered(self, order_id: int) -> bool:
        """Undoes mark_delivered() above -- a courier tapping the wrong
        order, or marking one delivered too early, must be reversible."""
        with self._lock, self._transaction() as conn:
            cur = conn.execute("UPDATE orders SET delivered_at = NULL WHERE id = ?", (order_id,))
            return cur.rowcount > 0

    def mark_reviewing(self, order_id: int) -> bool:
        """Part 37: the admin has seen the order (typically via the
        "I'm checking this order" link on the Telegram ping) and is
        looking at real Restopolis to place it -- a purely informational
        status the customer's app reflects (see static/i18n.js's
        statusReviewing). Only 'pending' -> 'reviewing'; a no-op (False)
        for an order already past that point, so tapping the Telegram
        link twice (or after already recording a price) never moves an
        order backward."""
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET status = 'reviewing' WHERE id = ? AND status = 'pending'",
                (order_id,),
            )
            return cur.rowcount > 0

    def admin_cancel_order(self, order_id: int) -> bool:
        """The admin calling an order off (spam, a test, something the
        canteen can't do) from the /admin/orders panel -- any order still
        waiting on the admin or the customer. False if there's no such
        order or it's already confirmed/cancelled. Unlike cancel_order()
        this needs no customer token; the ADMIN_TOKEN gate is the auth.
        The status change also kills any confirm/cancel email link already
        sent, since those only match while awaiting_confirmation."""
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET status = 'cancelled' WHERE id = ? "
                "AND status IN ('pending', 'reviewing', 'awaiting_confirmation')",
                (order_id,),
            )
            return cur.rowcount > 0

    def set_real_price(self, order_id: int, real_price: float) -> str | None:
        """Records what Restopolis actually charged (an admin-supplied
        FACT, from having placed the real reservation -- never derived or
        guessed) and moves the order to 'awaiting_confirmation'. Returns
        a fresh confirmation token (for the customer's confirm/cancel
        email links) on success, None if no such order exists or it's
        not in a state this applies to ('pending' or 'reviewing' --
        marking reviewing first is never required, an admin can record a
        price straight away -- but doesn't re-issue a token for an order
        already awaiting/confirmed/cancelled, which could invalidate a
        link already sent)."""
        token = secrets.token_urlsafe(24)
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET real_price = ?, confirmation_token = ?, status = 'awaiting_confirmation' "
                "WHERE id = ? AND status IN ('pending', 'reviewing')",
                (real_price, token, order_id),
            )
            if cur.rowcount == 0:
                return None
        return token

    def is_awaiting_confirmation(self, order_id: int, token: str) -> bool:
        """Read-only twin of confirm_order()/cancel_order()'s own match --
        lets the email link's GET page say "not valid anymore" up front
        without consuming anything."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM orders WHERE id = ? AND status = 'awaiting_confirmation' AND confirmation_token = ?",
                (order_id, token),
            ).fetchone()
        return row is not None

    def confirm_order(self, order_id: int, token: str) -> bool:
        """One-time use: the token only matches while status is still
        'awaiting_confirmation', so a link that's already been clicked
        (or a cancel link used instead) can't be replayed to flip the
        outcome afterward."""
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET status = 'confirmed' WHERE id = ? AND status = 'awaiting_confirmation' AND confirmation_token = ?",
                (order_id, token),
            )
            return cur.rowcount > 0

    def cancel_order(self, order_id: int, token: str) -> bool:
        """Same one-time-use guarantee as confirm_order()."""
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                "UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'awaiting_confirmation' AND confirmation_token = ?",
                (order_id, token),
            )
            return cur.rowcount > 0
