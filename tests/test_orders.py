import datetime

import pytest

from orderability_engine.orders import (
    MAX_QUANTITY,
    OrderStore,
    OrderValidationError,
    aggregate_totals,
    recalculate_order,
)


@pytest.fixture
def store(tmp_path):
    s = OrderStore(tmp_path / "orders.db")
    yield s
    s.close()


def test_create_and_get_order(store):
    order_id = store.create_order(
        "UDL-CKB-ALTIUS",
        "UDL-CKB - Altius - Restaurant",
        datetime.date(2026, 9, 24),
        items=[
            {"category": "Entrée", "name": "Soup", "description": None, "price": None, "allergens": [], "quantity": 1},
            {"category": "Dessert", "name": "Cake", "description": None, "price": None, "allergens": [{"code": 7}], "quantity": 2},
        ],
        delivery_location="Maison du Savoir 4.150",
    )
    order = store.get_order(order_id)
    assert order["restaurant_code"] == "UDL-CKB-ALTIUS"
    assert order["order_date"] == "2026-09-24"
    assert order["delivery_location"] == "Maison du Savoir 4.150"
    assert order["status"] == "pending"
    assert len(order["items"]) == 2
    assert order["items"][1]["quantity"] == 2
    assert order["items"][1]["allergens"] == [{"code": 7}]


def test_get_unknown_order_returns_none(store):
    assert store.get_order(999) is None


def test_orders_get_incrementing_ids(store):
    id1 = store.create_order("A", "A", datetime.date(2026, 9, 24), [{"category": "x", "name": "y"}])
    id2 = store.create_order("A", "A", datetime.date(2026, 9, 24), [{"category": "x", "name": "y"}])
    assert id2 > id1


def test_get_order_includes_weight_and_totals(store):
    order_id = store.create_order(
        "UDL-CKB-ALTIUS",
        "UDL-CKB - Altius - Restaurant",
        datetime.date(2026, 9, 24),
        items=[
            {"category": "Snack", "name": "Bretzel", "price": None, "weight_value": 80, "weight_unit": "g", "quantity": 2},
            {"category": "Entrée", "name": "Salad'bar", "price": None, "weight_value": None, "weight_unit": None, "quantity": 1},
        ],
    )
    order = store.get_order(order_id)
    assert order["totals"]["weight_by_unit"] == {"g": 160}
    assert order["totals"]["unknown_weight_portions"] == 1
    assert order["totals"]["weight_fully_known"] is False


# ---------------------------------------------------------------------------
# aggregate_totals / recalculate_order (pure logic, no DB)
# ---------------------------------------------------------------------------

MENU_ITEMS = [
    {"id": 0, "category": "Entrée", "name": "Salad'bar", "description": None, "price": None,
     "weight_value": None, "weight_unit": None, "allergens": []},
    {"id": 5, "category": "Non-végétarien", "name": "Rôti de porc Orloff", "description": None, "price": None,
     "weight_value": None, "weight_unit": None, "allergens": []},
    {"id": 6, "category": "Dessert", "name": "Paris-Brest", "description": None, "price": None,
     "weight_value": None, "weight_unit": None, "allergens": []},
    {"id": 32, "category": "Snack à emporter", "name": "Bretzel salé", "description": None, "price": None,
     "weight_value": 80.0, "weight_unit": "g", "allergens": []},
    {"id": 40, "category": "Snack à emporter", "name": "Coca Cola", "description": None, "price": None,
     "weight_value": 0.2, "weight_unit": "l", "allergens": []},
    {"id": 99, "category": "Dessert", "name": "Priced dessert (test only)", "description": None, "price": 2.5,
     "weight_value": 120.0, "weight_unit": "g", "allergens": []},
]


def test_recalculate_order_weight_by_unit_not_summed_across_units():
    result = recalculate_order(MENU_ITEMS, [{"id": 32, "quantity": 1}, {"id": 40, "quantity": 1}])
    assert result["totals"]["weight_by_unit"] == {"g": 80.0, "l": 0.2}


def test_recalculate_order_quantity_multiplier_matches_task_example():
    # "250 g x 2 = 500 g" -- here: 80 g x 2 = 160 g
    result = recalculate_order(MENU_ITEMS, [{"id": 32, "quantity": 2}])
    assert result["totals"]["weight_by_unit"]["g"] == 160.0
    assert result["items"][0]["line_weight"] == 160.0


def test_recalculate_order_unknown_weight_not_treated_as_zero():
    result = recalculate_order(MENU_ITEMS, [{"id": 0, "quantity": 1}, {"id": 32, "quantity": 1}])
    assert result["totals"]["weight_by_unit"] == {"g": 80.0}
    assert result["totals"]["unknown_weight_portions"] == 1
    assert result["totals"]["weight_fully_known"] is False


def test_recalculate_order_ignores_client_supplied_price_uses_server_price():
    # Even if a caller's dict "happened" to look like it had a client
    # price, recalculate_order only ever reads price from the menu_items
    # (server) side, keyed by id -- selection entries only carry id/quantity.
    result = recalculate_order(MENU_ITEMS, [{"id": 99, "quantity": 2, "price": 0.01}])
    assert result["items"][0]["price"] == 2.5
    assert result["items"][0]["line_price"] == 5.0
    assert result["totals"]["total_price_known"] == 5.0


def test_recalculate_order_unknown_item_id_raises():
    with pytest.raises(OrderValidationError):
        recalculate_order(MENU_ITEMS, [{"id": 12345, "quantity": 1}])


def test_recalculate_order_quantity_zero_raises():
    with pytest.raises(OrderValidationError):
        recalculate_order(MENU_ITEMS, [{"id": 0, "quantity": 0}])


def test_recalculate_order_negative_quantity_raises():
    with pytest.raises(OrderValidationError):
        recalculate_order(MENU_ITEMS, [{"id": 0, "quantity": -1}])


def test_recalculate_order_quantity_above_max_raises():
    with pytest.raises(OrderValidationError):
        recalculate_order(MENU_ITEMS, [{"id": 0, "quantity": MAX_QUANTITY + 1}])


def test_recalculate_order_quantity_at_max_is_allowed():
    result = recalculate_order(MENU_ITEMS, [{"id": 0, "quantity": MAX_QUANTITY}])
    assert result["items"][0]["quantity"] == MAX_QUANTITY


def test_aggregate_totals_empty_selection():
    totals = aggregate_totals([])
    assert totals["item_count"] == 0
    assert totals["total_quantity"] == 0
    assert totals["weight_by_unit"] == {}
    assert totals["formula"]["total"] is None


# ---------------------------------------------------------------------------
# The meal-formula price (orderability_engine/pricing.py) flows through
# recalculate_order()/aggregate_totals() and get_order()
# ---------------------------------------------------------------------------


def test_recalculate_order_includes_formula_price_for_main_plus_starter_plus_dessert():
    result = recalculate_order(
        MENU_ITEMS,
        [{"id": 5, "quantity": 1}, {"id": 0, "quantity": 1}, {"id": 6, "quantity": 1}],
    )
    formula = result["totals"]["formula"]
    assert formula["main_count"] == 1
    assert formula["starter_count"] == 1
    assert formula["dessert_count"] == 1
    assert formula["total"] == 10.00


def test_recalculate_order_formula_ignores_per_dish_price_field():
    # id 99 ("Priced dessert") has a non-null per-dish price (test
    # fixture only -- Restopolis never actually sets one); the formula
    # total must still be OUR flat per-category prices (main 6.00 +
    # dessert 2.00 = 8.00), not id 99's own per-dish price.
    result = recalculate_order(MENU_ITEMS, [{"id": 5, "quantity": 1}, {"id": 99, "quantity": 1}])
    formula = result["totals"]["formula"]
    assert formula["total"] == 8.00
    # but the unrelated per-dish total_price_known still reflects id 99's price
    assert result["totals"]["total_price_known"] == 2.5


def test_get_order_round_trips_the_formula_price(store):
    order_id = store.create_order(
        "UDL-CKB-ALTIUS",
        "UDL-CKB - Altius - Restaurant",
        datetime.date(2026, 9, 24),
        items=[
            {"category": "Non-végétarien", "name": "Rôti de porc Orloff", "price": None, "quantity": 1},
            {"category": "Entrée", "name": "Salad'bar", "price": None, "quantity": 1},
        ],
    )
    order = store.get_order(order_id)
    formula = order["totals"]["formula"]
    assert formula["main_count"] == 1
    assert formula["starter_count"] == 1
    assert formula["total"] == 8.00
