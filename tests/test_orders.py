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
    assert formula["total"] == 8.00


def test_recalculate_order_formula_ignores_per_dish_price_field():
    # id 99 ("Priced dessert") has a non-null per-dish price (test
    # fixture only -- Restopolis never actually sets one); the formula
    # total must still be OUR meal-tier bundle price (main+starter+dessert
    # = 8.00), not id 99's own per-dish price. A starter (id 0) has to be
    # included too, since a dessert with no starter isn't a priced
    # combination at all (see orderability_engine/pricing.py).
    result = recalculate_order(MENU_ITEMS, [{"id": 5, "quantity": 1}, {"id": 0, "quantity": 1}, {"id": 99, "quantity": 1}])
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
    assert formula["total"] == 7.00


# ---------------------------------------------------------------------------
# Admin confirmation workflow (Part 30): customer_email persistence,
# real_price, and the pending -> awaiting_confirmation -> confirmed/cancelled
# state machine
# ---------------------------------------------------------------------------


def _basic_order_id(store, **overrides):
    kwargs = dict(
        restaurant_code="UDL-CKB-ALTIUS",
        restaurant_name="UDL-CKB - Altius - Restaurant",
        order_date=datetime.date(2026, 9, 24),
        items=[{"category": "Non-végétarien", "name": "Rôti de porc Orloff", "price": None, "quantity": 1}],
    )
    kwargs.update(overrides)
    return store.create_order(**kwargs)


def test_create_order_persists_customer_email(store):
    order_id = _basic_order_id(store, customer_email="student@uni.lu")
    order = store.get_order(order_id)
    assert order["customer_email"] == "student@uni.lu"


def test_create_order_without_customer_email_is_none(store):
    order_id = _basic_order_id(store)
    order = store.get_order(order_id)
    assert order["customer_email"] is None


def test_new_order_starts_pending_with_no_real_price(store):
    order_id = _basic_order_id(store)
    order = store.get_order(order_id)
    assert order["status"] == "pending"
    assert order["real_price"] is None


def test_mark_reviewing_moves_pending_to_reviewing(store):
    order_id = _basic_order_id(store)
    assert store.mark_reviewing(order_id) is True
    assert store.get_order(order_id)["status"] == "reviewing"


def test_mark_reviewing_on_unknown_order_returns_false(store):
    assert store.mark_reviewing(999999) is False


def test_mark_reviewing_twice_is_a_no_op_the_second_time(store):
    order_id = _basic_order_id(store)
    assert store.mark_reviewing(order_id) is True
    assert store.mark_reviewing(order_id) is False
    assert store.get_order(order_id)["status"] == "reviewing"


def test_mark_reviewing_after_a_price_was_already_recorded_does_not_move_it_backward(store):
    order_id = _basic_order_id(store)
    store.set_real_price(order_id, 8.50)
    assert store.mark_reviewing(order_id) is False
    assert store.get_order(order_id)["status"] == "awaiting_confirmation"


def test_set_real_price_from_reviewing_also_moves_to_awaiting_confirmation(store):
    order_id = _basic_order_id(store)
    store.mark_reviewing(order_id)
    token = store.set_real_price(order_id, 8.50)
    assert token is not None
    order = store.get_order(order_id)
    assert order["status"] == "awaiting_confirmation"
    assert order["real_price"] == 8.50


def test_set_real_price_moves_to_awaiting_confirmation_and_returns_a_token(store):
    order_id = _basic_order_id(store)
    token = store.set_real_price(order_id, 8.50)
    assert token is not None
    order = store.get_order(order_id)
    assert order["status"] == "awaiting_confirmation"
    assert order["real_price"] == 8.50


def test_set_real_price_on_unknown_order_returns_none(store):
    assert store.set_real_price(999999, 8.50) is None


def test_set_real_price_twice_is_refused_the_second_time(store):
    # Already 'awaiting_confirmation' after the first call -- the WHERE
    # status='pending' guard must reject a second call rather than
    # silently re-issuing a token (which would invalidate a link already
    # emailed to the customer).
    order_id = _basic_order_id(store)
    store.set_real_price(order_id, 8.50)
    assert store.set_real_price(order_id, 9.00) is None
    assert store.get_order(order_id)["real_price"] == 8.50


def test_confirm_order_with_correct_token_succeeds(store):
    order_id = _basic_order_id(store)
    token = store.set_real_price(order_id, 8.50)
    assert store.confirm_order(order_id, token) is True
    assert store.get_order(order_id)["status"] == "confirmed"


def test_confirm_order_with_wrong_token_fails(store):
    order_id = _basic_order_id(store)
    store.set_real_price(order_id, 8.50)
    assert store.confirm_order(order_id, "wrong-token") is False
    assert store.get_order(order_id)["status"] == "awaiting_confirmation"


def test_confirm_order_before_any_price_set_fails(store):
    order_id = _basic_order_id(store)
    assert store.confirm_order(order_id, "anything") is False


def test_confirm_order_token_is_one_time_use(store):
    order_id = _basic_order_id(store)
    token = store.set_real_price(order_id, 8.50)
    assert store.confirm_order(order_id, token) is True
    # Replaying the same token/link a second time must not succeed again.
    assert store.confirm_order(order_id, token) is False


def test_cancel_order_with_correct_token_succeeds(store):
    order_id = _basic_order_id(store)
    token = store.set_real_price(order_id, 8.50)
    assert store.cancel_order(order_id, token) is True
    assert store.get_order(order_id)["status"] == "cancelled"


def test_cancel_order_with_wrong_token_fails(store):
    order_id = _basic_order_id(store)
    token = store.set_real_price(order_id, 8.50)
    assert store.cancel_order(order_id, "wrong-token") is False
    assert store.get_order(order_id)["status"] == "awaiting_confirmation"


def test_confirm_then_cancel_with_the_same_token_only_the_first_wins(store):
    order_id = _basic_order_id(store)
    token = store.set_real_price(order_id, 8.50)
    assert store.confirm_order(order_id, token) is True
    assert store.cancel_order(order_id, token) is False
    assert store.get_order(order_id)["status"] == "confirmed"


def test_list_orders_by_status_returns_only_matching_orders_newest_first(store):
    id1 = _basic_order_id(store)
    id2 = _basic_order_id(store)
    id3 = _basic_order_id(store)
    store.set_real_price(id2, 8.50)  # id2 is now awaiting_confirmation, id1/id3 stay pending

    pending = store.list_orders_by_status("pending")
    assert [o["id"] for o in pending] == [id3, id1]

    awaiting = store.list_orders_by_status("awaiting_confirmation")
    assert [o["id"] for o in awaiting] == [id2]


def test_migration_is_idempotent_reopening_the_same_db(tmp_path):
    # A second OrderStore pointed at the same file (simulating a process
    # restart) must not choke on columns that already exist.
    db_path = tmp_path / "orders.db"
    first = OrderStore(db_path)
    order_id = first.create_order(
        "UDL-CKB-ALTIUS",
        "UDL-CKB - Altius - Restaurant",
        datetime.date(2026, 9, 24),
        items=[{"category": "Non-végétarien", "name": "Rôti de porc Orloff", "price": None, "quantity": 1}],
        customer_email="student@uni.lu",
    )
    first.close()

    second = OrderStore(db_path)
    try:
        order = second.get_order(order_id)
        assert order["customer_email"] == "student@uni.lu"
        assert order["real_price"] is None
    finally:
        second.close()
