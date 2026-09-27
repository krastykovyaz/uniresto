import datetime
from unittest.mock import patch

import pytest

from app import create_app
from orderability_engine.cache import OrderabilityCache
from orderability_engine.delivery_subscribers import DeliverySubscriberStore
from orderability_engine.email_verification import EmailVerificationStore
from orderability_engine.models import TZINFO
from orderability_engine.orders import OrderStore
from orderability_engine.service import OrderabilityService
from restopolis.config import load_restaurants
from tests.orderability_helpers import FakeRestopolisClient

# Known from the real fixture (tests/fixtures/altius_week0.html), Thu 24 Sep:
# id 0 = "Salad'bar" (daily formula item, no weight in real data)
# id 32 = "Bretzel salé" (Constant products, 80 g -- real weight data)
SALAD_BAR_ID = 0
BRETZEL_ID = 32


def _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=None):
    restaurants = load_restaurants()
    fake_client = FakeRestopolisClient(week_html_by_offset={0: altius_html, 1: altius_closed_week_html})
    service = OrderabilityService(
        client=fake_client,
        cache=OrderabilityCache(tmp_path / "cache.db", ttl_seconds=900),
        restaurants=restaurants,
        today=fixture_today,
        # Pinned to the day BEFORE any test date, so it's before ANY test
        # date's same-day ordering deadline (evaluate_our_delivery)
        # regardless of that deadline's own cutoff time -- without this,
        # every route here would compare against the REAL wall clock (check_orderability
        # is always called with no explicit `now`, matching production),
        # making order-creation tests flaky/date-dependent on whenever the
        # suite happens to run rather than on the fixture's own "today".
        now=now or datetime.datetime.combine(fixture_today, datetime.time(12, 0), tzinfo=TZINFO),
    )
    order_store = OrderStore(tmp_path / "orders.db")
    delivery_subscriber_store = DeliverySubscriberStore(tmp_path / "orders.db")
    app = create_app(
        service=service,
        order_store=order_store,
        delivery_subscriber_store=delivery_subscriber_store,
        # Explicit ":memory:" instances -- isolated per test, never the
        # real email_verification.db/delivery_email_verification.db
        # files create_app() defaults to for the real app.
        email_verification_store=EmailVerificationStore(),
        delivery_verification_store=EmailVerificationStore(),
        # No background cache-warmer thread here -- this app/FakeRestopolisClient
        # only lives for one test, and the warmer's own behavior is covered
        # directly in tests/test_cache_warmer.py instead.
        enable_cache_warmer=False,
    )
    app.testing = True
    return app.test_client()


@pytest.fixture
def client(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today) as c:
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


def test_create_order_with_non_uni_lu_email_is_allowed(client):
    # customer_email is where confirmation mail actually gets sent, which
    # may deliberately be a personal address (the Profile "Communication
    # email" feature) -- only the University email itself (proving
    # affiliation) is restricted to uni.lu domains.
    with patch("app.send_order_confirmation", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/api/orders",
            json={
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@gmail.com",
            },
        )
    assert resp.status_code == 201
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "student@gmail.com"


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


def test_create_order_persists_customer_note(client):
    resp = client.post(
        "/api/orders",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_note": "no onion, please",
        },
    )
    assert resp.status_code == 201
    order_id = resp.get_json()["id"]
    body = client.get(f"/api/orders/{order_id}").get_json()
    assert body["customer_note"] == "no onion, please"


def test_create_order_with_overly_long_note_is_400(client):
    resp = client.post(
        "/api/orders",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_note": "x" * 501,
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


def test_create_order_after_our_deadline_is_409_even_though_restopolis_still_says_available(
    tmp_path, altius_html, altius_closed_week_html, fixture_today
):
    # Restopolis's own status for 2026-09-24 is "available" all day (see
    # test_api_status_available) -- but OUR same-day 13:00 cutoff
    # (evaluate_our_delivery) has its own, stricter deadline. The menu
    # stays browsable past that point (see
    # test_api_menu_still_available_after_our_deadline_has_passed below),
    # but creating an order must not silently succeed once we've told the
    # customer ordering is closed.
    after_deadline = datetime.datetime(2026, 9, 24, 13, 15, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=after_deadline) as late_client:
        resp = late_client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["status"] == "closed"


def test_api_menu_still_available_after_our_deadline_has_passed(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    # api_menu only ever gates on Restopolis's own status (never
    # our_delivery) -- a customer can still see what was on the menu even
    # once ordering has closed for the day.
    after_deadline = datetime.datetime(2026, 9, 24, 13, 15, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=after_deadline) as late_client:
        resp = late_client.get("/api/restaurants/altius/menu/2026-09-24")
    assert resp.status_code == 200


def test_api_status_reports_restopolis_available_but_our_delivery_closed_after_deadline(
    tmp_path, altius_html, altius_closed_week_html, fixture_today
):
    after_deadline = datetime.datetime(2026, 9, 24, 13, 15, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=after_deadline) as late_client:
        resp = late_client.get("/api/restaurants/altius/status?date=2026-09-24")
    body = resp.get_json()
    assert body["status"] == "available"
    assert body["our_delivery"]["available"] is False


def test_api_status_reports_early_cutoff_separately(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    # 09:00: past the early (08:00) grill/BBQ/salmon-only cutoff, but not
    # yet the general (13:00) one -- both are reported, never merged.
    past_early_cutoff = datetime.datetime(2026, 9, 24, 9, 0, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=past_early_cutoff) as c:
        resp = c.get("/api/restaurants/altius/status?date=2026-09-24")
    body = resp.get_json()
    assert body["our_delivery"]["available"] is True
    assert body["early_cutoff"]["available"] is False


# ---------------------------------------------------------------------------
# Early-cutoff dishes (grill/BBQ mains, salmon) needing the 08:00 deadline
# (Part 59) -- requires_early_order() is patched here rather than depending
# on a real fixture dish matching its keyword rule (already covered
# precisely in tests/test_menu_service.py); this only exercises the
# integration: app.py actually enforcing it once flagged.
# ---------------------------------------------------------------------------


def test_menu_items_carry_the_early_order_flag(client):
    with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
        resp = client.get("/api/restaurants/altius/menu/2026-09-24")
    body = resp.get_json()
    assert body["items"]
    assert all(it["requires_early_order"] is True for it in body["items"])


def test_create_order_rejects_early_cutoff_item_once_0800_has_passed(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    after_early_cutoff = datetime.datetime(2026, 9, 24, 9, 0, tzinfo=TZINFO)  # past 08:00, before the general 13:00 deadline
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=after_early_cutoff) as late_client:
        with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
            resp = late_client.post(
                "/api/orders",
                json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
            )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "early_cutoff_passed"


def test_create_order_allows_early_cutoff_item_before_0800(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    before_early_cutoff = datetime.datetime(2026, 9, 24, 7, 0, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=before_early_cutoff) as early_client:
        with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
            resp = early_client.post(
                "/api/orders",
                json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
            )
    assert resp.status_code == 201


def test_quote_rejects_early_cutoff_item_once_0800_has_passed(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    after_early_cutoff = datetime.datetime(2026, 9, 24, 9, 0, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=after_early_cutoff) as late_client:
        with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
            resp = late_client.post(
                "/api/orders/quote",
                json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
            )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "early_cutoff_passed"


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
    assert body["options"][0]["total_price"] == 6.70


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
# Email verification (Part 27)
# ---------------------------------------------------------------------------


def test_send_code_rejects_non_uni_lu_email(client):
    resp = client.post("/api/email/send-code", json={"email": "student@gmail.com"})
    assert resp.status_code == 400


def test_send_code_rejects_missing_email(client):
    resp = client.post("/api/email/send-code", json={})
    assert resp.status_code == 400


def test_send_code_success_issues_and_sends(client):
    with patch("app.send_verification_code", return_value=(True, None)) as mock_send:
        resp = client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sent"] is True
    assert body["error"] is None
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "student@uni.lu"


def test_send_code_reports_failure_without_erroring_the_request(client):
    with patch("app.send_verification_code", return_value=(False, "connection refused")):
        resp = client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sent"] is False
    assert body["error"] == "connection refused"


def test_send_code_a_second_time_immediately_is_rate_limited(client):
    with patch("app.send_verification_code", return_value=(True, None)):
        client.post("/api/email/send-code", json={"email": "student@uni.lu"})
        resp = client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    assert resp.status_code == 429
    body = resp.get_json()
    assert body["sent"] is False
    assert body["error"] == "rate_limited"
    assert body["retry_after_seconds"] > 0


def test_send_code_failure_does_not_trigger_the_resend_cooldown(client):
    # A delivery failure must never lock the user out of retrying
    # immediately -- only a genuinely successful send starts the cooldown.
    with patch("app.send_verification_code", return_value=(False, "connection refused")):
        client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    with patch("app.send_verification_code", return_value=(True, None)):
        resp = client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    assert resp.status_code == 200
    assert resp.get_json()["sent"] is True


def test_verify_code_with_no_code_requested_fails(client):
    resp = client.post("/api/email/verify-code", json={"email": "student@uni.lu", "code": "123456"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["verified"] is False
    assert body["reason"] == "no_code_requested"


def test_verify_code_end_to_end_with_the_real_code(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    resp = client.post("/api/email/verify-code", json={"email": "student@uni.lu", "code": "654321"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["verified"] is True
    assert body["reason"] is None


def test_verify_code_with_wrong_code_fails(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    resp = client.post("/api/email/verify-code", json={"email": "student@uni.lu", "code": "000000"})
    body = resp.get_json()
    assert body["verified"] is False
    assert body["reason"] == "incorrect_code"


def test_verify_code_missing_fields_is_400(client):
    assert client.post("/api/email/verify-code", json={"email": "student@uni.lu"}).status_code == 400
    assert client.post("/api/email/verify-code", json={"code": "123456"}).status_code == 400


# ---------------------------------------------------------------------------
# Delivery registration + real orders (Part 52+)
# ---------------------------------------------------------------------------


def test_delivery_register_send_code_allows_non_uni_lu_email(client):
    # Deliberately relaxed (Part 61): a personal address is the MORE
    # reliable destination for delivery notifications, since university
    # inboxes sometimes block this app's automated mail. Still code-
    # verified -- only the domain restriction is gone.
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        resp = client.post("/api/delivery/register/send-code", json={"email": "courier@gmail.com"})
    assert resp.status_code == 200
    assert resp.get_json()["sent"] is True


def test_delivery_register_send_code_rejects_malformed_email(client):
    resp = client.post("/api/delivery/register/send-code", json={"email": "not-an-email"})
    assert resp.status_code == 400


def test_delivery_register_verify_code_persists_the_subscriber(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/delivery/register/send-code", json={"email": "courier@uni.lu"})
    resp = client.post("/api/delivery/register/verify-code", json={"email": "courier@uni.lu", "code": "654321"})
    assert resp.get_json()["verified"] is True
    assert "courier@uni.lu" in client.application.config["DELIVERY_SUBSCRIBER_STORE"].list_emails()


def test_delivery_register_verify_code_persists_a_private_address_too(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/delivery/register/send-code", json={"email": "courier@gmail.com"})
    resp = client.post("/api/delivery/register/verify-code", json={"email": "courier@gmail.com", "code": "654321"})
    assert resp.get_json()["verified"] is True
    assert "courier@gmail.com" in client.application.config["DELIVERY_SUBSCRIBER_STORE"].list_emails()


def test_delivery_register_verify_code_wrong_code_does_not_persist(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/delivery/register/send-code", json={"email": "courier@uni.lu"})
    resp = client.post("/api/delivery/register/verify-code", json={"email": "courier@uni.lu", "code": "000000"})
    assert resp.get_json()["verified"] is False
    assert "courier@uni.lu" not in client.application.config["DELIVERY_SUBSCRIBER_STORE"].list_emails()


def test_delivery_register_code_is_not_accepted_by_customer_email_verification(client):
    # A code issued for courier registration must not also verify the
    # customer checkout email flow (two separate EmailVerificationStore
    # instances) -- and vice versa (test_verify_code_with_no_code_requested_fails
    # already covers the customer store never having seen this address).
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/delivery/register/send-code", json={"email": "student@uni.lu"})
    resp = client.post("/api/email/verify-code", json={"email": "student@uni.lu", "code": "654321"})
    assert resp.get_json()["verified"] is False
    assert resp.get_json()["reason"] == "no_code_requested"


def test_delivery_register_quick_persists_the_subscriber_with_no_code(client):
    resp = client.post("/api/delivery/register/quick", json={"email": "courier@uni.lu"})
    assert resp.status_code == 200
    assert resp.get_json()["registered"] is True
    assert "courier@uni.lu" in client.application.config["DELIVERY_SUBSCRIBER_STORE"].list_emails()


def test_delivery_register_quick_rejects_non_uni_lu_email(client):
    resp = client.post("/api/delivery/register/quick", json={"email": "courier@gmail.com"})
    assert resp.status_code == 400
    assert "courier@gmail.com" not in client.application.config["DELIVERY_SUBSCRIBER_STORE"].list_emails()


def test_delivery_register_quick_requires_email(client):
    resp = client.post("/api/delivery/register/quick", json={})
    assert resp.status_code == 400


def test_delivery_orders_returns_real_orders_and_strips_customer_email(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    resp = client.get("/api/delivery/orders")
    assert resp.status_code == 200
    orders = resp.get_json()
    assert any(o["id"] == order_id for o in orders)
    for o in orders:
        assert "customer_email" not in o


def test_delivery_orders_excludes_cancelled(client):
    order_id = _create_basic_order(client)
    store = client.application.config["ORDER_STORE"]
    token = store.set_real_price(order_id, 6.70)
    store.cancel_order(order_id, token)
    resp = client.get("/api/delivery/orders")
    assert order_id not in [o["id"] for o in resp.get_json()]


def test_create_order_notifies_every_registered_courier(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/delivery/register/send-code", json={"email": "courier@uni.lu"})
    client.post("/api/delivery/register/verify-code", json={"email": "courier@uni.lu", "code": "654321"})

    with patch("app.send_admin_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ) as mock_notify:
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 201
    mock_notify.assert_called_once()
    assert mock_notify.call_args[0][0] == "courier@uni.lu"
    assert mock_notify.call_args[0][1]["id"] == resp.get_json()["id"]


def test_create_order_with_no_registered_couriers_notifies_no_one(client):
    with patch("app.send_admin_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification"
    ) as mock_notify:
        client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    mock_notify.assert_not_called()


def test_create_order_still_succeeds_when_courier_notification_fails(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/delivery/register/send-code", json={"email": "courier@uni.lu"})
    client.post("/api/delivery/register/verify-code", json={"email": "courier@uni.lu", "code": "654321"})

    with patch("app.send_admin_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", side_effect=Exception("smtp exploded")
    ):
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Admin confirmation workflow (Part 30)
# ---------------------------------------------------------------------------


def _create_basic_order(client, customer_email=None, customer_note=None):
    payload = {"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]}
    if customer_email:
        payload["customer_email"] = customer_email
    if customer_note:
        payload["customer_note"] = customer_note
    with patch("app.send_admin_notification", return_value=(True, None)):
        resp = client.post("/api/orders", json=payload)
    return resp.get_json()["id"]


def test_create_order_pings_the_admin_via_telegram(client):
    with patch("app.send_admin_notification", return_value=(True, None)) as mock_notify:
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 201
    mock_notify.assert_called_once()
    order_arg = mock_notify.call_args[0][0]
    assert order_arg["id"] == resp.get_json()["id"]


def test_create_order_passes_a_mark_reviewing_url_when_admin_token_is_set(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    with patch("app.send_admin_notification", return_value=(True, None)) as mock_notify:
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    order_id = resp.get_json()["id"]
    mark_reviewing_url = mock_notify.call_args.kwargs["mark_reviewing_url"]
    assert mark_reviewing_url is not None
    assert f"/admin/orders/{order_id}/mark-reviewing" in mark_reviewing_url
    assert "token=correct-token" in mark_reviewing_url


def test_create_order_passes_a_restopolis_url_for_the_ordered_restaurant(client):
    # Unlike admin_url/mark_reviewing_url, this one never depends on
    # ADMIN_TOKEN -- it points at Restopolis's own site, not ours.
    with patch("app.send_admin_notification", return_value=(True, None)) as mock_notify:
        client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    restopolis_url = mock_notify.call_args.kwargs["restopolis_url"]
    assert restopolis_url is not None
    assert restopolis_url.startswith("https://ssl.education.lu/eRestauration/CustomerServices/Menu/BtnChangeRestaurant")
    # 164 = Altius's real restaurant_id (restaurants.yaml) -- never guessed.
    assert "pRestaurantSelection=164" in restopolis_url


def test_create_order_mark_reviewing_url_is_none_without_admin_token(client):
    with patch("app.send_admin_notification", return_value=(True, None)) as mock_notify:
        client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert mock_notify.call_args.kwargs["mark_reviewing_url"] is None


def test_create_order_still_succeeds_when_telegram_notify_fails(client):
    # Best-effort, same as the email confirmation -- a Telegram failure
    # must never turn a successful order into a 500.
    with patch("app.send_admin_notification", return_value=(False, "chat not found")):
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 201


def test_admin_orders_without_admin_token_configured_is_404(client):
    resp = client.get("/admin/orders?token=anything")
    assert resp.status_code == 404


def test_admin_orders_with_wrong_token_is_404(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    resp = client.get("/admin/orders?token=wrong-token")
    assert resp.status_code == 404


def test_admin_orders_with_correct_token_lists_pending_orders(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    resp = client.get("/admin/orders?token=correct-token")
    assert resp.status_code == 200
    assert f"Order #{order_id}".encode() in resp.data


def test_admin_orders_shows_customer_note(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu", customer_note="no onion, please")
    resp = client.get("/admin/orders?token=correct-token")
    assert resp.status_code == 200
    assert b"no onion, please" in resp.data
    assert f"Order #{order_id}".encode() in resp.data


def test_admin_orders_lists_reviewing_orders_too(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    client.get(f"/admin/orders/{order_id}/mark-reviewing?token=correct-token")
    resp = client.get("/admin/orders?token=correct-token")
    assert resp.status_code == 200
    assert f"Order #{order_id}".encode() in resp.data


def test_admin_mark_reviewing_without_token_is_404(client):
    order_id = _create_basic_order(client)
    resp = client.get(f"/admin/orders/{order_id}/mark-reviewing")
    assert resp.status_code == 404


def test_admin_mark_reviewing_with_wrong_token_is_404(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    resp = client.get(f"/admin/orders/{order_id}/mark-reviewing?token=wrong-token")
    assert resp.status_code == 404


def test_admin_mark_reviewing_flips_status_and_redirects(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    resp = client.get(f"/admin/orders/{order_id}/mark-reviewing?token=correct-token")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/orders?token=correct-token"
    order = client.get(f"/api/orders/{order_id}").get_json()
    assert order["status"] == "reviewing"


def test_admin_set_price_without_token_is_404(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    resp = client.post(f"/admin/orders/{order_id}/set-price", data={"real_price": "8.50"})
    assert resp.status_code == 404


def test_admin_set_price_success_emails_customer_and_redirects(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")

    with patch("app.send_order_needs_confirmation", return_value=(True, None)) as mock_send:
        resp = client.post(
            f"/admin/orders/{order_id}/set-price?token=correct-token",
            data={"real_price": "8.50", "token": "correct-token"},
        )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/admin/orders?token=correct-token"
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0]
    assert call_args[0] == "student@uni.lu"
    assert call_args[2] == 8.50
    assert f"/o/{order_id}/confirm" in call_args[3]
    assert f"/o/{order_id}/cancel" in call_args[4]

    order = client.get(f"/api/orders/{order_id}").get_json()
    assert order["status"] == "awaiting_confirmation"
    assert order["real_price"] == 8.50


def test_admin_set_price_for_order_without_email_is_400(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)  # no customer_email
    resp = client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "8.50"})
    assert resp.status_code == 400


def test_admin_set_price_invalid_price_is_400(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    resp = client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "not-a-number"})
    assert resp.status_code == 400


def test_admin_set_price_twice_is_409(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_needs_confirmation", return_value=(True, None)):
        client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "8.50"})
        resp = client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "9.00"})
    assert resp.status_code == 409


def test_order_confirm_with_valid_token_succeeds(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_needs_confirmation", return_value=(True, None)) as mock_send:
        client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "8.50"})
    confirm_url = mock_send.call_args[0][3]
    path = confirm_url.split("://", 1)[1].split("/", 1)[1]  # strip scheme+host, keep "/o/<id>/confirm?token=..."

    resp = client.get(f"/{path}")
    assert resp.status_code == 200
    assert b"confirmed" in resp.data.lower()
    order = client.get(f"/api/orders/{order_id}").get_json()
    assert order["status"] == "confirmed"


def test_order_confirm_with_invalid_token_shows_error_not_confirmed(client):
    resp = client.get("/o/999999/confirm?token=nonsense")
    assert resp.status_code == 200
    assert b"link isn" in resp.data  # "This link isn't valid anymore" (apostrophe may be HTML-escaped)
    assert b"Order confirmed" not in resp.data


def test_order_cancel_with_valid_token_succeeds(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_needs_confirmation", return_value=(True, None)) as mock_send:
        client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "8.50"})
    cancel_url = mock_send.call_args[0][4]
    path = cancel_url.split("://", 1)[1].split("/", 1)[1]

    resp = client.get(f"/{path}")
    assert resp.status_code == 200
    assert b"cancelled" in resp.data.lower()
    order = client.get(f"/api/orders/{order_id}").get_json()
    assert order["status"] == "cancelled"


def test_order_confirm_link_cannot_be_replayed(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_needs_confirmation", return_value=(True, None)) as mock_send:
        client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "8.50"})
    confirm_url = mock_send.call_args[0][3]
    path = confirm_url.split("://", 1)[1].split("/", 1)[1]

    first = client.get(f"/{path}")
    second = client.get(f"/{path}")
    assert b"Order confirmed" in first.data
    assert b"Order confirmed" not in second.data


# ---------------------------------------------------------------------------
# Mobile SPA shell + admin
# ---------------------------------------------------------------------------


def test_root_serves_the_spa_shell(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'<div id="app"' in resp.data
    assert b"app.js" in resp.data
    assert b'name="viewport"' in resp.data
    assert b'rel="icon"' in resp.data
    assert b'rel="apple-touch-icon"' in resp.data


def test_favicon_ico_redirects_to_the_real_png(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code in (301, 302)
    assert resp.headers["Location"].endswith("/static/favicon-32.png")


def test_admin_page_renders(client):
    resp = client.get("/admin/orderability")
    assert resp.status_code == 200
    assert b"Orderability debug" in resp.data
    assert b"AVAILABLE" in resp.data
