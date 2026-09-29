import datetime
import io
from unittest.mock import patch

import pytest
from PIL import Image

from app import create_app
from orderability_engine.cache import OrderabilityCache
from orderability_engine.coming_soon_clicks import ComingSoonClickStore
from orderability_engine.daily_report import DailyReportStore
from orderability_engine.delivery_subscribers import DeliverySubscriberStore
from orderability_engine.dish_photos import DishPhotoStore
from orderability_engine.pending_dish_photos import PendingDishPhotoStore
from orderability_engine.rewards import RewardStore
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
    # Part 88: "courier@uni.lu" is this whole file's canonical placeholder
    # courier email, same reasoning as student@uni.lu above.
    verified_email_store.mark_verified("courier@uni.lu")
    dish_photo_store = DishPhotoStore(tmp_path / "orders.db")
    pending_dish_photo_store = PendingDishPhotoStore(tmp_path / "orders.db")
    reward_store = RewardStore(tmp_path / "orders.db")
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
        og_cache_dir=tmp_path / "og_cache",
        pending_dish_photo_store=pending_dish_photo_store,
        reward_store=reward_store,
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
    assert body["max_quantity"] == 2
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

def _image_bytes(color=(0, 0, 0), size=(8, 8), fmt="PNG", **save_kwargs):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format=fmt, **save_kwargs)
    return out.getvalue()


# A real, decodable PNG -- uploads are now re-encoded through Pillow (see
# _sanitize_dish_photo in app.py), so a bare signature is no longer enough.
# Reused across every "valid upload" test below via a helper rather than
# inlined, so unsupported-type/too-large tests read as obviously-deliberate
# deviations from it.
_PNG_BYTES = _image_bytes()


def test_dish_photos_starts_empty_for_a_restaurant(client):
    resp = client.get("/api/restaurants/altius/dish-photos")
    assert resp.status_code == 200
    assert resp.get_json() == {}


def test_dish_photos_unknown_restaurant_is_404(client):
    assert client.get("/api/restaurants/does-not-exist/dish-photos").status_code == 404


def _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=_PNG_BYTES, filename="dish.png", email="student@uni.lu"):
    return client.post(
        "/api/restaurants/altius/dish-photos",
        data={"email": email, "category": category, "name": name, "photo": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def test_upload_dish_photo_is_pending_not_immediately_listed(client):
    resp = _upload_dish_photo(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "pending"
    assert isinstance(body["id"], int)
    assert body["photo_path"].startswith("/static/dish_photos/") and body["photo_path"].endswith(".jpg")

    # Not live -- api_dish_photos (what every OTHER student's card reads)
    # must stay empty until an admin actually approves it.
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}


def test_pending_dish_photo_is_served_back_from_static(client):
    resp = _upload_dish_photo(client)
    photo_path = resp.get_json()["photo_path"]
    served = client.get(photo_path)
    assert served.status_code == 200
    assert served.data.startswith(b"\xff\xd8")  # re-encoded to JPEG, never the raw upload


def test_upload_dish_photo_missing_category_or_name_is_400(client):
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"email": "student@uni.lu", "name": "Salad'bar", "photo": (io.BytesIO(_PNG_BYTES), "dish.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_dish_photo_missing_file_is_400(client):
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"email": "student@uni.lu", "category": "Végétarien", "name": "Salad'bar"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_dish_photo_rejects_a_non_image_file(client):
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={
            "email": "student@uni.lu",
            "category": "Végétarien",
            "name": "Salad'bar",
            "photo": (io.BytesIO(b"<script>alert(1)</script>"), "evil.svg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unsupported_type"


def test_upload_dish_photo_rejects_an_oversized_file(client):
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * (8 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"email": "student@uni.lu", "category": "Végétarien", "name": "Salad'bar", "photo": (io.BytesIO(huge), "big.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "too_large"


def test_upload_dish_photo_rejects_a_valid_signature_with_garbage_after_it(client):
    resp = _upload_dish_photo(client, data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unsupported_type"


def _jpeg_with_exif(size=(8, 4), orientation=None):
    exif = Image.Exif()
    exif[0x010F] = "SnoopPhone"  # Make
    exif[0x8825] = {1: "N", 2: (49.0, 30.0, 17.0), 3: "E", 4: (5.0, 56.0, 51.0)}  # GPSInfo
    if orientation:
        exif[0x0112] = orientation
    return _image_bytes((200, 30, 30), size=size, fmt="JPEG", exif=exif)


def test_uploaded_dish_photo_has_exif_and_gps_stripped(client):
    original = _jpeg_with_exif()
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(0x8825)  # sanity: GPS really is in there
    photo_path = _upload_dish_photo(client, data=original, filename="dish.jpg").get_json()["photo_path"]
    served = client.get(photo_path).data
    assert b"SnoopPhone" not in served
    assert len(Image.open(io.BytesIO(served)).getexif()) == 0


def test_uploaded_dish_photo_bakes_in_exif_orientation(client):
    # Orientation 6 = "rotate 90° clockwise to display": an 8x4 sensor
    # image is really a 4x8 portrait shot, and must stay that way once
    # the tag that said so is gone.
    photo_path = _upload_dish_photo(client, data=_jpeg_with_exif(size=(8, 4), orientation=6), filename="dish.jpg").get_json()["photo_path"]
    assert Image.open(io.BytesIO(client.get(photo_path).data)).size == (4, 8)


def test_uploaded_dish_photo_is_downscaled(client):
    big = _image_bytes(size=(3200, 1600))
    photo_path = _upload_dish_photo(client, data=big).get_json()["photo_path"]
    assert Image.open(io.BytesIO(client.get(photo_path).data)).size == (1600, 800)


def test_admin_replacement_photo_has_exif_stripped(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client).get_json()
    client.post(
        f"/admin/dish-photos/{upload['id']}/replace?token=correct-token",
        data={"photo": (io.BytesIO(_jpeg_with_exif()), "admin-choice.jpg")},
        content_type="multipart/form-data",
    )
    new_photo_path = client.get("/api/restaurants/altius/dish-photos").get_json()["Végétarien"]["Salad'bar"]
    assert b"SnoopPhone" not in client.get(new_photo_path).data


def test_upload_dish_photo_unknown_restaurant_is_404(client):
    resp = client.post(
        "/api/restaurants/does-not-exist/dish-photos",
        data={"email": "student@uni.lu", "category": "Végétarien", "name": "Salad'bar", "photo": (io.BytesIO(_PNG_BYTES), "dish.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 404


def test_upload_dish_photo_is_scoped_per_restaurant(client):
    _upload_dish_photo(client)
    # brasserie-johns -- the other real restaurant in restaurants.yaml
    # (see UDL-CKB-BRASSERIE-JOHNS), never uploaded to in this test.
    assert client.get("/api/restaurants/brasserie-johns/dish-photos").get_json() == {}


# ---------------------------------------------------------------------------
# API: dish photo upload requires a verified University email (Part 85)
# ---------------------------------------------------------------------------


def test_upload_dish_photo_missing_email_is_400(client):
    resp = client.post(
        "/api/restaurants/altius/dish-photos",
        data={"category": "Végétarien", "name": "Salad'bar", "photo": (io.BytesIO(_PNG_BYTES), "dish.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_dish_photo_rejects_a_non_university_email(client):
    resp = _upload_dish_photo(client, email="student@gmail.com")
    assert resp.status_code == 400


def test_upload_dish_photo_rejects_an_unverified_university_email(client):
    # A real uni.lu address, but this client never verified it (only
    # "student@uni.lu" is pre-verified in the test fixture -- see
    # _make_client()).
    resp = _upload_dish_photo(client, email="someone-else@uni.lu")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "email_not_verified"


def test_upload_dish_photo_succeeds_with_a_verified_student_uni_lu_email(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("verified-student@student.uni.lu")
    resp = _upload_dish_photo(client, email="verified-student@student.uni.lu")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pending"


def test_upload_dish_photo_email_verified_via_a_different_flow_still_counts(client):
    # Part 83's whole point: VerifiedEmailStore is shared across checkout/
    # courier/University-email verification -- proving a uni.lu address
    # via ANY of those flows must be enough here too, not just Profile's
    # own University Email field specifically.
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("via-checkout@uni.lu")
    resp = _upload_dish_photo(client, email="via-checkout@uni.lu")
    assert resp.status_code == 200


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
    resp = client.post(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
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
    client.post(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
    resp = client.post(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
    assert resp.status_code == 200
    assert b"isn&#39;t valid anymore" in resp.data or b"isn't valid anymore" in resp.data


def test_admin_reject_dish_photo_discards_it(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client, category="Végétarien", name="Salad'bar").get_json()
    resp = client.post(f"/admin/dish-photos/{upload['id']}/reject?token=correct-token")
    assert resp.status_code == 200
    assert b"rejected" in resp.data.lower()

    # Discarded, not published -- and the file itself is gone too.
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}
    assert client.get(upload["photo_path"]).status_code == 404


def test_admin_reject_dish_photo_requires_token(client):
    upload = _upload_dish_photo(client).get_json()
    assert client.get(f"/admin/dish-photos/{upload['id']}/reject").status_code == 404
    assert client.get(upload["photo_path"]).status_code == 200  # file untouched


def test_admin_replace_dish_photo_publishes_the_admins_own_upload(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client, category="Végétarien", name="Salad'bar").get_json()
    other_png = _image_bytes((0x11,) * 3)
    resp = client.post(
        f"/admin/dish-photos/{upload['id']}/replace?token=correct-token",
        data={"photo": (io.BytesIO(other_png), "admin-choice.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"published" in resp.data.lower()

    listed = client.get("/api/restaurants/altius/dish-photos").get_json()
    new_photo_path = listed["Végétarien"]["Salad'bar"]
    assert new_photo_path != upload["photo_path"]
    served = Image.open(io.BytesIO(client.get(new_photo_path).data))
    assert served.format == "JPEG"
    assert all(abs(c - 0x11) <= 4 for c in served.getpixel((0, 0)))  # the admin's pixels, not the student's
    # The student's original submission is discarded, not published.
    assert client.get(upload["photo_path"]).status_code == 404
    # Consumed -- no longer sitting in the pending queue.
    assert client.get("/admin/dish-photos?token=correct-token").data.count(b"Approve") == 0


def test_admin_replace_dish_photo_requires_token(client):
    upload = _upload_dish_photo(client).get_json()
    other_png = _image_bytes((0x11,) * 3)
    resp = client.post(
        f"/admin/dish-photos/{upload['id']}/replace",
        data={"photo": (io.BytesIO(other_png), "admin-choice.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 404
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}


def test_admin_replace_dish_photo_rejects_a_non_image_file(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client).get_json()
    resp = client.post(
        f"/admin/dish-photos/{upload['id']}/replace?token=correct-token",
        data={"photo": (io.BytesIO(b"<script>alert(1)</script>"), "evil.svg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"Unsupported file type" in resp.data
    # Untouched -- still pending, original submission still there.
    assert client.get("/admin/dish-photos?token=correct-token").data.count(b"Approve") == 1


def test_admin_replace_dish_photo_unknown_id_is_friendly_not_404(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    other_png = _image_bytes((0x11,) * 3)
    resp = client.post(
        "/admin/dish-photos/999999/replace?token=correct-token",
        data={"photo": (io.BytesIO(other_png), "admin-choice.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"already approved or rejected" in resp.data


# ---------------------------------------------------------------------------
# Storage cleanup: a dish never keeps more than one photo on disk (Part 86)
# ---------------------------------------------------------------------------


def test_approving_a_resubmission_deletes_the_dishs_previous_live_photo(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    first = _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=_PNG_BYTES).get_json()
    client.post(f"/admin/dish-photos/{first['id']}/approve?token=correct-token")

    other_png = _image_bytes((0x11,) * 3)
    second = _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=other_png).get_json()
    client.post(f"/admin/dish-photos/{second['id']}/approve?token=correct-token")

    listed = client.get("/api/restaurants/altius/dish-photos").get_json()
    assert listed["Végétarien"]["Salad'bar"] == second["photo_path"]
    # The FIRST approved photo's file is gone -- nothing points at it anymore.
    assert client.get(first["photo_path"]).status_code == 404
    assert client.get(second["photo_path"]).status_code == 200


def test_replacing_deletes_the_dishs_previous_live_photo(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    first = _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=_PNG_BYTES).get_json()
    client.post(f"/admin/dish-photos/{first['id']}/approve?token=correct-token")

    pending = _upload_dish_photo(client, category="Végétarien", name="Salad'bar").get_json()
    other_png = _image_bytes((0x22,) * 3)
    client.post(
        f"/admin/dish-photos/{pending['id']}/replace?token=correct-token",
        data={"photo": (io.BytesIO(other_png), "admin-choice.png")},
        content_type="multipart/form-data",
    )

    assert client.get(first["photo_path"]).status_code == 404
    assert client.get(pending["photo_path"]).status_code == 404  # the discarded submission's own file too


def test_approving_discards_other_pending_submissions_for_the_same_dish(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    keeper = _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=_PNG_BYTES).get_json()
    other_png = _image_bytes((0x33,) * 3)
    other = _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=other_png).get_json()

    client.post(f"/admin/dish-photos/{keeper['id']}/approve?token=correct-token")

    # The other, never explicitly decided, submission is discarded too --
    # both its pending row and its file.
    review_page = client.get(f"/admin/dish-photos/{other['id']}?token=correct-token")
    assert b"already approved or rejected" in review_page.data
    assert client.get(other["photo_path"]).status_code == 404
    # Unrelated to a different dish's own still-pending submission.
    assert client.get("/admin/dish-photos?token=correct-token").data.count(b"Approve") == 0


def test_rejecting_does_not_touch_a_different_pending_submission_for_the_same_dish(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    first = _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=_PNG_BYTES).get_json()
    other_png = _image_bytes((0x44,) * 3)
    second = _upload_dish_photo(client, category="Végétarien", name="Salad'bar", data=other_png).get_json()

    client.post(f"/admin/dish-photos/{first['id']}/reject?token=correct-token")

    # Rejecting one submission is NOT a decision about the dish itself --
    # the other one is still legitimately awaiting its own review.
    assert client.get(second["photo_path"]).status_code == 200
    assert client.get("/admin/dish-photos?token=correct-token").data.count(b"Approve") == 1


# ---------------------------------------------------------------------------
# API: Luni reward points (Part 87)
# ---------------------------------------------------------------------------


def test_rewards_is_zero_for_an_email_never_awarded_anything(client):
    resp = client.get("/api/rewards?email=student@uni.lu")
    assert resp.status_code == 200
    assert resp.get_json() == {"points": 0}


def test_rewards_reflects_a_real_balance(client):
    client.application.config["REWARD_STORE"].add_points("student@uni.lu", 25)
    resp = client.get("/api/rewards?email=student@uni.lu")
    assert resp.get_json() == {"points": 25}


def test_rewards_missing_email_is_400(client):
    assert client.get("/api/rewards").status_code == 400


def test_rewards_rejects_a_non_university_email(client):
    assert client.get("/api/rewards?email=student@gmail.com").status_code == 400


def test_rewards_are_scoped_per_email(client):
    client.application.config["REWARD_STORE"].add_points("a@uni.lu", 10)
    assert client.get("/api/rewards?email=b@uni.lu").get_json() == {"points": 0}


# ---------------------------------------------------------------------------
# API: earning Luni (Part 90)
# ---------------------------------------------------------------------------


def test_verifying_university_email_awards_3_luni(client):
    store = client.application.config["EMAIL_VERIFICATION_STORE"]
    store.issue("newstudent@uni.lu", "123456")
    resp = client.post("/api/email/verify-code", json={"email": "newstudent@uni.lu", "code": "123456"})
    assert resp.get_json()["verified"] is True
    assert client.get("/api/rewards?email=newstudent@uni.lu").get_json() == {"points": 3}


def test_reverifying_the_same_university_email_does_not_repay(client):
    store = client.application.config["EMAIL_VERIFICATION_STORE"]
    store.issue("newstudent@uni.lu", "111111")
    client.post("/api/email/verify-code", json={"email": "newstudent@uni.lu", "code": "111111"})
    store.issue("newstudent@uni.lu", "222222")
    client.post("/api/email/verify-code", json={"email": "newstudent@uni.lu", "code": "222222"})
    assert client.get("/api/rewards?email=newstudent@uni.lu").get_json() == {"points": 3}


def test_verifying_via_checkout_flow_does_not_award_the_registration_bonus(client):
    # Part 90's "registration" bonus is specifically Profile's own
    # University Email flow (/api/email/verify-code) -- verifying the
    # SAME shared VerifiedEmailStore fact via checkout's own flow
    # (Part 83) still unlocks ordering, but isn't "registering".
    store = client.application.config["CHECKOUT_VERIFICATION_STORE"]
    store.issue("checkout-only@uni.lu", "123456")
    client.post("/api/orders/email/verify-code", json={"email": "checkout-only@uni.lu", "code": "123456"})
    assert client.get("/api/rewards?email=checkout-only@uni.lu").get_json() == {"points": 0}


def _claim_reward(client, action, value=None, email="student@uni.lu"):
    body = {"email": email, "action": action}
    if value is not None:
        body["value"] = value
    return client.post("/api/rewards/claim", json=body)


def test_rewards_claim_awards_for_communication_email(client):
    body = _claim_reward(client, "communication_email_added", "me@gmail.com").get_json()
    assert body["awarded"] is True
    assert body["points"] == 1


def test_rewards_claim_for_communication_email_only_pays_once(client):
    _claim_reward(client, "communication_email_added", "me@gmail.com")
    resp = _claim_reward(client, "communication_email_added", "other@gmail.com")
    assert resp.get_json() == {"awarded": False, "reason": "already_awarded", "points": 1}


def test_rewards_claim_awards_for_phone_number(client):
    resp = _claim_reward(client, "phone_number_added", "+352 621 123 456")
    assert resp.get_json() == {"awarded": True, "reason": None, "points": 1}


def test_rewards_claim_communication_email_and_phone_both_pay(client):
    _claim_reward(client, "communication_email_added", "me@gmail.com")
    _claim_reward(client, "phone_number_added", "621123456")
    assert client.get("/api/rewards?email=student@uni.lu").get_json() == {"points": 2}


def test_rewards_claim_needs_the_value_it_is_about(client):
    assert _claim_reward(client, "communication_email_added").status_code == 400
    assert _claim_reward(client, "phone_number_added").status_code == 400
    assert client.get("/api/rewards?email=student@uni.lu").get_json() == {"points": 0}


def test_rewards_claim_rejects_garbage_values(client):
    assert _claim_reward(client, "communication_email_added", "not-an-email").status_code == 400
    assert _claim_reward(client, "phone_number_added", "abc").status_code == 400
    assert _claim_reward(client, "phone_number_added", "123").status_code == 400
    assert _claim_reward(client, "phone_number_added", ["621123456"]).status_code == 400


def test_a_university_address_is_not_a_communication_email(client):
    assert _claim_reward(client, "communication_email_added", "someone@uni.lu").status_code == 400
    assert _claim_reward(client, "communication_email_added", "someone@student.uni.lu").status_code == 400


def _second_student(client, email="second@uni.lu"):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(email)
    return email


def test_one_phone_number_pays_only_one_account(client):
    _claim_reward(client, "phone_number_added", "+352 621 123 456")
    other = _second_student(client)
    resp = _claim_reward(client, "phone_number_added", "621 123 456", email=other).get_json()
    assert resp == {"awarded": False, "reason": "value_already_used", "points": 0}


@pytest.mark.parametrize("variant", ["+352621123456", "00352 621 123 456", "621-123-456", "(621) 123456"])
def test_phone_formats_are_recognised_as_the_same_number(client, variant):
    _claim_reward(client, "phone_number_added", "+352 621 123 456")
    other = _second_student(client)
    assert _claim_reward(client, "phone_number_added", variant, email=other).get_json()["awarded"] is False


@pytest.mark.parametrize("variant", ["Me@Gmail.com", "me+shop@gmail.com", "m.e@gmail.com", "me@googlemail.com"])
def test_one_communication_email_pays_only_one_account(client, variant):
    _claim_reward(client, "communication_email_added", "me@gmail.com")
    other = _second_student(client)
    resp = _claim_reward(client, "communication_email_added", variant, email=other).get_json()
    assert resp["awarded"] is False and resp["reason"] == "value_already_used"


def test_a_refused_duplicate_does_not_burn_the_action_for_a_real_value(client):
    _claim_reward(client, "phone_number_added", "621123456")
    other = _second_student(client)
    _claim_reward(client, "phone_number_added", "621123456", email=other)
    # Their own, different number still pays.
    assert _claim_reward(client, "phone_number_added", "691999888", email=other).get_json()["awarded"] is True


def test_the_university_email_bonus_can_be_claimed_once_by_a_verified_address(client):
    assert _claim_reward(client, "university_email_verified").get_json()["awarded"] is True
    assert _claim_reward(client, "university_email_verified").get_json()["reason"] == "already_awarded"
    assert client.get("/api/rewards?email=student@uni.lu").get_json() == {"points": 3}


def test_the_university_email_bonus_needs_a_verified_address(client):
    assert _claim_reward(client, "university_email_verified", email="stranger@uni.lu").status_code == 403


# One mailbox, many addresses: plus-tags and uni.lu / student.uni.lu are the
# same person and must not earn (or order) twice.


def test_plus_tagged_and_student_addresses_are_one_reward_identity(client):
    store = client.application.config["EMAIL_VERIFICATION_STORE"]
    for email, code in (("dupe@uni.lu", "111111"), ("dupe+2@uni.lu", "222222"), ("dupe@student.uni.lu", "333333")):
        store.issue(email, code)
        client.post("/api/email/verify-code", json={"email": email, "code": code})
    assert client.get("/api/rewards?email=dupe@uni.lu").get_json() == {"points": 3}
    assert client.get("/api/rewards?email=DUPE%2B9@student.uni.lu").get_json() == {"points": 3}


def test_plus_tags_cannot_claim_the_contact_bonuses_again(client):
    for email in ("dupe@uni.lu", "dupe+2@uni.lu", "dupe@student.uni.lu"):
        client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(email)
    assert _claim_reward(client, "phone_number_added", "621111111", email="dupe@uni.lu").get_json()["awarded"] is True
    resp = _claim_reward(client, "phone_number_added", "622222222", email="dupe+2@uni.lu").get_json()
    assert resp["awarded"] is False and resp["reason"] == "already_awarded"


def test_the_daily_order_limit_sees_through_plus_tags_and_the_student_domain(client):
    payload = _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}])
    for email in ("student@uni.lu", "student+1@uni.lu"):
        assert _post_order(client, dict(payload, reward_email=email)).status_code == 201
    resp = _post_order(client, dict(payload, reward_email="student@student.uni.lu"))
    assert resp.status_code == 409 and resp.get_json()["error"] == "daily_order_limit"


def test_the_days_limit_sees_through_plus_tags(client):
    _seed_order_on(client, "2026-09-30")
    _seed_order_on(client, "2026-10-01")
    resp = _post_order(client, dict(_order_payload([{"id": SALAD_BAR_ID, "quantity": 1}]), reward_email="student+x@uni.lu"))
    assert resp.status_code == 409 and resp.get_json()["error"] == "order_days_limit"


def test_a_courier_cannot_deliver_their_own_order_via_the_other_domain(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("courier@student.uni.lu")
    order_id = _create_basic_order(client, customer_email="courier@uni.lu")
    _hand_off(client, order_id, courier_email="courier@student.uni.lu")
    _mark_delivered(client, order_id, courier_email="courier@student.uni.lu")
    assert _points(client, "courier@uni.lu") == 0


def test_rewards_claim_rejects_an_unknown_action(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("student@uni.lu")
    resp = client.post("/api/rewards/claim", json={"email": "student@uni.lu", "action": "free_points_please"})
    assert resp.status_code == 400


def test_rewards_claim_rejects_an_unverified_email(client):
    resp = client.post("/api/rewards/claim", json={"email": "someone-else@uni.lu", "action": "phone_number_added"})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "email_not_verified"


def test_rewards_claim_rejects_a_non_university_email(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("student@gmail.com")
    resp = client.post("/api/rewards/claim", json={"email": "student@gmail.com", "action": "phone_number_added"})
    assert resp.status_code == 400


def _hand_off(client, order_id, courier_email="courier@uni.lu"):
    """Claim + pick up, with every outbound notification stubbed -- the
    two steps a real courier takes before mark-delivered can pay Luni."""
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_accepted", return_value=(True, None)), patch(
        "app.send_order_out_for_delivery", return_value=(True, None)
    ):
        _claim(client, order_id, courier_email=courier_email)
        _pickup(client, order_id, courier_email=courier_email)


def _points(client, email):
    return client.get(f"/api/rewards?email={email}").get_json()["points"]


def test_placing_an_order_alone_awards_nothing(client):
    # Orders are free and take one request -- paying on creation made
    # Luni farmable. The "order" reward pays out on delivery instead.
    _create_basic_order(client, customer_email="student@uni.lu")
    assert _points(client, "student@uni.lu") == 0


def test_a_real_delivery_awards_1_luni_to_customer_and_courier(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    assert _mark_delivered(client, order_id).get_json() == {"delivered": True}
    assert _points(client, "student@uni.lu") == 1
    assert _points(client, "courier@uni.lu") == 1


def test_two_delivered_orders_award_luni_for_each(client):
    for _ in range(2):
        order_id = _create_basic_order(client, customer_email="student@uni.lu")
        _hand_off(client, order_id)
        _mark_delivered(client, order_id)
    assert _points(client, "student@uni.lu") == 2
    assert _points(client, "courier@uni.lu") == 2


def test_marking_an_unclaimed_order_delivered_awards_nothing(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    assert _mark_delivered(client, order_id).status_code == 200
    assert _points(client, "student@uni.lu") == 0
    assert _points(client, "courier@uni.lu") == 0


def test_delivery_luni_goes_to_the_claiming_courier_not_the_caller(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("other@uni.lu")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id, courier_email="courier@uni.lu")
    _mark_delivered(client, order_id, courier_email="other@uni.lu")
    assert _points(client, "courier@uni.lu") == 1
    assert _points(client, "other@uni.lu") == 0


def test_delivering_your_own_order_awards_nothing(client):
    order_id = _create_basic_order(client, customer_email="courier@uni.lu")
    _hand_off(client, order_id, courier_email="COURIER@uni.lu")
    _mark_delivered(client, order_id)
    assert _points(client, "courier@uni.lu") == 0
    assert _points(client, "COURIER@uni.lu") == 0


def test_mark_delivered_on_a_cancelled_order_is_409(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    store = client.application.config["ORDER_STORE"]
    store.cancel_order(order_id, store.set_real_price(order_id, 6.70))
    resp = _mark_delivered(client, order_id)
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "not_deliverable"
    assert _points(client, "courier@uni.lu") == 0


def test_mark_delivered_on_a_missing_order_is_404(client):
    assert _mark_delivered(client, 999999).status_code == 404


def test_toggling_delivered_and_back_does_not_repay(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    _mark_delivered(client, order_id)
    _mark_not_delivered(client, order_id)
    _mark_delivered(client, order_id)
    assert _points(client, "courier@uni.lu") == 1
    assert _points(client, "student@uni.lu") == 1


def test_approving_a_dish_photo_awards_1_luni_to_the_uploader(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client, email="student@uni.lu").get_json()
    client.post(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
    assert client.get("/api/rewards?email=student@uni.lu").get_json()["points"] == 1


def test_replacing_a_dish_photo_still_awards_the_original_uploader(client, monkeypatch):
    # Part 90: the admin's own replacement photo goes live, but the
    # Luni credit is still the ORIGINAL submitter's -- their submission
    # is what prompted a real photo to end up on this dish either way.
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client, email="student@uni.lu").get_json()
    other_png = _image_bytes((0x55,) * 3)
    client.post(
        f"/admin/dish-photos/{upload['id']}/replace?token=correct-token",
        data={"photo": (io.BytesIO(other_png), "admin-choice.png")},
        content_type="multipart/form-data",
    )
    assert client.get("/api/rewards?email=student@uni.lu").get_json()["points"] == 1


def test_rejecting_a_dish_photo_awards_nothing(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client, email="student@uni.lu").get_json()
    client.post(f"/admin/dish-photos/{upload['id']}/reject?token=correct-token")
    assert client.get("/api/rewards?email=student@uni.lu").get_json()["points"] == 0


def test_approving_two_different_dish_photos_from_the_same_uploader_pays_twice(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    first = _upload_dish_photo(client, email="student@uni.lu", name="Salad'bar").get_json()
    second = _upload_dish_photo(client, email="student@uni.lu", name="Buddha bowl").get_json()
    client.post(f"/admin/dish-photos/{first['id']}/approve?token=correct-token")
    client.post(f"/admin/dish-photos/{second['id']}/approve?token=correct-token")
    assert client.get("/api/rewards?email=student@uni.lu").get_json()["points"] == 2


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
            "reward_email": _uni_email_for("student@uni.lu"),
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
        json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
    )
    body = resp.get_json()
    assert body["items"][0]["price"] is None


def test_create_order_with_uni_lu_email_sends_confirmation(client):
    with patch("app.send_order_confirmation", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/api/orders",
            json={
                "delivery_location": "Building A — Room 1.01",
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@uni.lu",
                "reward_email": _uni_email_for("student@uni.lu"),
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
                "delivery_location": "Building A — Room 1.01",
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@student.uni.lu",
                "reward_email": _uni_email_for("student@student.uni.lu"),
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
                "delivery_location": "Building A — Room 1.01",
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@gmail.com",
                "reward_email": _uni_email_for("student@gmail.com"),
            },
        )
    assert resp.status_code == 201
    mock_send.assert_called_once()
    assert mock_send.call_args[0][0] == "student@gmail.com"


def test_create_order_with_malformed_email_is_400(client):
    resp = client.post(
        "/api/orders",
        json={
            "delivery_location": "Building A — Room 1.01",
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_email": "not-an-email@uni.lu@uni.lu",
            "reward_email": _uni_email_for("not-an-email@uni.lu@uni.lu"),
        },
    )
    assert resp.status_code == 400


def test_create_order_persists_customer_note(client):
    resp = client.post(
        "/api/orders",
        json={
            "delivery_location": "Building A — Room 1.01",
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_note": "no onion, please",
            "customer_email": "student@uni.lu",
            "reward_email": _uni_email_for("student@uni.lu"),
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
            "delivery_location": "Building A — Room 1.01",
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_note": "x" * 201,
            "customer_email": "student@uni.lu",
            "reward_email": "student@uni.lu",
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]},
        )
    assert resp.status_code == 400
    mock_send.assert_not_called()


def test_create_order_still_succeeds_even_when_sending_the_email_fails(client):
    # A flaky mail server must never turn a successful order into a 500.
    with patch("app.send_order_confirmation", return_value=(False, "connection refused")):
        resp = client.post(
            "/api/orders",
            json={
                "delivery_location": "Building A — Room 1.01",
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@uni.lu",
                "reward_email": _uni_email_for("student@uni.lu"),
            },
        )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["email_sent"] is False
    assert body["email_error"] == "connection refused"


def test_create_order_for_unavailable_date_is_409(client):
    resp = client.post(
        "/api/orders",
        json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-26", "items": [{"id": 0, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},  # no_menu
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
            json={
                "delivery_location": "Building A — Room 1.01",
                "restaurant": "altius",
                "date": "2026-09-24",
                "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
                "customer_email": "student@uni.lu",
                "reward_email": _uni_email_for("student@uni.lu"),
            },
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
                json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
            )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "early_cutoff_passed"


def test_create_order_allows_early_cutoff_item_before_0800(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    before_early_cutoff = datetime.datetime(2026, 9, 24, 7, 0, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=before_early_cutoff) as early_client:
        with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
            resp = early_client.post(
                "/api/orders",
                json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
            )
    assert resp.status_code == 201


def test_quote_rejects_early_cutoff_item_once_0800_has_passed(tmp_path, altius_html, altius_closed_week_html, fixture_today):
    after_early_cutoff = datetime.datetime(2026, 9, 24, 9, 0, tzinfo=TZINFO)
    with _make_client(tmp_path, altius_html, altius_closed_week_html, fixture_today, now=after_early_cutoff) as late_client:
        with patch("orderability_engine.menu_service.requires_early_order", return_value=True):
            resp = late_client.post(
                "/api/orders/quote",
                json={"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
            )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "early_cutoff_passed"


def test_create_order_without_items_is_400(client):
    resp = client.post("/api/orders", json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": []})
    assert resp.status_code == 400


def test_create_order_without_delivery_location_is_400(client):
    # Part 89: Building/Delivery location used to be labelled "(optional)"
    # but were never actually enforced -- an ambiguous/missing location is
    # exactly what left couriers stuck (see api_create_order's own
    # docstring comment).
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("student@uni.lu")
    resp = client.post(
        "/api/orders",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_email": "student@uni.lu",
            "reward_email": _uni_email_for("student@uni.lu"),
        },
    )
    assert resp.status_code == 400


def test_create_order_with_blank_delivery_location_is_400(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("student@uni.lu")
    resp = client.post(
        "/api/orders",
        json={
            "restaurant": "altius",
            "date": "2026-09-24",
            "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
            "customer_email": "student@uni.lu",
            "reward_email": _uni_email_for("student@uni.lu"),
            "delivery_location": "   ",
        },
    )
    assert resp.status_code == 400


def test_create_order_with_invalid_item_id_is_400(client):
    resp = client.post(
        "/api/orders",
        json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": 999999, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
    )
    assert resp.status_code == 400


def test_get_order_by_id_returns_the_confirmed_order(client):
    create_resp = client.post(
        "/api/orders",
        json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": BRETZEL_ID, "quantity": 2}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
    )
    order_id = create_resp.get_json()["id"]

    resp = client.get(f"/api/orders/{order_id}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == order_id
    assert body["restaurant_code"] == "UDL-CKB-ALTIUS"
    assert body["items"][0]["quantity"] == 2


def test_get_order_by_id_never_exposes_contact_details(client):
    # Unauthenticated + sequential ids: anyone can walk /api/orders/1..N,
    # so no customer or courier contact detail may ever come back here.
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim(client, order_id, courier_email="courier@uni.lu")
    body = client.get(f"/api/orders/{order_id}").get_json()
    for field in ("customer_email", "customer_phone", "courier_email", "courier_lang"):
        assert field not in body


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


# Part 88: every courier action below needs a verified University email --
# "courier@uni.lu" is this whole file's canonical placeholder courier
# address (pre-verified once in _make_client(), same reasoning as
# "student@uni.lu" for customer_email -- see that fixture's own comment).
def _pickup(client, order_id, courier_email="courier@uni.lu"):
    return client.post(f"/api/orders/{order_id}/picked-up", json={"courier_email": courier_email})


def _unclaim(client, order_id, courier_email="courier@uni.lu"):
    return client.post(f"/api/orders/{order_id}/unclaim", json={"courier_email": courier_email})


def _mark_delivered(client, order_id, courier_email="courier@uni.lu"):
    return client.post(f"/api/orders/{order_id}/mark-delivered", json={"courier_email": courier_email})


def _mark_not_delivered(client, order_id, courier_email="courier@uni.lu"):
    return client.post(f"/api/orders/{order_id}/mark-not-delivered", json={"courier_email": courier_email})


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


def test_claim_order_rejects_a_non_university_courier_email(client):
    # Part 88: well-formed, but not @uni.lu/@student.uni.lu -- the OLD
    # (pre-Part-88) check here was just _is_valid_email_format, which
    # would have allowed this.
    order_id = _create_basic_order(client)
    resp = _claim(client, order_id, courier_email="courier@gmail.com")
    assert resp.status_code == 400


def test_claim_order_rejects_an_unverified_university_courier_email(client):
    # A real uni.lu address, but never verified (only "courier@uni.lu" is
    # pre-verified in this file's fixture -- see _make_client()).
    order_id = _create_basic_order(client)
    resp = _claim(client, order_id, courier_email="someone-else@uni.lu")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "email_not_verified"


@pytest.mark.parametrize("action", ["picked-up", "unclaim", "mark-delivered", "mark-not-delivered"])
def test_courier_actions_require_courier_email(client, action):
    order_id = _create_basic_order(client)
    resp = client.post(f"/api/orders/{order_id}/{action}", json={})
    assert resp.status_code == 400


@pytest.mark.parametrize("action", ["picked-up", "unclaim", "mark-delivered", "mark-not-delivered"])
def test_courier_actions_reject_an_unverified_courier_email(client, action):
    order_id = _create_basic_order(client)
    resp = client.post(f"/api/orders/{order_id}/{action}", json={"courier_email": "someone-else@uni.lu"})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "email_not_verified"


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
    _mark_delivered(client, order_id)
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
        resp = _unclaim(client, order_id)
    assert resp.status_code == 200
    mock_released.assert_called_once()
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["claimed_at"] is None


def test_unclaim_an_unclaimed_order_is_a_409_without_pinging(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_released_notification") as mock_released:
        resp = _unclaim(client, order_id)
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
    _pickup(client, order_id)
    with patch("app.send_order_released_notification") as mock_released:
        resp = _unclaim(client, order_id)
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
        _unclaim(client, order_id)
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
        resp = _pickup(client, order_id)
    assert resp.status_code == 200
    assert resp.get_json() == {"picked_up": True}
    mock_email.assert_called_once()
    assert mock_email.call_args[0][0] == "student@uni.lu"
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["picked_up_at"] is not None


def test_mark_picked_up_before_claiming_is_409(client):
    order_id = _create_basic_order(client)
    with patch("app.send_order_out_for_delivery") as mock_email:
        resp = _pickup(client, order_id)
    assert resp.status_code == 409
    mock_email.assert_not_called()


def test_mark_picked_up_twice_does_not_reemail(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_accepted", return_value=(True, None)):
        _claim(client, order_id)
    with patch("app.send_order_out_for_delivery", return_value=(True, None)) as mock_email:
        _pickup(client, order_id)
        resp = _pickup(client, order_id)
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
    resp = _mark_delivered(client, order_id)
    assert resp.status_code == 200
    assert resp.get_json()["delivered"] is True
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert listed["delivered_at"] is not None


def test_mark_order_delivered_unknown_order_404s(client):
    resp = _mark_delivered(client, 999999)
    assert resp.status_code == 404


def test_mark_order_not_delivered_undoes_it(client):
    order_id = _create_basic_order(client)
    _mark_delivered(client, order_id)
    resp = _mark_not_delivered(client, order_id)
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
        )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Admin confirmation workflow (Part 30)
# ---------------------------------------------------------------------------


def _uni_email_for(customer_email):
    """Orders now belong to a verified University email (reward_email).
    Tests that order with a uni.lu customer_email are their own student;
    anything else (a personal address) belongs to student@uni.lu."""
    return customer_email if customer_email and customer_email.lower().endswith("uni.lu") else "student@uni.lu"


def _create_basic_order(client, customer_email="student@uni.lu", customer_note=None, delivery_location="Building A — Room 1.01", reward_email=None):
    payload = {"restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}]}
    if delivery_location:
        payload["delivery_location"] = delivery_location
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
    reward_email = reward_email or _uni_email_for(customer_email)
    payload["reward_email"] = reward_email
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(reward_email)
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
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
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
        )
    assert mock_notify.call_args.kwargs["mark_reviewing_url"] is None


def test_create_order_still_succeeds_when_telegram_notify_fails(client):
    # Best-effort, same as the email confirmation -- a Telegram failure
    # must never turn a successful order into a 500.
    with patch("app.send_admin_notification", return_value=(False, "chat not found")):
        resp = client.post(
            "/api/orders",
            json={
            "delivery_location": "Building A — Room 1.01", "restaurant": "altius", "date": "2026-09-24", "items": [{"id": SALAD_BAR_ID, "quantity": 1}], "customer_email": "student@uni.lu", "reward_email": _uni_email_for("student@uni.lu")},
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

    resp = client.post(f"/{path}")
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

    resp = client.post(f"/{path}")
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

    first = client.post(f"/{path}")
    second = client.post(f"/{path}")
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


# ---------------------------------------------------------------------------
# Audit fixes: Medium / Low
# ---------------------------------------------------------------------------


def _create_order_with_reward_email(client, customer_email, reward_email):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(customer_email)
    payload = {
        "restaurant": "altius",
        "date": "2026-09-24",
        "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
        "delivery_location": "Building A — Room 1.01",
        "customer_email": customer_email,
        "reward_email": reward_email,
    }
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(reward_email)
    with patch("app.send_admin_notification", return_value=(True, None)):
        return client.post("/api/orders", json=payload).get_json()["id"]


def test_order_luni_goes_to_the_university_email_not_the_communication_email(client):
    order_id = _create_order_with_reward_email(client, "me@gmail.com", "student@uni.lu")
    _hand_off(client, order_id)
    _mark_delivered(client, order_id)
    assert _points(client, "student@uni.lu") == 1
    assert client.application.config["REWARD_STORE"].get_points("me@gmail.com") == 0


def test_courier_delivering_to_their_own_reward_email_earns_nothing(client):
    order_id = _create_order_with_reward_email(client, "me@gmail.com", "courier@uni.lu")
    _hand_off(client, order_id, courier_email="courier@uni.lu")
    _mark_delivered(client, order_id)
    assert _points(client, "courier@uni.lu") == 0


def test_reward_email_is_never_exposed_publicly(client):
    order_id = _create_order_with_reward_email(client, "me@gmail.com", "student@uni.lu")
    assert "reward_email" not in client.get(f"/api/orders/{order_id}").get_json()
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert "reward_email" not in listed


def test_send_code_is_rate_limited_per_ip_across_addresses(client):
    with patch("app.send_verification_code", return_value=(True, None)):
        codes = [
            client.post("/api/email/send-code", json={"email": f"s{i}@uni.lu"}).status_code for i in range(20)
        ]
        # The three send-code routes share one budget.
        blocked = client.post("/api/orders/email/send-code", json={"email": "someone@gmail.com"})
    assert codes == [200] * 20
    assert blocked.status_code == 429


def test_quick_courier_registration_requires_a_verified_email(client):
    resp = client.post("/api/delivery/register/quick", json={"email": "never-verified@uni.lu"})
    assert resp.status_code == 403
    assert client.application.config["DELIVERY_SUBSCRIBER_STORE"].list_subscribers() == []
    assert client.post("/api/delivery/register/quick", json={"email": "student@uni.lu"}).status_code == 200


def test_rewards_claim_is_rate_limited(client):
    codes = [_claim_reward(client, "phone_number_added", "621123456").status_code for _ in range(31)]
    assert codes == [200] * 30 + [429]


def _price_order(client, order_id):
    with patch("app.send_order_needs_confirmation", return_value=(True, None)) as mock_send:
        client.post(f"/admin/orders/{order_id}/set-price?token=correct-token", data={"real_price": "8.50"})
    confirm_url, cancel_url = mock_send.call_args[0][3], mock_send.call_args[0][4]
    strip = lambda url: "/" + url.split("://", 1)[1].split("/", 1)[1]  # noqa: E731
    return strip(confirm_url), strip(cancel_url)


@pytest.mark.parametrize("which", ["confirm", "cancel"])
def test_opening_an_email_link_only_shows_a_button(client, monkeypatch, which):
    # A mail scanner opening the link must not decide the order.
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    confirm_path, cancel_path = _price_order(client, order_id)
    resp = client.get(confirm_path if which == "confirm" else cancel_path)
    assert resp.status_code == 200
    assert b'method="post"' in resp.data
    assert client.get(f"/api/orders/{order_id}").get_json()["status"] == "awaiting_confirmation"


def test_email_link_page_for_a_used_link_says_so_up_front(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    confirm_path, cancel_path = _price_order(client, order_id)
    client.post(confirm_path)
    resp = client.get(cancel_path)
    assert b"link isn" in resp.data
    assert b'method="post"' not in resp.data


def test_opening_an_approve_link_does_not_publish(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client).get_json()
    resp = client.get(f"/admin/dish-photos/{upload['id']}/approve?token=correct-token")
    assert resp.status_code == 200
    assert b'method="post"' in resp.data
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}


def test_approve_post_without_token_is_404(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    upload = _upload_dish_photo(client).get_json()
    assert client.post(f"/admin/dish-photos/{upload['id']}/approve").status_code == 404
    assert client.get("/api/restaurants/altius/dish-photos").get_json() == {}


def test_delivery_list_never_includes_the_customer_note(client):
    order_id = _create_basic_order(client, customer_note="call me on +352 000 000")
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)
    assert "customer_note" not in listed


def test_delivery_list_keeps_the_full_location_until_delivered_then_only_the_building(client):
    order_id = _create_basic_order(client, delivery_location="Building G — 2211 room")
    listed = lambda: next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == order_id)  # noqa: E731
    assert listed()["delivery_location"] == "Building G — 2211 room"
    _mark_delivered(client, order_id)
    assert listed()["delivery_location"] == "Building G"


def test_delivery_list_drops_orders_older_than_two_weeks(client):
    order_id = _create_basic_order(client)
    store = client.application.config["ORDER_STORE"]
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=15)).isoformat()
    with store._lock:
        store._conn.execute("UPDATE orders SET created_at = ? WHERE id = ?", (old, order_id))
        store._conn.commit()
    assert order_id not in [o["id"] for o in client.get("/api/delivery/orders").get_json()]


def test_upload_dish_photo_rejects_an_overlong_name(client):
    resp = _upload_dish_photo(client, name="x" * 201)
    assert resp.status_code == 400


def test_stale_pending_photos_expire_with_their_files(client):
    stale = _upload_dish_photo(client, name="Old dish").get_json()
    pending_store = client.application.config["PENDING_DISH_PHOTO_STORE"]
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31)).isoformat()
    with pending_store._connect() as conn:
        conn.execute("UPDATE pending_dish_photos SET submitted_at = ? WHERE id = ?", (old, stale["id"]))
    fresh = _upload_dish_photo(client, name="New dish").get_json()
    assert pending_store.get(stale["id"]) is None
    assert client.get(stale["photo_path"]).status_code == 404
    assert pending_store.get(fresh["id"]) is not None


def test_security_headers_on_every_response(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_admin_and_email_link_pages_never_leak_their_token(client):
    resp = client.get("/o/1/confirm?token=nonsense")
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Cache-Control"] == "no-store"


def test_award_once_records_and_pays_together(tmp_path):
    rewards = RewardStore(tmp_path / "r.db")
    assert rewards.award_once("a@uni.lu", "x:1", 2) is True
    assert rewards.award_once("a@uni.lu", "x:1", 2) is False
    assert rewards.get_points("a@uni.lu") == 2


# ---------------------------------------------------------------------------
# Order limits: 2 per dish, 2 orders per day per client
# ---------------------------------------------------------------------------


def _order_payload(items, customer_email="student@uni.lu", date="2026-09-24", **extra):
    return {
        "restaurant": "altius",
        "date": date,
        "items": items,
        "delivery_location": "Building A — Room 1.01",
        "customer_email": customer_email,
        "reward_email": _uni_email_for(customer_email),
        **extra,
    }


def _post_order(client, payload):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(payload["customer_email"])
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified(payload["reward_email"])
    with patch("app.send_admin_notification", return_value=(True, None)):
        return client.post("/api/orders", json=payload)


def test_a_dish_can_be_ordered_twice_but_not_three_times(client):
    assert _post_order(client, _order_payload([{"id": SALAD_BAR_ID, "quantity": 2}])).status_code == 201
    resp = _post_order(client, _order_payload([{"id": SALAD_BAR_ID, "quantity": 3}], customer_email="other@uni.lu"))
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_selection"


def test_an_order_can_hold_several_different_dishes_two_each(client):
    resp = _post_order(
        client, _order_payload([{"id": SALAD_BAR_ID, "quantity": 2}, {"id": BRETZEL_ID, "quantity": 2}])
    )
    assert resp.status_code == 201
    assert sum(i["quantity"] for i in resp.get_json()["items"]) == 4


def test_menu_advertises_the_per_dish_cap(client):
    assert client.get("/api/restaurants/altius/menu/2026-09-24").get_json()["max_quantity"] == 2


def test_third_order_for_the_same_day_is_refused(client):
    payload = _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}])
    assert _post_order(client, payload).status_code == 201
    assert _post_order(client, payload).status_code == 201
    resp = _post_order(client, payload)
    assert resp.status_code == 409
    assert resp.get_json() == {
        "error": "daily_order_limit",
        "message": "You can place at most 2 orders for the same day",
        "max_orders": 2,
    }


def test_the_daily_limit_is_per_client_not_global(client):
    payload = _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}])
    for _ in range(2):
        _post_order(client, payload)
    other = dict(payload, customer_email="courier@uni.lu", reward_email="courier@uni.lu")
    assert _post_order(client, other).status_code == 201


def test_the_daily_limit_is_per_order_date(client):
    payload = _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}])
    for _ in range(2):
        _post_order(client, payload)
    assert _order_count(client, "2026-09-24") == 2
    # A different day is a fresh allowance.
    assert _order_count(client, "2026-09-25") == 0


def test_the_daily_limit_ignores_case_in_the_email(client):
    for email in ("student@uni.lu", "Student@Uni.lu"):
        assert _post_order(client, _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}], customer_email=email)).status_code == 201
    resp = _post_order(client, _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}], customer_email="STUDENT@uni.lu"))
    assert resp.status_code == 409


def test_a_second_address_cannot_dodge_the_limit_via_the_university_email(client):
    for personal in ("a@gmail.com", "b@gmail.com"):
        resp = _post_order(
            client, _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}], customer_email=personal, reward_email="student@uni.lu")
        )
        assert resp.status_code == 201
    resp = _post_order(
        client, _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}], customer_email="c@gmail.com", reward_email="student@uni.lu")
    )
    assert resp.status_code == 409


def test_a_cancelled_order_frees_up_the_allowance(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    payload = _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}])
    first = _post_order(client, payload).get_json()["id"]
    _post_order(client, payload)
    assert _post_order(client, payload).status_code == 409
    store = client.application.config["ORDER_STORE"]
    store.cancel_order(first, store.set_real_price(first, 6.70))
    assert _post_order(client, payload).status_code == 201


def test_a_refused_order_sends_no_notifications(client):
    payload = _order_payload([{"id": SALAD_BAR_ID, "quantity": 1}])
    for _ in range(2):
        _post_order(client, payload)
    with patch("app.send_admin_notification") as admin, patch("app.send_order_confirmation") as confirmation:
        assert client.post("/api/orders", json=payload).status_code == 409
    admin.assert_not_called()
    confirmation.assert_not_called()


def _order_count(client, order_date):
    return client.application.config["ORDER_STORE"].count_live_orders_for_day(
        datetime.date.fromisoformat(order_date), ["student@uni.lu"]
    )


# ---------------------------------------------------------------------------
# Ordering needs a verified University email; note/feedback length caps
# ---------------------------------------------------------------------------


def _bare_order(**overrides):
    payload = {
        "restaurant": "altius",
        "date": "2026-09-24",
        "items": [{"id": SALAD_BAR_ID, "quantity": 1}],
        "delivery_location": "Building A — Room 1.01",
        "customer_email": "student@uni.lu",
        "reward_email": "student@uni.lu",
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def test_order_without_a_university_email_is_refused(client):
    with patch("app.send_admin_notification") as admin:
        resp = client.post("/api/orders", json=_bare_order(reward_email=None))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "university_email_required"
    admin.assert_not_called()


def test_order_with_an_unverified_university_email_is_refused(client):
    resp = client.post("/api/orders", json=_bare_order(reward_email="never-verified@uni.lu"))
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "university_email_not_verified"


def test_order_with_a_non_university_reward_email_is_refused(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("me@gmail.com")
    resp = client.post("/api/orders", json=_bare_order(reward_email="me@gmail.com"))
    assert resp.status_code == 400


def test_a_verified_personal_customer_email_alone_is_not_enough(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("throwaway@passinbox.com")
    resp = client.post("/api/orders", json=_bare_order(customer_email="throwaway@passinbox.com", reward_email=None))
    assert resp.status_code == 403


def test_personal_notification_email_still_works_with_a_university_email(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("me@gmail.com")
    with patch("app.send_admin_notification", return_value=(True, None)):
        resp = client.post("/api/orders", json=_bare_order(customer_email="me@gmail.com"))
    assert resp.status_code == 201


def test_customer_note_of_200_characters_is_allowed_and_201_is_not(client):
    with patch("app.send_admin_notification", return_value=(True, None)):
        assert client.post("/api/orders", json=_bare_order(customer_note="x" * 200)).status_code == 201
    assert client.post("/api/orders", json=_bare_order(customer_note="x" * 201)).status_code == 400


def test_feedback_of_500_characters_is_allowed_and_501_is_not(client):
    with patch("app.send_feedback_notification"):
        assert client.post("/api/feedback", json={"message": "x" * 500}).status_code == 200
        assert client.post("/api/feedback", json={"message": "x" * 501}).status_code == 400


# ---------------------------------------------------------------------------
# A client may have live orders on at most 2 different days -- any 2 of the
# days on offer, not just the next two
# ---------------------------------------------------------------------------


def _seed_order_on(client, order_date, email="student@uni.lu", cancelled=False):
    """A live order for `order_date`, written straight to the store (the
    fixture menu only covers a couple of real dates)."""
    store = client.application.config["ORDER_STORE"]
    order_id = store.create_order(
        "UDL-CKB-ALTIUS",
        "Altius",
        datetime.date.fromisoformat(order_date),
        [{"category": "Entrée", "name": "Salad'bar", "quantity": 1}],
        "Building A — Room 1.01",
        email,
        reward_email=email,
    )
    if cancelled:
        store.admin_cancel_order(order_id)
    return order_id


def test_a_third_different_day_is_refused(client):
    # Fixture "today" is 2026-09-23; the two seeded days are both upcoming.
    _seed_order_on(client, "2026-09-30")
    _seed_order_on(client, "2026-10-01")
    with patch("app.send_admin_notification") as admin:
        resp = client.post("/api/orders", json=_bare_order(date="2026-09-24"))
    assert resp.status_code == 409
    assert resp.get_json() == {
        "error": "order_days_limit",
        "message": "You can have orders on at most 2 different days at a time",
        "max_days": 2,
    }
    admin.assert_not_called()


def test_a_second_day_is_fine(client):
    _seed_order_on(client, "2026-09-30")
    with patch("app.send_admin_notification", return_value=(True, None)):
        assert client.post("/api/orders", json=_bare_order(date="2026-09-24")).status_code == 201


def test_ordering_again_on_a_day_you_already_have_is_not_a_new_day(client):
    _seed_order_on(client, "2026-09-24")
    _seed_order_on(client, "2026-09-30")
    with patch("app.send_admin_notification", return_value=(True, None)):
        assert client.post("/api/orders", json=_bare_order(date="2026-09-24")).status_code == 201


def test_cancelled_orders_do_not_count_as_a_day(client):
    _seed_order_on(client, "2026-09-30", cancelled=True)
    _seed_order_on(client, "2026-10-01")
    with patch("app.send_admin_notification", return_value=(True, None)):
        assert client.post("/api/orders", json=_bare_order(date="2026-09-24")).status_code == 201


def test_past_days_do_not_count_as_a_day(client):
    _seed_order_on(client, "2026-09-20")
    _seed_order_on(client, "2026-09-21")
    with patch("app.send_admin_notification", return_value=(True, None)):
        assert client.post("/api/orders", json=_bare_order(date="2026-09-24")).status_code == 201


def test_the_days_limit_is_per_client(client):
    _seed_order_on(client, "2026-09-30")
    _seed_order_on(client, "2026-10-01")
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("courier@uni.lu")
    with patch("app.send_admin_notification", return_value=(True, None)):
        resp = client.post("/api/orders", json=_bare_order(date="2026-09-24", customer_email="courier@uni.lu", reward_email="courier@uni.lu"))
    assert resp.status_code == 201


def test_the_days_limit_follows_the_university_email_across_personal_addresses(client):
    _seed_order_on(client, "2026-09-30")
    _seed_order_on(client, "2026-10-01")
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("me@gmail.com")
    resp = client.post("/api/orders", json=_bare_order(date="2026-09-24", customer_email="me@gmail.com"))
    assert resp.status_code == 409 and resp.get_json()["error"] == "order_days_limit"


def test_there_is_no_two_day_booking_horizon(client):
    # Any day on offer can be ordered, however far out: a far date is judged
    # by its own menu/status (409 date_not_available here), never refused
    # just for being far.
    resp = client.post("/api/orders", json=_bare_order(date="2026-10-15"))
    assert resp.get_json()["error"] != "date_too_far"


# ---------------------------------------------------------------------------
# Luni penalties for orders that fall through after a courier claimed them
# ---------------------------------------------------------------------------
# The orders in this file are for 2026-09-24, which is long past on the real
# clock, so they count as "expired" unless a test patches app.is_delivery_expired.


def _claim_quietly(client, order_id, courier_email="courier@uni.lu"):
    with patch("app.send_order_claimed_notification", return_value=(True, None)), patch(
        "app.send_delivery_notification", return_value=(True, None)
    ), patch("app.send_order_accepted", return_value=(True, None)):
        return _claim(client, order_id, courier_email=courier_email)


def _price(client, order_id):
    return client.application.config["ORDER_STORE"].set_real_price(order_id, 8.50)


def _confirm(client, order_id):
    store = client.application.config["ORDER_STORE"]
    assert store.confirm_order(order_id, _price(client, order_id))


def _give(client, email, points):
    client.application.config["REWARD_STORE"].add_points(email, points)


def test_customer_who_never_confirms_a_claimed_order_loses_1_luni(client):
    _give(client, "student@uni.lu", 3)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    _price(client, order_id)  # admin priced it, customer said nothing
    assert _points(client, "student@uni.lu") == 2
    assert _points(client, "courier@uni.lu") == 0


def test_the_no_confirm_penalty_is_charged_once_per_order(client):
    _give(client, "student@uni.lu", 3)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    _price(client, order_id)
    for _ in range(3):
        _points(client, "student@uni.lu")
    assert _points(client, "student@uni.lu") == 2


def test_a_penalty_never_takes_a_balance_below_zero(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    _price(client, order_id)
    assert _points(client, "student@uni.lu") == 0


def test_courier_who_never_picks_up_a_confirmed_order_loses_1_luni(client):
    _give(client, "courier@uni.lu", 2)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    _confirm(client, order_id)
    assert _points(client, "courier@uni.lu") == 1
    assert _points(client, "student@uni.lu") == 0  # the customer did their part


def test_no_penalty_for_a_courier_who_picked_the_order_up(client):
    _give(client, "courier@uni.lu", 2)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    _confirm(client, order_id)
    assert _points(client, "courier@uni.lu") == 2


def test_no_penalty_before_the_delivery_day_is_over(client):
    _give(client, "student@uni.lu", 3)
    _give(client, "courier@uni.lu", 3)
    unconfirmed = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, unconfirmed)
    _price(client, unconfirmed)
    with patch("app.is_delivery_expired", return_value=False):
        assert _points(client, "student@uni.lu") == 3
        assert _points(client, "courier@uni.lu") == 3


def test_no_penalty_when_nobody_claimed_the_order(client):
    _give(client, "student@uni.lu", 3)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _price(client, order_id)
    assert _points(client, "student@uni.lu") == 3


def test_no_penalty_when_the_admin_never_priced_the_order(client):
    # Still pending: the customer had nothing to confirm yet.
    _give(client, "student@uni.lu", 3)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    assert _points(client, "student@uni.lu") == 3


def test_no_penalty_for_a_courier_who_released_the_order_in_time(client):
    _give(client, "courier@uni.lu", 2)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    _unclaim(client, order_id)
    _confirm(client, order_id)
    assert _points(client, "courier@uni.lu") == 2


def test_no_penalty_for_a_delivered_order(client):
    _give(client, "student@uni.lu", 3)
    _give(client, "courier@uni.lu", 3)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    _mark_delivered(client, order_id)
    _price(client, order_id)
    assert _points(client, "student@uni.lu") == 4  # +1 for the delivery, no penalty
    assert _points(client, "courier@uni.lu") == 4


def test_no_penalty_for_a_cancelled_order(client):
    _give(client, "student@uni.lu", 3)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    store = client.application.config["ORDER_STORE"]
    store.cancel_order(order_id, _price(client, order_id))
    assert _points(client, "student@uni.lu") == 3


def test_penalty_goes_to_the_university_email_not_the_personal_one(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("me@gmail.com")
    _give(client, "student@uni.lu", 3)
    order_id = _create_basic_order(client, customer_email="me@gmail.com", reward_email="student@uni.lu")
    _claim_quietly(client, order_id)
    _price(client, order_id)
    assert _points(client, "student@uni.lu") == 2


def test_the_delivery_list_also_applies_penalties(client):
    _give(client, "courier@uni.lu", 2)
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _claim_quietly(client, order_id)
    _confirm(client, order_id)
    client.get("/api/delivery/orders")
    assert client.application.config["REWARD_STORE"].get_points("courier@uni.lu") == 1


# ---------------------------------------------------------------------------
# Admin: cancel an order from the /admin/orders panel
# ---------------------------------------------------------------------------


def _admin_status(client, order_id):
    return client.get(f"/api/orders/{order_id}").get_json()["status"]


def test_admin_can_cancel_a_pending_order(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    resp = client.post(f"/admin/orders/{order_id}/cancel?token=correct-token")
    assert resp.status_code == 302 and "/admin/orders" in resp.headers["Location"]
    assert _admin_status(client, order_id) == "cancelled"


def test_admin_can_cancel_a_reviewing_and_an_awaiting_order(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    store = client.application.config["ORDER_STORE"]
    reviewing = _create_basic_order(client, customer_email="student@uni.lu")
    store.mark_reviewing(reviewing)
    awaiting = _create_basic_order(client, customer_email="courier@uni.lu")
    store.set_real_price(awaiting, 8.50)
    for order_id in (reviewing, awaiting):
        client.post(f"/admin/orders/{order_id}/cancel?token=correct-token")
        assert _admin_status(client, order_id) == "cancelled"


def test_admin_cancel_needs_the_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    assert client.post(f"/admin/orders/{order_id}/cancel").status_code == 404
    assert client.post(f"/admin/orders/{order_id}/cancel?token=wrong").status_code == 404
    assert _admin_status(client, order_id) == "pending"


def test_opening_the_cancel_link_only_asks_it_does_not_cancel(client, monkeypatch):
    # The Telegram button is a plain URL (GET): a preview or stray tap must
    # not remove the order -- only the page's own POST button does.
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    resp = client.get(f"/admin/orders/{order_id}/cancel?token=correct-token")
    assert resp.status_code == 200
    assert b'method="post"' in resp.data and b"Remove order" in resp.data
    assert _admin_status(client, order_id) == "pending"


def test_the_cancel_page_needs_the_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    assert client.get(f"/admin/orders/{order_id}/cancel").status_code == 404
    assert client.get(f"/admin/orders/{order_id}/cancel?token=wrong").status_code == 404


def test_the_cancel_page_for_a_finished_order_says_so(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    _confirm(client, order_id)
    resp = client.get(f"/admin/orders/{order_id}/cancel?token=correct-token")
    assert b"can&#39;t be removed anymore" in resp.data or b"can't be removed anymore" in resp.data
    assert b'method="post"' not in resp.data


def test_the_new_order_telegram_ping_carries_a_cancel_link(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    with patch("app.send_admin_notification", return_value=(True, None)) as mock_notify:
        order_id = client.post("/api/orders", json=_bare_order()).get_json()["id"]
    cancel_url = mock_notify.call_args.kwargs["cancel_url"]
    assert f"/admin/orders/{order_id}/cancel?token=correct-token" in cancel_url


def test_no_cancel_link_without_an_admin_token(client):
    with patch("app.send_admin_notification", return_value=(True, None)) as mock_notify:
        client.post("/api/orders", json=_bare_order())
    assert mock_notify.call_args.kwargs["cancel_url"] is None


def test_admin_cancel_of_a_missing_order_is_404(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    assert client.post("/admin/orders/999999/cancel?token=correct-token").status_code == 404


def test_admin_cancel_leaves_a_confirmed_order_alone(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    order_id = _create_basic_order(client)
    _confirm(client, order_id)
    client.post(f"/admin/orders/{order_id}/cancel?token=correct-token")
    assert _admin_status(client, order_id) == "confirmed"


def test_the_admin_panel_shows_a_cancel_button_per_order(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    pending = _create_basic_order(client, customer_email="student@uni.lu")
    awaiting = _create_basic_order(client, customer_email="courier@uni.lu")
    client.application.config["ORDER_STORE"].set_real_price(awaiting, 8.50)
    page = client.get("/admin/orders?token=correct-token").data.decode()
    assert f"/admin/orders/{pending}/cancel?token=correct-token" in page
    assert f"/admin/orders/{awaiting}/cancel?token=correct-token" in page


def test_cancelling_frees_the_customers_daily_slot_and_closes_it_for_couriers(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    ids = [_create_basic_order(client) for _ in range(2)]
    client.post(f"/admin/orders/{ids[0]}/cancel?token=correct-token")
    assert _create_basic_order(client)  # a third would have been refused without the cancel
    listed = next(o for o in client.get("/api/delivery/orders").get_json() if o["id"] == ids[0])
    assert listed["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Sharing a dish: the link preview is THAT dish's card, not the app banner
# ---------------------------------------------------------------------------

from urllib.parse import quote  # noqa: E402


def _menu_items(client, date="2026-09-24"):
    return client.get(f"/api/restaurants/altius/menu/{date}").get_json()["items"]


def _share_url(item, date="2026-09-24", lang=None, slug="altius"):
    url = f"/?dish={slug}&date={date}&cat={quote(item['category'])}&name={quote(item['name'])}"
    return url + (f"&lang={lang}" if lang else "")


def _meta(html, prop):
    import re

    m = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', html)
    return m.group(1) if m else None


def _item(client, category_startswith, name_contains=""):
    return next(i for i in _menu_items(client) if i["category"].startswith(category_startswith) and name_contains in i["name"])


def test_the_plain_link_keeps_the_generic_preview(client):
    html = client.get("/").data.decode()
    assert _meta(html, "og:title") == "UniResto · Campus Kirchberg"
    assert _meta(html, "og:image").endswith("/static/og-image.png")


def test_a_dish_link_previews_that_dish(client):
    main = _item(client, "Végétarien")
    html = client.get(_share_url(main)).data.decode()
    # the preview title is in the sharer's language (default English) when the dish has a translation
    from orderability_engine.dish_name_labels import dish_name_label
    from orderability_engine.dish_names import split_dish_size

    expected = split_dish_size(dish_name_label(main["name"], "en"))[0]
    assert expected.replace("'", "&#39;") in _meta(html, "og:title") or expected in _meta(html, "og:title")
    assert "€6.70" in _meta(html, "og:title")  # a main dish alone: the Formule 3 price
    assert "Altius" in _meta(html, "og:description") and "order on UniResto" in _meta(html, "og:description")
    image = _meta(html, "og:image")
    assert "/og/dish.jpg?" in image and "dish=altius" in image and "date=2026-09-24" in image
    assert _meta(html, "twitter:image") == image and _meta(html, "twitter:card") == "summary_large_image"


def test_a_sized_dish_shows_its_size_in_the_description_not_the_title(client):
    drink = _item(client, "10.1", "Rosport Blue")
    html = client.get(_share_url(drink)).data.decode()
    title = _meta(html, "og:title")
    assert "Rosport Blue" in title and "l btl" not in title and "non consign" not in title
    assert drink["name"].split("Rosport Blue ")[1] in _meta(html, "og:description")


def test_a_dish_with_no_price_says_canteen_price(client):
    starter = _item(client, "Entrée")
    assert "Canteen Price" in _meta(client.get(_share_url(starter)).data.decode(), "og:title")


def test_the_dish_title_follows_the_sharers_language(client):
    salad = next((i for i in _menu_items(client) if i["name"] == "Mini salades 150 g"), None)
    if salad is None:
        pytest.skip("fixture menu has no Mini salades")
    assert _meta(client.get(_share_url(salad, lang="en")).data.decode(), "og:title").startswith("Mini salads")
    assert _meta(client.get(_share_url(salad, lang="fr")).data.decode(), "og:title").startswith("Mini salades")


@pytest.mark.parametrize(
    "query",
    [
        "?dish=nowhere&date=2026-09-24&cat=X&name=Y",
        "?dish=altius&date=not-a-date&cat=X&name=Y",
        "?dish=altius&date=2026-09-24&cat=Entr%C3%A9e&name=A%20dish%20that%20does%20not%20exist",
        "?dish=altius&date=2026-09-24",
        '?dish=altius&date=2026-09-24&cat="><script>alert(1)</script>&name=x',
    ],
)
def test_a_broken_dish_link_falls_back_to_the_generic_preview(client, query):
    resp = client.get("/" + query)
    assert resp.status_code == 200
    html = resp.data.decode()
    assert _meta(html, "og:title") == "UniResto · Campus Kirchberg"
    assert "<script>alert(1)" not in html


def test_the_card_image_is_a_1200_by_630_jpeg_small_enough_for_whatsapp(client):
    main = _item(client, "Végétarien")
    resp = client.get(f"/og/dish.jpg?dish=altius&date=2026-09-24&cat={quote(main['category'])}&name={quote(main['name'])}")
    assert resp.status_code == 200 and resp.mimetype == "image/jpeg"
    assert len(resp.data) < 300_000
    assert "max-age" in resp.headers["Cache-Control"]
    image = Image.open(io.BytesIO(resp.data))
    assert image.size == (1200, 630)


def test_the_card_image_is_cached_between_requests(client, tmp_path):
    main = _item(client, "Végétarien")
    url = f"/og/dish.jpg?dish=altius&date=2026-09-24&cat={quote(main['category'])}&name={quote(main['name'])}"
    client.get(url)
    files = list((tmp_path / "og_cache").glob("*.jpg"))
    assert len(files) == 1
    mtime = files[0].stat().st_mtime_ns
    client.get(url)
    assert [f.stat().st_mtime_ns for f in (tmp_path / "og_cache").glob("*.jpg")] == [mtime]


def test_the_card_image_404s_for_a_dish_that_is_not_on_the_menu(client):
    assert client.get("/og/dish.jpg?dish=altius&date=2026-09-24&cat=Entr%C3%A9e&name=Nope").status_code == 404
    assert client.get("/og/dish.jpg").status_code == 404


def test_an_approved_photo_changes_the_card(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "correct-token")
    dish = _item(client, "Entrée", "Salad'bar")
    url = f"/og/dish.jpg?dish=altius&date=2026-09-24&cat={quote(dish['category'])}&name={quote(dish['name'])}"
    placeholder = client.get(url).data
    upload = client.post(
        "/api/restaurants/altius/dish-photos",
        data={
            "email": "student@uni.lu",
            "category": dish["category"],
            "name": dish["name"],
            "photo": (io.BytesIO(_image_bytes((200, 40, 40), size=(64, 48))), "dish.png"),
        },
        content_type="multipart/form-data",
    ).get_json()
    client.post(f"/admin/dish-photos/{upload['id']}/approve", data={"token": "correct-token"})
    with_photo = Image.open(io.BytesIO(client.get(url).data)).convert("RGB")
    assert client.get(url).data != placeholder
    r, g, b = with_photo.getpixel((200, 300))  # inside the photo panel: the red image, not the pale placeholder
    assert r > 150 and g < 120 and b < 120
