"""Internal order storage + server-side price/weight recalculation.

No payment, no real Restopolis order placement -- this only records what
the customer picked, for later wiring into a real fulfillment flow
(explicitly out of scope for this task).

Per the task's explicit requirement, the browser is never trusted for
price or weight: `recalculate_order` takes only {id, quantity} from the
client and looks up price/weight/name/allergens from the live menu items
the backend itself just fetched (see app.py's /api/orders handler), so a
tampered or stale client payload can't affect what gets charged/recorded.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from orderability_engine.pricing import compute_formula_total

MAX_QUANTITY = 10
MIN_QUANTITY = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_code TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    order_date TEXT NOT NULL,          -- the delivery/menu date being ordered for
    delivery_location TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- internal only; no payment/fulfillment yet
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


class OrderValidationError(Exception):
    """Raised when a selection references a dish that isn't on the live
    menu, or an out-of-range quantity -- the frontend must not be trusted."""


def _line_total(price: float | None, quantity: int) -> float | None:
    return None if price is None else round(price * quantity, 2)


def _line_weight(weight_value: float | None, quantity: int) -> float | None:
    return None if weight_value is None else weight_value * quantity


def recalculate_order(menu_items: list[dict], selection: list[dict]) -> dict:
    """menu_items: the live, backend-fetched menu (each dict has at least
    id/category/name/description/price/weight_value/weight_unit/allergens).
    selection: client-supplied [{"id": int, "quantity": int}, ...] -- the
    ONLY two fields trusted from the browser; everything else is looked
    up server-side. Raises OrderValidationError for an unknown id or a
    quantity outside [MIN_QUANTITY, MAX_QUANTITY]."""
    by_id = {item["id"]: item for item in menu_items}

    line_items = []
    for entry in selection:
        item_id = entry.get("id")
        quantity = entry.get("quantity", 1)

        if item_id not in by_id:
            raise OrderValidationError(f"Menu item id {item_id!r} is not on the current menu for this date")
        if not isinstance(quantity, int) or not (MIN_QUANTITY <= quantity <= MAX_QUANTITY):
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
        # OUR OWN per-course price (main/starter/dessert, each priced and
        # summed independently), NOT from Restopolis -- see
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
        self._conn.commit()

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
    ) -> int:
        """items: recalculate_order()'s "items" list (server-priced/weighed)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO orders (restaurant_code, restaurant_name, order_date, delivery_location, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (restaurant_code, restaurant_name, order_date.isoformat(), delivery_location, now),
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

    def get_order(self, order_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, restaurant_code, restaurant_name, order_date, delivery_location, status, created_at "
                "FROM orders WHERE id = ?",
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
                }
            )

        return {
            "id": row[0],
            "restaurant_code": row[1],
            "restaurant_name": row[2],
            "order_date": row[3],
            "delivery_location": row[4],
            "status": row[5],
            "created_at": row[6],
            "items": line_items,
            "totals": aggregate_totals(line_items),
        }
