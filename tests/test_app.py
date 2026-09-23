import datetime
from unittest.mock import patch

import pytest

from app import create_app
from orderability_engine.cache import OrderabilityCache
from orderability_engine.orders import OrderStore
from orderability_engine.service import OrderabilityService
from restopolis.config import load_restaurants
from tests.orderability_helpers import FakeRestopolisClient

# Known from the real fixture (tests/fixtures/altius_week0.html), Thu 24 Sep:
# id 0 = "Salad'bar" (daily formula item, no weight in real data)
# id 32 = "Bretzel salé" (Constant products, 80 g -- real weight data)
SALAD_BAR_ID = 0
BRETZEL_ID = 32


@pytest.fixture
def client(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    restaurants = load_restaurants()
    fake_client = FakeRestopolisClient(week_html_by_offset={0: altius_html, 1: altius_closed_week_html})
    service = OrderabilityService(
        client=fake_client,
        cache=OrderabilityCache(tmp_path / "cache.db", ttl_seconds=900),
        restaurants=restaurants,
        today=fixture_today,
    )
    order_store = OrderStore(tmp_path / "orders.db")
    app = create_app(service=service, order_store=order_store)
    app.testing = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# API: restaurants / status / available-dates (Task 2, unaffected)
# ---------------------------------------------------------------------------


def test_api_restaurants(client):
    resp = client.get("/api/restaurants")
    assert resp.status_code == 200
    slugs = {r["slug"] for r in resp.get_json()}
    assert slugs == {"altius", "brasserie-johns"}


def test_api_restaurants_includes_building(client):
    resp = client.get("/api/restaurants")
    by_slug = {r["slug"]: r for r in resp.get_json()}
    assert by_slug["altius"]["building"] == "Main building"
    assert by_slug["brasserie-johns"]["building"] == "JFK building"


def test_api_status_available(client):
    resp = client.get("/api/restaurants/altius/status?date=2026-09-24")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "available"


def test_api_status_missing_date_is_400(client):
    assert client.get("/api/restaurants/altius/status").status_code == 400


def test_api_status_unknown_restaurant_is_404(client):
    assert client.get("/api/restaurants/nope/status?date=2026-09-24").status_code == 404


def test_api_available_dates(client):
    resp = client.get("/api/restaurants/altius/available-dates?count=2")
    body = resp.get_json()
    assert len(body) == 2
    assert all(r["status"] == "available" for r in body)


# ---------------------------------------------------------------------------
# API: menu (Task 3 -- weight, ids, Constant products included)
# ---------------------------------------------------------------------------


def test_api_menu_for_available_date_includes_weight_and_ids(client):
    resp = client.get("/api/restaurants/altius/menu/2026-09-24")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["date"] == "2026-09-24"
    assert body["max_quantity"] == 10
    ids = {it["id"] for it in body["items"]}
    assert len(ids) == len(body["items"])  # ids are unique

    salad = next(it for it in body["items"] if it["id"] == SALAD_BAR_ID)
    assert salad["name"] == "Salad'bar"
    assert salad["weight_value"] is None
    assert salad["weight_display"] == "Portion size not specified"

    bretzel = next(it for it in body["items"] if it["id"] == BRETZEL_ID)
    assert bretzel["weight_value"] == 80.0
    assert bretzel["weight_unit"] == "g"
    assert bretzel["weight_display"] == "80 g"


def test_api_menu_never_invents_a_price(client):
    resp = client.get("/api/restaurants/altius/menu/2026-09-24")
    body = resp.get_json()
    # Real Restopolis data exposes no prices at all on this page (see
    # README.md) -- every item must honestly report price: null, never a
    # fabricated number.
    assert all(it["price"] is None for it in body["items"])


def test_api_menu_for_unavailable_date_is_409(client):
    resp = client.get("/api/restaurants/altius/menu/2026-09-26")  # no_menu
    assert resp.status_code == 409
    assert resp.get_json()["status"] == "no_menu"


def test_api_orderability_check_post(client):
    resp = client.post("/api/orderability/check", json={"restaurant": "altius", "date": "2026-09-01"})
    assert resp.get_json()["status"] == "past_date"


def test_api_orderability_check_missing_fields_is_400(client):
    assert client.post("/api/orderability/check", json={"restaurant": "altius"}).status_code == 400


# ---------------------------------------------------------------------------
# API: order quote / create -- server-side recalculation (Task 3 §27/§28)
# ---------------------------------------------------------------------------


def test_quote_computes_weight_by_unit_and_ignores_client_price(client):
    resp = client.post(
        "/api/orders/quote",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": BRETZEL_ID, "quantity": 2}, {"id": SALAD_BAR_ID, "quantity": 1}],
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["totals"]["weight_by_unit"]["g"] == 160.0  # 80g x 2
    assert body["totals"]["unknown_weight_portions"] == 1  # Salad'bar
    assert body["totals"]["item_count"] == 2
    assert body["totals"]["total_quantity"] == 3


def test_quote_rejects_unknown_item_id(client):
    resp = client.post(
        "/api/orders/quote",
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": 999999, "quantity": 1}]},
    )
    assert resp.status_code == 400


def test_quote_rejects_out_of_range_quantity(client):
    resp = client.post(
        "/api/orders/quote",
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 99}]},
    )
    assert resp.status_code == 400


def test_create_order_success_recalculates_server_side(client):
    resp = client.post(
        "/api/orders",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": BRETZEL_ID, "quantity": 2}],
            "delivery_location": "Office 4.150",
        },
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["restaurant_code"] == "UDL-CKB-ALTIUS"
    assert body["items"][0]["name"] == "Bretzel salé 80 g"  # weight is never stripped out of the raw name
    assert body["items"][0]["weight_value"] == 80.0
    assert body["items"][0]["quantity"] == 2
    assert body["totals"]["weight_by_unit"]["g"] == 160.0


def test_create_order_ignores_any_price_client_tries_to_send(client):
    # The client payload only ever contains {id, quantity} -- there is no
    # price field it COULD send that would be trusted; this asserts the
    # server's own (null, real) price is what's stored regardless.
    resp = client.post(
        "/api/orders",
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
    )
    body = resp.get_json()
    assert body["items"][0]["price"] is None


def test_create_order_with_uni_lu_email_sends_confirmation(client):
    with patch("app.send_order_confirmation", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/api/orders",
            json={
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@uni.lu",
            },
        )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["email_sent"] is True
    assert body["email_error"] is None
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "student@uni.lu"


def test_create_order_with_student_uni_lu_email_is_also_allowed(client):
    with patch("app.send_order_confirmation", return_value=(True, None)):
        resp = client.post(
            "/api/orders",
            json={
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@student.uni.lu",
            },
        )
    assert resp.status_code == 201


def test_create_order_with_non_uni_lu_email_is_400(client):
    resp = client.post(
        "/api/orders",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_email": "student@gmail.com",
        },
    )
    assert resp.status_code == 400


def test_create_order_with_malformed_email_is_400(client):
    resp = client.post(
        "/api/orders",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_email": "not-an-email@uni.lu@uni.lu",
        },
    )
    assert resp.status_code == 400


def test_create_order_without_email_never_attempts_to_send_and_has_no_email_fields(client):
    with patch("app.send_order_confirmation") as mock_send:
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 201
    body = resp.get_json()
    assert "email_sent" not in body
    assert "email_error" not in body
    mock_send.assert_not_called()


def test_create_order_still_succeeds_even_when_sending_the_email_fails(client):
    # A flaky mail server must never turn a successful order into a 500.
    with patch("app.send_order_confirmation", return_value=(False, "connection refused")):
        resp = client.post(
            "/api/orders",
            json={
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@uni.lu",
            },
        )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["email_sent"] is False
    assert body["email_error"] == "connection refused"


def test_create_order_for_unavailable_date_is_409(client):
    resp = client.post(
        "/api/orders",
        json={"restaurant": "altius", "date": "2026-09-26", "items": [{"id": 0, "quantity": 1}]},  # no_menu
    )
    assert resp.status_code == 409


def test_create_order_without_items_is_400(client):
    resp = client.post("/api/orders", json={"restaurant": "altius", "date": "2026-09-24", "items": []})
    assert resp.status_code == 400


def test_create_order_with_invalid_item_id_is_400(client):
    resp = client.post(
        "/api/orders",
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": 999999, "quantity": 1}]},
    )
    assert resp.status_code == 400


def test_get_order_by_id_returns_the_confirmed_order(client):
    create_resp = client.post(
        "/api/orders",
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": BRETZEL_ID, "quantity": 2}]},
    )
    order_id = create_resp.get_json()["id"]

    resp = client.get(f"/api/orders/{order_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == order_id
    assert body["restaurant_code"] == "UDL-CKB-ALTIUS"
    assert body["items"][0]["quantity"] == 2


def test_get_order_unknown_id_is_404(client):
    resp = client.get("/api/orders/999999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API: Smart Lunch (Part 51)
# ---------------------------------------------------------------------------


def test_smart_lunch_no_constraints_gives_up_to_three_options(client):
    resp = client.post("/api/smart-lunch", json={"restaurant": "altius", "date": "2026-09-24"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert [o["tier"] for o in body["options"]] == ["main", "main_starter", "main_starter_dessert"]
    assert body["options"][0]["total_price"] == 6.00


def test_smart_lunch_vegan_preference_only_returns_the_vegan_main(client):
    resp = client.post(
        "/api/smart-lunch",
        json={"restaurant": "altius", "date": "2026-09-24", "dietary_preferences": ["vegan"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["options"]
    for option in body["options"]:
        assert option["items"][0]["name"] == "Aloo Palak au tofu"  # the real vegan main in this fixture


def test_smart_lunch_missing_fields_is_400(client):
    resp = client.post("/api/smart-lunch", json={"restaurant": "altius"})
    assert resp.status_code == 400


def test_smart_lunch_invalid_meal_preference_is_400(client):
    resp = client.post(
        "/api/smart-lunch",
        json={"restaurant": "altius", "date": "2026-09-24", "meal_preference": "not_a_real_tier"},
    )
    assert resp.status_code == 400


def test_smart_lunch_for_unavailable_date_is_409(client):
    resp = client.post("/api/smart-lunch", json={"restaurant": "altius", "date": "2026-09-26"})  # no_menu
    assert resp.status_code == 409


def test_smart_lunch_min_weight_relaxed_on_real_data(client):
    # The real fixture's daily-formula dishes have no published weight at
    # all -- this must be honestly relaxed, not faked or a hard failure.
    resp = client.post(
        "/api/smart-lunch",
        json={"restaurant": "altius", "date": "2026-09-24", "min_weight": 300},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["options"]
    assert "min_weight" not in body["matched_constraints"]
    assert {"constraint": "min_weight", "reason": "no_weight_data_available"} in body["unavailable_constraints"]


# ---------------------------------------------------------------------------
# Mobile SPA shell + admin
# ---------------------------------------------------------------------------


def test_root_serves_the_spa_shell(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'<div id="app"' in resp.data
    assert b"app.js" in resp.data
    assert b'name="viewport"' in resp.data


def test_admin_page_renders(client):
    resp = client.get("/admin/orderability")
    assert resp.status_code == 200
    assert b"Orderability debug" in resp.data
    assert b"AVAILABLE" in resp.data
