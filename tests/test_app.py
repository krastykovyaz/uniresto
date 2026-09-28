import datetime
import io
from unittest.mock import patch

import pytest

from app import create_app
from orderability_engine.cache import OrderabilityCache
from orderability_engine.coming_soon_clicks import ComingSoonClickStore
from orderability_engine.daily_report import DailyReportStore
from orderability_engine.delivery_subscribers import DeliverySubscriberStore
from orderability_engine.dish_photos import DishPhotoStore
from orderability_engine.pending_dish_photos import PendingDishPhotoStore
from orderability_engine.email_verification import EmailVerificationStore
from orderability_engine.feedback import FeedbackStore
from orderability_engine.models import TZINFO
from orderability_engine.orders import OrderStore
from orderability_engine.page_views import PageViewStore
from orderability_engine.rate_limits import RateLimitStore
from orderability_engine.service import OrderabilityService
from orderability_engine.verified_emails import VerifiedEmailStore
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
    # The request path never live-fetches on its own anymore (see
    # menu_refresh.py) -- every test in this file expects real fixture
    # data back from a plain (non-refresh) call, so simulate the
    # scheduler's own immediate startup sweep here: one forced fetch per
    # fixture week actually registered with fake_client (0 and 1), which
    # is all every test date in this file falls into. NOT
    # menu_refresh.refresh_all_once's full 42-day sweep, which would also
    # probe weeks this fake client has no fixture for.
    altius = restaurants["UDL-CKB-ALTIUS"]
    service.check_orderability(altius, fixture_today, refresh=True)
    service.check_orderability(altius, fixture_today + datetime.timedelta(days=7), refresh=True)

    order_store = OrderStore(tmp_path / "orders.db")
    verified_email_store = VerifiedEmailStore(tmp_path / "orders.db")
    # Part 83: "student@uni.lu" is this whole file's canonical placeholder
    # customer email -- pre-verifying it here (once, for every test using
    # this client) is far more honest than sprinkling individual
    # mark_verified() calls across dozens of tests that were never ABOUT
    # verification in the first place. Tests that specifically exercise
    # the verification requirement (or a different address) mark/omit it
    # explicitly themselves.
    verified_email_store.mark_verified("student@uni.lu")
    dish_photo_store = DishPhotoStore(tmp_path / "orders.db")
    pending_dish_photo_store = PendingDishPhotoStore(tmp_path / "orders.db")
    delivery_subscriber_store = DeliverySubscriberStore(tmp_path / "orders.db")
    coming_soon_click_store = ComingSoonClickStore(tmp_path / "orders.db")
    feedback_store = FeedbackStore(tmp_path / "orders.db")
    page_view_store = PageViewStore(tmp_path / "orders.db")
    daily_report_store = DailyReportStore(tmp_path / "orders.db")
    rate_limit_store = RateLimitStore(tmp_path / "orders.db")
    app = create_app(
        service=service,
        order_store=order_store,
        verified_email_store=verified_email_store,
        dish_photo_store=dish_photo_store,
        dish_photo_dir=tmp_path / "dish_photos",
        pending_dish_photo_store=pending_dish_photo_store,
        delivery_subscriber_store=delivery_subscriber_store,
        coming_soon_click_store=coming_soon_click_store,
        feedback_store=feedback_store,
        page_view_store=page_view_store,
        daily_report_store=daily_report_store,
        rate_limit_store=rate_limit_store,
        # Explicit ":memory:" instances -- isolated per test, never the
        # real email_verification.db/delivery_email_verification.db/
        # checkout_email_verification.db files create_app() defaults to
        # for the real app.
        email_verification_store=EmailVerificationStore(),
        delivery_verification_store=EmailVerificationStore(),
        checkout_verification_store=EmailVerificationStore(),
        # No background menu-refresh/daily-report threads here -- this
        # app/FakeRestopolisClient only lives for one test, and each
        # scheduler's own behavior is covered directly in its own test
        # file instead (test_menu_refresh.py, test_daily_report.py).
        enable_menu_refresh_scheduler=False,
        enable_daily_report_scheduler=False,
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
# API: crowd-sourced dish photos (Part 84)
# ---------------------------------------------------------------------------

# A real (if tiny) PNG: signature + IHDR/IEND-shaped bytes are irrelevant to
# api_upload_dish_photo, which only sniffs the leading signature -- see
# _sniff_dish_photo_extension in app.py. Reused across every "valid upload"
# test below via a helper rather than inlined, so unsupported-type/
# too-large tests read as obviously-deliberate deviations from it.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_dish_photos_starts_empty_for_a_restaurant(client):
    resp = client.get("/api/restaurants/altius/dish-photos")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_dish_photos_unknown_restaurant_is_404(client):
    assert client.get("/api/restaurants/does-not-exist/dish-photos").status_code == 404


def _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=_PNG_BYTES, filename="dish.png"):
    return client.post(
        "/api/restaurants/altius/dish-photos",
        data={"category": category, "name": name, "photo": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def test_upload_dish_photo_is_pending_not_immediately_listed(client):
    resp = _upload_dish_photo(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "pending"
    assert isinstance(body["id"], int)
    assert body["photo_path"].startswith("/static/dish_photos/") and body["photo_path"].endswith(".png")

    # Not live -- api_dish_photos (what every OTHER student's card reads)
    # must stay empty until an admin actually approves it.
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}


def test_pending_dish_photo_is_served_back_from_static(client):
    resp = _upload_dish_photo(client)
    photo_path = resp.get_json()["photo_path"]
    served = client.get(photo_path)
    assert served.status_code == 200
    assert served.data == _PNG_BYTES


def test_upload_dish_photo_missing_category_or_name_is_400(client):
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"name": "Salad'bar", "photo": (io.BytesIO(_PNG_BYTES), "dish.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_dish_photo_missing_file_is_400(client):
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"category": "Végétarien", "name": "Salad'bar"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_dish_photo_rejects_a_non_image_file(client):
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"category": "Végétarien", "name": "Salad'bar", "photo": (io.BytesIO(b"<script>alert(1)</script>"), "evil.svg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unsupported_type"


def test_upload_dish_photo_rejects_an_oversized_file(client):
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * (8 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"category": "Végétarien", "name": "Salad'bar", "photo": (io.BytesIO(huge), "big.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "too_large"


def test_upload_dish_photo_unknown_restaurant_is_404(client):
    resp = client.post(
        "/api/restaurants/does-not-exist/dish-photos",
        data={"category": "Végétarien", "name": "Salad'bar", "photo": (io.BytesIO(_PNG_BYTES), "dish.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 404


def test_upload_dish_photo_is_scoped_per_restaurant(client):
    client.post(
        "/api/restaurants/altius/dish-photos",
        data={"category": "Végétarien", "name": "Salad'bar", "photo": (io.BytesIO(_PNG_BYTES), "dish.png")},
        content_type="multipart/form-data",
    )
    # brasserie-johns -- the other real restaurant in restaurants.yaml
    # (see UDL-CKB-BRASSERIE-JOHNS), never uploaded to in this test.
    assert client.get("/api/restaurants/brasserie-johns/dish-photos").get_json() == {}


# ---------------------------------------------------------------------------
# Admin: dish photo review queue (Part 84)
# ---------------------------------------------------------------------------


def test_admin_dish_photos_requires_token(client):
    assert client.get("/admin/dish-photos").status_code == 404


def test_admin_dish_photos_lists_pending_submissions(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    _upload_dish_photo(client, name="Salad'bar")
    resp = client.get("/admin/dish-photos?token=correct-token")
    assert resp.status_code == 200
    assert b"Salad&#39;bar" in resp.data or b"Salad'bar" in resp.data


def test_admin_dish_photo_review_page_shows_the_pending_entry(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    pending_id = _upload_dish_photo(client).get_json()["id"]
    resp = client.get(f"/admin/dish-photos/{pending_id}?token=correct-token")
    assert resp.status_code == 200
    assert b"Salad" in resp.data


def test_admin_dish_photo_review_page_for_unknown_id_is_friendly_not_404(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    resp = client.get("/admin/dish-photos/999999?token=correct-token")
    assert resp.status_code == 200
    assert b"already approved or rejected" in resp.data


def test_admin_approve_dish_photo_publishes_it(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client, category="Végétarien", name="Salad'bar").get_json()
    resp = client.get(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
    assert resp.status_code == 200
    assert b"approved" in resp.data.lower()

    listed = client.get("/api/restaurants/altius/dish-photos").get_json()
    assert listed == {"Végétarien": {"Salad'bar": upload["photo_path"]}}
    # Consumed -- no longer sitting in the pending queue.
    assert client.get("/admin/dish-photos?token=correct-token").data.count(b"Approve") == 0


def test_admin_approve_dish_photo_requires_token(client):
    upload = _upload_dish_photo(client).get_json()
    assert client.get(f"/admin/dish-photos/{upload['id']}/approve").status_code == 404
    # Never approved without the token -- still not live.
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}


def test_admin_approve_dish_photo_twice_is_a_friendly_no_op_the_second_time(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client).get_json()
    client.get(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
    resp = client.get(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
    assert resp.status_code == 200
    assert b"isn&#39;t valid anymore" in resp.data or b"isn't valid anymore" in resp.data


def test_admin_reject_dish_photo_discards_it(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client, category="Végétarien", name="Salad'bar").get_json()
    resp = client.get(f"/admin/dish-photos/{upload['id']}/reject?token=correct-token")
    assert resp.status_code == 200
    assert b"rejected" in resp.data.lower()

    # Discarded, not published -- and the file itself is gone too.
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}
    assert client.get(upload["photo_path"]).status_code == 404


def test_admin_reject_dish_photo_requires_token(client):
    upload = _upload_dish_photo(client).get_json()
    assert client.get(f"/admin/dish-photos/{upload['id']}/reject").status_code == 404
    assert client.get(upload["photo_path"]).status_code == 200  # file untouched


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
            "customer_email": "student@uni.lu",
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
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("student@student.uni.lu")
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
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("student@gmail.com")
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
            "customer_email": "student@uni.lu",
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
            "customer_email": "student@uni.lu",
        },
    )
    assert resp.status_code == 400


def test_create_order_without_email_is_400(client):
    # customer_email became required after a real delivery got stuck with
    # no way to reach the customer at all (an ambiguous delivery_location
    # and no email/phone on file) -- an order can no longer be created
    # without one.
    with patch("app.send_order_confirmation") as mock_send:
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 400
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
        json={"restaurant": "altius", "date": "2026-09-26", "items": [{"id": 0, "quantity": 1}], "customer_email": "student@uni.lu"},  # no_menu
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
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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
                json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
            )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "early_cutoff_passed"


def test_create_order_allows_early_cutoff_item_before_0800(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    before_early_cutoff = datetime.datetime(2026, 9, 24, 7, 0, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=before_early_cutoff) as early_client:
        with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
            resp = early_client.post(
                "/api/orders",
                json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
            )
    assert resp.status_code == 201


def test_quote_rejects_early_cutoff_item_once_0800_has_passed(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    after_early_cutoff = datetime.datetime(2026, 9, 24, 9, 0, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=after_early_cutoff) as late_client:
        with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
            resp = late_client.post(
                "/api/orders/quote",
                json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
            )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "early_cutoff_passed"


def test_create_order_without_items_is_400(client):
    resp = client.post("/api/orders", json={"restaurant": "altius", "date": "2026-09-24", "items": []})
    assert resp.status_code == 400


def test_create_order_with_invalid_item_id_is_400(client):
    resp = client.post(
        "/api/orders",
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": 999999, "quantity": 1}], "customer_email": "student@uni.lu"},
    )
    assert resp.status_code == 400


def test_get_order_by_id_returns_the_confirmed_order(client):
    create_resp = client.post(
        "/api/orders",
        json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": BRETZEL_ID, "quantity": 2}], "customer_email": "student@uni.lu"},
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


def test_orders_email_send_code_allows_non_uni_lu_email(client):
    # Same relaxed domain reasoning as delivery registration -- checkout
    # itself never restricted customer_email to uni.lu, only proving it's
    # real matters here.
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        resp = client.post("/api/orders/email/send-code", json={"email": "customer@gmail.com"})
    assert resp.status_code == 200
    assert resp.get_json()["sent"] is True


def test_orders_email_send_code_rejects_malformed_email(client):
    resp = client.post("/api/orders/email/send-code", json={"email": "not-an-email"})
    assert resp.status_code == 400


def test_orders_email_verify_code_marks_the_address_verified(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/orders/email/send-code", json={"email": "customer@gmail.com"})
    resp = client.post("/api/orders/email/verify-code", json={"email": "customer@gmail.com", "code": "654321"})
    assert resp.get_json()["verified"] is True
    assert client.application.config["VERIFIED_EMAIL_STORE"].is_verified("customer@gmail.com") is True


def test_orders_email_verify_code_wrong_code_does_not_mark_verified(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/orders/email/send-code", json={"email": "customer@gmail.com"})
    resp = client.post("/api/orders/email/verify-code", json={"email": "customer@gmail.com", "code": "000000"})
    assert resp.get_json()["verified"] is False
    assert client.application.config["VERIFIED_EMAIL_STORE"].is_verified("customer@gmail.com") is False


def test_orders_email_code_is_not_accepted_by_delivery_register_verification(client):
    # A code issued for checkout must not also verify courier
    # registration (a separate EmailVerificationStore instance) -- and
    # vice versa (test_delivery_register_code_is_not_accepted_by_
    # customer_email_verification already covers that direction).
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/orders/email/send-code", json={"email": "student@gmail.com"})
    resp = client.post("/api/delivery/register/verify-code", json={"email": "student@gmail.com", "code": "654321"})
    assert resp.get_json()["verified"] is False
    assert resp.get_json()["reason"] == "no_code_requested"


def test_university_email_verification_also_unlocks_ordering(client):
    # VerifiedEmailStore is shared across all three flows (Part 83) --
    # proving an address via the University-email flow is just as good
    # as proving it via checkout's own, so it must not have to be
    # re-verified.
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/email/send-code", json={"email": "student@uni.lu"})
    client.post("/api/email/verify-code", json={"email": "student@uni.lu", "code": "654321"})
    assert client.application.config["VERIFIED_EMAIL_STORE"].is_verified("student@uni.lu") is True


def test_delivery_register_verification_also_unlocks_ordering(client):
    with patch("app.generate_verification_code", return_value="654321"), patch(
        "app.send_verification_code", return_value=(True, None)
    ):
        client.post("/api/delivery/register/send-code", json={"email": "courier@gmail.com"})
    client.post("/api/delivery/register/verify-code", json={"email": "courier@gmail.com", "code": "654321"})
    assert client.application.config["VERIFIED_EMAIL_STORE"].is_verified("courier@gmail.com") is True


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


def test_delivery_orders_includes_cancelled_as_closed(client):
    # Part 73: the Delivery screen now buckets a cancelled order into its
    # own "Closed" section (static/app.js's deliveryOrderSections())
    # rather than hiding it outright -- the API itself has to keep
    # returning it for that section to have anything to show.
    order_id = _create_basic_order(client)
    store = client.application.config["ORDER_STORE"]
    token = store.set_real_price(order_id, 6.70)
    store.cancel_order(order_id, token)
    resp = client.get("/api/delivery/orders")
    order = next(o for o in resp.get_json() if o["id"] == order_id)
    assert order["status"] == "cancelled"


def _claim(client, order_id, courier_email="courier@uni.lu", lang=None):
    body = {"courier_email": courier_email}
    if lang:
        body["lang"] = lang
    return client.post(f"/api/orders/{order_id}/claim", json=body)


def test_claim_order_notifies_admin(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_claimed_notification", return_value=(True, None)) as mock_notify, patch(
        "app.send_delivery_notification", return_value=(True, None)
    ):
        resp = _claim(client, order_id)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["claimed"] is True
    assert body["already_claimed"] is False
    mock_notify.assert_called_once()
    order_arg = mock_notify.call_args[0][0]
    assert order_arg["id"] == order_id
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["claimed_at"] is not None


def test_claim_order_without_courier_email_is_400(client):
    order_id = _create_basic_order(client)
    resp = client.post(f"/api/orders/{order_id}/claim", json={})
    assert resp.status_code == 400


def test_claim_order_with_malformed_courier_email_is_400(client):
    order_id = _create_basic_order(client)
    resp = client.post(f"/api/orders/{order_id}/claim", json={"courier_email": "not-an-email"})
    assert resp.status_code == 400


def test_claim_order_emails_the_courier_the_order_description(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ) as mock_email:
        _claim(client, order_id, courier_email="courier@uni.lu", lang="fr")
    mock_email.assert_called_once()
    assert mock_email.call_args[0][0] == "courier@uni.lu"
    assert mock_email.call_args[0][1]["id"] == order_id
    assert mock_email.call_args.kwargs["courier_lang"] == "fr"


def test_claim_order_emails_the_customer_accepted_when_an_email_was_given(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_accepted", return_value=(True, None)) as mock_email:
        _claim(client, order_id)
    mock_email.assert_called_once()
    assert mock_email.call_args[0][0] == "student@uni.lu"


def test_claim_order_does_not_email_customer_when_no_customer_email_was_given(client):
    order_id = _create_order_without_email(client)
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_accepted", return_value=(True, None)) as mock_email:
        _claim(client, order_id)
    mock_email.assert_not_called()


def test_claim_order_second_tap_does_not_renotify(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_claimed_notification", return_value=(True, None)) as mock_notify, patch(
        "app.send_delivery_notification", return_value=(True, None)
    ):
        _claim(client, order_id)
        resp = _claim(client, order_id)
    assert resp.status_code == 200
    assert resp.get_json() == {"claimed": True, "already_claimed": True}
    mock_notify.assert_called_once()


def test_claim_order_refuses_a_cancelled_order_without_notifying(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    store = client.application.config["ORDER_STORE"]
    token = store.set_real_price(order_id, 6.70)
    store.cancel_order(order_id, token)
    with patch("app.send_order_claimed_notification") as mock_notify, patch(
        "app.send_order_accepted"
    ) as mock_email:
        resp = _claim(client, order_id)
    assert resp.status_code == 409
    mock_notify.assert_not_called()
    mock_email.assert_not_called()
    assert store.get_order(order_id)["claimed_at"] is None


def test_claim_order_refuses_an_already_delivered_order_without_notifying(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    client.post(f"/api/orders/{order_id}/mark-delivered")
    with patch("app.send_order_claimed_notification") as mock_notify, patch(
        "app.send_order_accepted"
    ) as mock_email:
        resp = _claim(client, order_id)
    assert resp.status_code == 409
    mock_notify.assert_not_called()
    mock_email.assert_not_called()


def test_unclaim_releases_the_order_and_pings_the_admin(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ):
        _claim(client, order_id)
    with patch("app.send_order_released_notification", return_value=(True, None)) as mock_released:
        resp = client.post(f"/api/orders/{order_id}/unclaim")
    assert resp.status_code == 200
    mock_released.assert_called_once()
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["claimed_at"] is None


def test_unclaim_an_unclaimed_order_is_a_409_without_pinging(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_released_notification") as mock_released:
        resp = client.post(f"/api/orders/{order_id}/unclaim")
    assert resp.status_code == 409
    mock_released.assert_not_called()


def test_unclaim_after_pickup_is_a_409(client):
    # Once the food is physically in hand, "release" no longer makes
    # real-world sense (see OrderStore.mark_unclaimed()'s own docstring).
    order_id = _create_basic_order(client)
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ):
        _claim(client, order_id)
    client.post(f"/api/orders/{order_id}/picked-up")
    with patch("app.send_order_released_notification") as mock_released:
        resp = client.post(f"/api/orders/{order_id}/unclaim")
    assert resp.status_code == 409
    mock_released.assert_not_called()


def test_reclaiming_after_a_release_never_emails_the_customer_twice(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_claimed_notification", return_value=(True, None)) as mock_claimed, patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_released_notification", return_value=(True, None)), patch(
        "app.send_order_accepted", return_value=(True, None)
    ) as mock_email:
        _claim(client, order_id)
        client.post(f"/api/orders/{order_id}/unclaim")
        _claim(client, order_id)
    # The admin hears about both claims (it was dropped in between)...
    assert mock_claimed.call_count == 2
    # ...but the customer only ever gets "accepted" once.
    mock_email.assert_called_once()


def test_mark_picked_up_emails_the_customer_on_its_way(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_accepted", return_value=(True, None)):
        _claim(client, order_id)
    with patch("app.send_order_out_for_delivery", return_value=(True, None)) as mock_email:
        resp = client.post(f"/api/orders/{order_id}/picked-up")
    assert resp.status_code == 200
    assert resp.get_json() == {"picked_up": True}
    mock_email.assert_called_once()
    assert mock_email.call_args[0][0] == "student@uni.lu"
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["picked_up_at"] is not None


def test_mark_picked_up_before_claiming_is_409(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_out_for_delivery") as mock_email:
        resp = client.post(f"/api/orders/{order_id}/picked-up")
    assert resp.status_code == 409
    mock_email.assert_not_called()


def test_mark_picked_up_twice_does_not_reemail(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_accepted", return_value=(True, None)):
        _claim(client, order_id)
    with patch("app.send_order_out_for_delivery", return_value=(True, None)) as mock_email:
        client.post(f"/api/orders/{order_id}/picked-up")
        resp = client.post(f"/api/orders/{order_id}/picked-up")
    assert resp.status_code == 409
    mock_email.assert_called_once()


def test_delivery_orders_strips_courier_email(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ):
        _claim(client, order_id, courier_email="courier@uni.lu")
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert "courier_email" not in listed
    assert "courier_lang" not in listed


def test_delivery_orders_carry_a_server_side_expired_flag(client):
    # The fixture order is for 2026-09-24; the real clock is later, so it's
    # past 15:00 Luxembourg on its date -- decided here, not on the device.
    order_id = _create_basic_order(client)
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["expired"] is True


def _post_n(client, url, n, **kw):
    return [client.post(url, **kw).status_code for _ in range(n)]


def test_feedback_is_rate_limited_per_client(client):
    with patch("app.send_feedback_notification", return_value=(True, None)) as mock_notify:
        codes = _post_n(client, "/api/feedback", 6, json={"message": "hi"})
    assert codes == [200] * 5 + [429]
    assert mock_notify.call_count == 5  # the blocked one never reached Telegram


def test_429_says_when_to_retry(client):
    for _ in range(5):
        client.post("/api/feedback", json={"message": "hi"})
    resp = client.post("/api/feedback", json={"message": "hi"})
    body = resp.get_json()
    assert body["error"] == "rate_limited"
    assert 0 < body["retry_after_seconds"] <= 3600


def test_order_creation_is_rate_limited_before_validation(client):
    codes = _post_n(client, "/api/orders", 11, json={})
    assert codes == [400] * 10 + [429]


def test_courier_actions_are_rate_limited(client):
    codes = _post_n(client, "/api/orders/999999/claim", 31, json={"courier_email": "courier@uni.lu"})
    assert codes == [404] * 30 + [429]


def test_page_view_beacons_are_rate_limited_per_event(client):
    assert _post_n(client, "/api/track/home", 61)[-2:] == [200, 429]
    # A separate event has its own budget.
    assert client.post("/api/track/menu").status_code == 200
    assert _count_now(client, "home") == 60


def test_delivery_list_is_never_blocked_but_view_counting_is_capped(client):
    codes = [client.get("/api/delivery/orders").status_code for _ in range(61)]
    assert codes == [200] * 61
    assert _count_now(client, "delivery") == 60


def test_rate_limits_are_per_client_ip(client):
    # nginx appends the real client IP to X-Forwarded-For and ProxyFix
    # trusts that last hop -- so two different clients get their own budget.
    for _ in range(5):
        client.post("/api/feedback", json={"message": "hi"}, headers={"X-Forwarded-For": "10.0.0.1"})
    assert client.post("/api/feedback", json={"message": "hi"}, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 429
    assert client.post("/api/feedback", json={"message": "hi"}, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200


def test_claim_order_unknown_order_404s(client):
    resp = _claim(client, 999999)
    assert resp.status_code == 404


def test_mark_order_delivered(client):
    order_id = _create_basic_order(client)
    resp = client.post(f"/api/orders/{order_id}/mark-delivered")
    assert resp.status_code == 200
    assert resp.get_json()["delivered"] is True
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["delivered_at"] is not None


def test_mark_order_delivered_unknown_order_404s(client):
    resp = client.post("/api/orders/999999/mark-delivered")
    assert resp.status_code == 404


def test_mark_order_not_delivered_undoes_it(client):
    order_id = _create_basic_order(client)
    client.post(f"/api/orders/{order_id}/mark-delivered")
    resp = client.post(f"/api/orders/{order_id}/mark-not-delivered")
    assert resp.status_code == 200
    assert resp.get_json()["delivered"] is False
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["delivered_at"] is None


def test_track_home_records_a_page_view(client):
    resp = client.post("/api/track/home")
    assert resp.status_code == 200
    assert resp.get_json()["recorded"] is True
    page_views = client.application.config["PAGE_VIEW_STORE"]
    now = datetime.datetime.now(TZINFO)
    assert page_views.count_between("home", now - datetime.timedelta(minutes=1), now + datetime.timedelta(minutes=1)) == 1


def test_track_home_records_the_given_source(client):
    client.post("/api/track/home", json={"source": "flyer-a"})
    page_views = client.application.config["PAGE_VIEW_STORE"]
    assert page_views.source_counts("home") == [("flyer-a", 1)]


def test_track_home_with_no_source_groups_as_direct(client):
    client.post("/api/track/home")
    page_views = client.application.config["PAGE_VIEW_STORE"]
    assert page_views.source_counts("home") == [("(direct)", 1)]


def test_track_home_source_is_trimmed_and_capped(client):
    client.post("/api/track/home", json={"source": "  flyer-a  "})
    client.post("/api/track/home", json={"source": "x" * 500})
    page_views = client.application.config["PAGE_VIEW_STORE"]
    counts = dict(page_views.source_counts("home"))
    assert counts["flyer-a"] == 1
    assert "x" * 500 not in counts
    assert any(len(src) <= 60 for src in counts if src.startswith("x"))


def _count_now(client, event):
    page_views = client.application.config["PAGE_VIEW_STORE"]
    now = datetime.datetime.now(TZINFO)
    return page_views.count_between(event, now - datetime.timedelta(minutes=1), now + datetime.timedelta(minutes=1))


def test_menu_fetch_itself_does_not_count_a_view(client):
    # The date picker prefetches every orderable day's menu in the
    # background -- counting here read one real view as ~5.
    client.get("/api/restaurants/altius/menu/2026-09-24")
    assert _count_now(client, "menu") == 0


def test_track_menu_records_a_page_view(client):
    resp = client.post("/api/track/menu")
    assert resp.status_code == 200
    assert _count_now(client, "menu") == 1


def test_track_rejects_events_the_client_does_not_own(client):
    # "delivery" is counted server-side; a client beacon for it would
    # double-count. Unknown events are rejected outright.
    assert client.post("/api/track/delivery").status_code == 404
    assert client.post("/api/track/nonsense").status_code == 404
    assert _count_now(client, "delivery") == 0


def test_delivery_orders_fetch_records_a_page_view(client):
    page_views = client.application.config["PAGE_VIEW_STORE"]
    now = datetime.datetime.now(TZINFO)
    client.get("/api/delivery/orders")
    assert page_views.count_between("delivery", now - datetime.timedelta(minutes=1), now + datetime.timedelta(minutes=1)) == 1


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
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
        )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Admin confirmation workflow (Part 30)
# ---------------------------------------------------------------------------


def _create_basic_order(client, customer_email="student@uni.lu", customer_note=None):
    payload = {"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]}
    if customer_email:
        payload["customer_email"] = customer_email
        # Part 83: customer_email must now be verified (not just well-
        # formed) to place an order -- bypasses the real send-code/
        # verify-code round trip the same way _create_order_without_email
        # bypasses the API's own validation entirely, since this helper's
        # whole point is "just get me an order", not exercising
        # verification itself (see test_order_creation_requires_a_
        # verified_email below for that).
        client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(customer_email)
    if customer_note:
        payload["customer_note"] = customer_note
    with patch("app.send_admin_notification", return_value=(True, None)):
        resp = client.post("/api/orders", json=payload)
    return resp.get_json()["id"]


def _create_order_without_email(client):
    """Simulates a LEGACY order from before customer_email became
    required at checkout -- the only way one can still exist, since the
    API itself now refuses to create one without an email. Writes
    straight to the store, bypassing api_create_order's own validation."""
    store = client.application.config["ORDER_STORE"]
    return store.create_order(
        "UDL-CKB-ALTIUS",
        "UDL-CKB - Altius - Restaurant",
        datetime.date(2026, 9, 24),
        [{"category": "Salades", "name": "Salad bar", "price": 3.5, "quantity": 1}],
    )


def test_create_order_pings_the_admin_via_telegram(client):
    with patch("app.send_admin_notification", return_value=(True, None)) as mock_notify:
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
        )
    assert mock_notify.call_args.kwargs["mark_reviewing_url"] is None


def test_create_order_still_succeeds_when_telegram_notify_fails(client):
    # Best-effort, same as the email confirmation -- a Telegram failure
    # must never turn a successful order into a 500.
    with patch("app.send_admin_notification", return_value=(False, "chat not found")):
        resp = client.post(
            "/api/orders",
            json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu"},
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


# ---------------------------------------------------------------------------
# Coming-soon card click tracking (Part 69)
# ---------------------------------------------------------------------------


def test_coming_soon_click_records_a_known_location(client):
    resp = client.post("/api/coming-soon/click", json={"location": "Food House"})
    assert resp.status_code == 200
    assert resp.get_json()["recorded"] is True


def test_coming_soon_click_rejects_an_unknown_location(client):
    resp = client.post("/api/coming-soon/click", json={"location": "Not A Real Place"})
    assert resp.status_code == 400


def test_coming_soon_click_rejects_missing_location(client):
    resp = client.post("/api/coming-soon/click", json={})
    assert resp.status_code == 400


def test_admin_coming_soon_clicks_requires_token(client):
    resp = client.get("/admin/coming-soon-clicks")
    assert resp.status_code == 404


def test_admin_coming_soon_clicks_shows_counts(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    client.post("/api/coming-soon/click", json={"location": "Food Lab"})
    client.post("/api/coming-soon/click", json={"location": "Food Lab"})
    client.post("/api/coming-soon/click", json={"location": "Food Zone"})
    resp = client.get("/admin/coming-soon-clicks?token=correct-token")
    assert resp.status_code == 200
    assert b"Food Lab" in resp.data
    assert b"Food Zone" in resp.data


def test_admin_sources_requires_token(client):
    resp = client.get("/admin/sources")
    assert resp.status_code == 404


def test_admin_sources_shows_counts_by_source(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    client.post("/api/track/home", json={"source": "flyer-a"})
    client.post("/api/track/home", json={"source": "flyer-a"})
    client.post("/api/track/home", json={"source": "flyer-b"})
    client.post("/api/track/home")
    resp = client.get("/admin/sources?token=correct-token")
    assert resp.status_code == 200
    assert b"flyer-a" in resp.data
    assert b"flyer-b" in resp.data
    assert b"(direct)" in resp.data


def test_feedback_records_a_message(client):
    resp = client.post("/api/feedback", json={"message": "Please add Belval restaurants soon!"})
    assert resp.status_code == 200
    assert resp.get_json()["recorded"] is True


def test_feedback_rejects_empty_message(client):
    resp = client.post("/api/feedback", json={"message": "   "})
    assert resp.status_code == 400


def test_feedback_rejects_an_invalid_contact_email(client):
    resp = client.post("/api/feedback", json={"message": "Hello", "email": "not-an-email"})
    assert resp.status_code == 400


def test_feedback_accepts_an_optional_contact_email(client):
    resp = client.post("/api/feedback", json={"message": "Love the app!", "email": "student@uni.lu"})
    assert resp.status_code == 200


def test_admin_feedback_requires_token(client):
    resp = client.get("/admin/feedback")
    assert resp.status_code == 404


def test_admin_feedback_shows_submitted_messages(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    client.post("/api/feedback", json={"message": "The green box idea is great"})
    resp = client.get("/admin/feedback?token=correct-token")
    assert resp.status_code == 200
    assert b"The green box idea is great" in resp.data


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
    order_id = _create_order_without_email(client)
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


def test_root_includes_open_graph_and_twitter_card_tags(client):
    resp = client.get("/")
    body = resp.data
    assert b'property="og:title"' in body
    assert b'property="og:description"' in body
    assert b'property="og:image"' in body
    assert b'property="og:url"' in body
    assert b'name="twitter:card" content="summary_large_image"' in body
    assert b"/static/og-image.png" in body


def test_og_image_url_uses_https_behind_the_reverse_proxy(client):
    # nginx forwards the real scheme via X-Forwarded-Proto (see the
    # resto-unilu site config) -- ProxyFix must turn that into an
    # https:// _external=True URL, not the plain-http one gunicorn
    # itself sees on the wire.
    resp = client.get("/", headers={"X-Forwarded-Proto": "https"})
    assert b"https://" in resp.data
    assert b'content="http://' not in resp.data


def test_root_localizes_the_open_graph_preview_to_the_lang_param(client):
    # ?lang=fr is the SHARER's language (see static/app.js's
    # syncLangInUrl()), not this visitor's -- the crawler fetching a
    # shared link never runs our JS, so this param is the only signal
    # the server has for which language to render the preview in.
    resp = client.get("/?lang=fr")
    body = resp.data.decode()
    assert 'lang="fr"' in body
    assert "Commandez votre déjeuner" in body
    assert "Order lunch from University" not in body


def test_root_falls_back_to_english_for_an_unknown_lang_param(client):
    resp = client.get("/?lang=klingon")
    body = resp.data.decode()
    assert 'lang="en"' in body
    assert "Order lunch from University" in body


def test_favicon_ico_redirects_to_the_real_png(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code in (301, 302)
    assert resp.headers["Location"].endswith("/static/favicon-32.png")


def test_admin_page_renders(client):
    resp = client.get("/admin/orderability")
    assert resp.status_code == 200
    assert b"Orderability debug" in resp.data
    assert b"AVAILABLE" in resp.data
