#!/usr/bin/env python3
"""Flask app: JSON API + admin debug page + customer-facing UI for the
orderability engine. Dev server only (see README.md) -- no payment, no
real Restopolis order placement, no delivery routing.
"""

from __future__ import annotations

import hashlib
import io
import time
import logging
import os
import re
import json
import secrets
from urllib.parse import unquote
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from orderability_engine.cache import OrderabilityCache
from orderability_engine.coming_soon_clicks import ComingSoonClickStore
from orderability_engine.daily_report import DailyReportStore, start_daily_report_scheduler
from orderability_engine.delivery_subscribers import DeliverySubscriberStore
from orderability_engine.dish_card import render_dish_card
from orderability_engine.dish_name_labels import dish_name_label
from orderability_engine.dish_names import split_dish_size
from orderability_engine.dish_photos import DishPhotoStore
from orderability_engine.identity import canonical_identity, normalize_contact_email, normalize_phone
from orderability_engine.email_verification import EmailVerificationStore
from orderability_engine.feedback import FeedbackStore
from orderability_engine.mailer import (
    generate_verification_code,
    send_delivery_notification,
    send_order_accepted,
    send_order_confirmation,
    send_order_needs_confirmation,
    send_order_out_for_delivery,
    send_verification_code,
)
from orderability_engine.menu_refresh import start_menu_refresh_scheduler
from orderability_engine.menu_service import flatten_menu_items, get_customer_menu
from orderability_engine.delivery_rules import is_delivery_expired
from orderability_engine.models import STATUS_VALUES, TZINFO
from orderability_engine.orders import (
    MAX_ORDERS_PER_DAY,
    MAX_ORDER_DATES,
    MAX_QUANTITY,
    DailyOrderLimitError,
    OrderDatesLimitError,
    OrderStore,
    OrderValidationError,
    recalculate_order,
)
from orderability_engine.page_views import MAX_SOURCE_LENGTH, PageViewStore
from orderability_engine.pending_dish_photos import PendingDishPhotoStore
from orderability_engine.photo_sanitize import sanitize_dish_photo
from orderability_engine.pricing import INCLUDED_SIDE_CATEGORIES, compute_formula_total
from orderability_engine.rate_limits import RateLimitStore
from orderability_engine.rewards import (
    CLAIM_ALREADY_AWARDED,
    CLAIM_AWARDED,
    COMMUNICATION_EMAIL_ADDED,
    COURIER_NO_SHOW,
    DELIVERY_COMPLETED,
    DISH_PHOTO_APPROVED,
    ORDER_NOT_CONFIRMED,
    ORDER_PLACED,
    PHONE_NUMBER_ADDED,
    REWARD_POINTS,
    UNIVERSITY_EMAIL_VERIFIED,
    RewardStore,
)
from orderability_engine.service import OrderabilityService
from orderability_engine.smart_lunch import TIER_ORDER, find_smart_lunch
from orderability_engine.verified_emails import VerifiedEmailStore
from orderability_engine.admin_stats import build_stats_message
from orderability_engine.telegram_notify import (
    is_admin_chat,
    is_stats_request,
    send_admin_notification,
    send_admin_text,
    send_dish_photo_review,
    send_feedback_notification,
    send_order_claimed_notification,
    send_order_released_notification,
    webhook_secret,
)
from restopolis.client import BASE_URL as RESTOPOLIS_BASE_URL
from restopolis.config import load_restaurants
from scraper import slug_for

# Loads RESEND_API_KEY/etc from a git-ignored .env file in the
# working directory (see orderability_engine/mailer.py's docstring and
# README.md Part 23) -- a no-op if .env doesn't exist (local dev with no
# email configured yet) or if the real values already came from the
# environment directly (systemd's EnvironmentFile in production; dotenv
# never overrides an already-set var).
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(message)s")

ADMIN_LOOKAHEAD_DAYS = 10

# Campus-only audience: the checkout email field (Part 23) must be a
# University of Luxembourg address. Both domains Restopolis itself is
# scoped to (student and staff/general uni.lu accounts) -- not derived
# from any Restopolis data, this is OUR OWN validation rule.
ALLOWED_EMAIL_DOMAINS = ("@uni.lu", "@student.uni.lu")

# Open Graph / Twitter Card preview text (Part 70), one per language static/
# i18n.js's LANGUAGES list offers. The title reuses that file's own
# `tagline` string verbatim so the preview matches the in-app UI exactly;
# the description is this table's own text, since i18n.js has no
# equivalent key. This has to live here rather than in i18n.js because the
# preview is built server-side (crawlers fetch the URL directly and never
# run our JS) from static/app.js's `?lang=` URL param -- see
# syncLangInUrl() there for how that param gets onto the shared URL in the
# first place.
OG_PREVIEW_TEXT = {
    "en": {
        "title": "UniResto · Campus Kirchberg",
        "description": "Order lunch from University of Luxembourg Campus Kirchberg restaurants — real menus, real prices.",
    },
    "zh": {
        "title": "UniResto · Kirchberg 校区",
        "description": "从卢森堡大学基希贝格校区的餐厅订午餐——真实菜单，真实价格。",
    },
    "hi": {
        "title": "UniResto · कैम्पस किरखबर्ग",
        "description": "लक्ज़मबर्ग विश्वविद्यालय, कैंपस किरखबर्ग के रेस्तराँ से लंच ऑर्डर करें — असली मेनू, असली कीमतें।",
    },
    "es": {
        "title": "UniResto · Campus Kirchberg",
        "description": "Pide el almuerzo en los restaurantes de la Universidad de Luxemburgo, Campus Kirchberg — menús reales, precios reales.",
    },
    "fr": {
        "title": "UniResto · Campus Kirchberg",
        "description": "Commandez votre déjeuner dans les restaurants de l'Université du Luxembourg, Campus Kirchberg — vrais menus, vrais prix.",
    },
    "ar": {
        "title": "UniResto · حرم كيرشبرغ",
        "description": "اطلب غداءك من مطاعم جامعة لوكسمبورغ، حرم كيرشبرغ — قوائم حقيقية وأسعار حقيقية.",
    },
    "bn": {
        "title": "UniResto · ক্যাম্পাস কির্শবের্গ",
        "description": "লুক্সেমবার্গ বিশ্ববিদ্যালয়ের কির্শবের্গ ক্যাম্পাসের রেস্তোরাঁ থেকে লাঞ্চ অর্ডার করুন — সত্যিকারের মেনু, সত্যিকারের দাম।",
    },
    "pt": {
        "title": "UniResto · Campus Kirchberg",
        "description": "Peça o seu almoço nos restaurantes da Universidade do Luxemburgo, Campus Kirchberg — menus reais, preços reais.",
    },
    "ru": {
        "title": "UniResto · Кампус Кирхберг",
        "description": "Заказывайте обед в ресторанах Люксембургского университета, кампус Кирхберг — настоящие меню, настоящие цены.",
    },
    "ur": {
        "title": "UniResto · کیمپس کِرشبرگ",
        "description": "لکسمبرگ یونیورسٹی، کیمپس کِرشبرگ کے ریستورانوں سے لنچ آرڈر کریں — حقیقی مینو، حقیقی قیمتیں۔",
    },
    "lb": {
        "title": "UniResto · Campus Kirchberg",
        "description": "Bestell Mëttegiessen bei de Restauranten vun der Uni Lëtzebuerg, Campus Kirchberg — richtege Menüen, richtege Präisser.",
    },
}


def _is_allowed_customer_email(email: str) -> bool:
    normalized = email.strip().lower()
    if normalized.count("@") != 1 or normalized.startswith("@"):
        return False
    return normalized.endswith(ALLOWED_EMAIL_DOMAINS)


_EMAIL_FORMAT_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_lang_arg(value) -> str | None:
    """A request body's own claimed `lang` (Part 72) -- e.g. the
    customer's/courier's app language at the moment they ordered or
    registered. Reuses OG_PREVIEW_TEXT's key set as the canonical list of
    languages this app actually supports (the same set static/i18n.js's
    own LANGUAGES exports) rather than a second hardcoded copy. Anything
    else (missing, empty, a code this app doesn't have) is simply
    unknown, not a validation error -- both callers treat it the same as
    not having been given at all."""
    value = (value or "").strip().lower()
    return value if value in OG_PREVIEW_TEXT else None


def _is_valid_email_format(email: str) -> bool:
    """Looser than _is_allowed_customer_email above: no domain
    restriction. Used for the order's own customer_email, which is
    where confirmation mail actually gets sent -- a student may want
    that at a personal address even though the University email domains
    above are still required to prove campus affiliation elsewhere
    (email verification, courier registration)."""
    return bool(_EMAIL_FORMAT_RE.match(email.strip()))


# Contact details on an order: never returned by any public endpoint
# (api_get_order, api_delivery_orders) -- only the admin page and the
# order's own creation response ever show them.
PRIVATE_ORDER_FIELDS = ("customer_email", "customer_phone", "courier_email", "courier_lang", "reward_email")


MAX_CUSTOMER_NOTE_LENGTH = 200
MAX_FEEDBACK_LENGTH = 500
DELIVERY_LIST_DAYS = 14


def _as_utc(iso_timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(iso_timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _building_only(delivery_location: str | None) -> str | None:
    """"Building G — 2211 room" -> "Building G": the checkout form always
    joins building and free text with " — " (see combinedDeliveryLocation
    in static/app.js). Anything not in that shape is dropped entirely
    rather than guessed at."""
    if not delivery_location or " — " not in delivery_location:
        return None
    return delivery_location.split(" — ", 1)[0]


# Part 30's admin page (real-price entry) is more sensitive than
# /admin/orderability's read-only debug view above -- it triggers a real
# customer-facing email and changes order status -- so it's gated behind
# a shared secret (ADMIN_TOKEN env var), unlike that page. Deliberately
# NOT a full login/session system, matching this whole app's minimal-auth
# ethos elsewhere (e.g. email verification is a code, not a password).
# The admin page is simply unreachable (every request 404s) until
# ADMIN_TOKEN is actually set -- no accidentally-guessable default.
def _is_admin_authorized() -> bool:
    expected = os.environ.get("ADMIN_TOKEN")
    if not expected:
        return False
    given = request.args.get("token") or (request.form.get("token") if request.method == "POST" else None)
    return given is not None and secrets.compare_digest(given, expected)


def _admin_orders_url() -> str | None:
    """Link to /admin/orders for a Telegram ping, or None when ADMIN_TOKEN
    isn't set (the page is unreachable without it anyway)."""
    admin_token = os.environ.get("ADMIN_TOKEN")
    return f"{request.host_url}admin/orders?token={admin_token}" if admin_token else None


def _admin_dish_photo_urls(pending_id: int) -> tuple[str | None, str | None, str | None]:
    """(review_url, approve_url, reject_url) for a pending dish photo's
    Telegram ping -- all None together when ADMIN_TOKEN isn't set, same
    reasoning as _admin_orders_url() above."""
    admin_token = os.environ.get("ADMIN_TOKEN")
    if not admin_token:
        return None, None, None
    base = f"{request.host_url}admin/dish-photos/{pending_id}"
    return f"{base}?token={admin_token}", f"{base}/approve?token={admin_token}", f"{base}/reject?token={admin_token}"


def create_app(
    service: OrderabilityService | None = None,
    order_store: OrderStore | None = None,
    email_verification_store: EmailVerificationStore | None = None,
    delivery_verification_store: EmailVerificationStore | None = None,
    checkout_verification_store: EmailVerificationStore | None = None,
    verified_email_store: VerifiedEmailStore | None = None,
    dish_photo_store: DishPhotoStore | None = None,
    dish_photo_dir: str | Path | None = None,
    og_cache_dir: str | Path | None = None,
    pending_dish_photo_store: PendingDishPhotoStore | None = None,
    reward_store: RewardStore | None = None,
    delivery_subscriber_store: DeliverySubscriberStore | None = None,
    coming_soon_click_store: ComingSoonClickStore | None = None,
    feedback_store: FeedbackStore | None = None,
    page_view_store: PageViewStore | None = None,
    daily_report_store: DailyReportStore | None = None,
    rate_limit_store: RateLimitStore | None = None,
    enable_menu_refresh_scheduler: bool = True,
    enable_daily_report_scheduler: bool = True,
) -> Flask:
    app = Flask(__name__)
    # nginx (see the resto-unilu site config) terminates TLS and proxies
    # to gunicorn over plain HTTP, forwarding the real scheme via
    # X-Forwarded-Proto -- without trusting it here, request.scheme
    # (and so url_for(..., _external=True), used for og:image/og:url
    # below) would report "http" even on the real https:// site.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_for=1)

    restaurants = load_restaurants()
    by_slug = {slug_for(code): cfg for code, cfg in restaurants.items()}

    app.config["ORDERABILITY_SERVICE"] = service or OrderabilityService(
        cache=OrderabilityCache("orderability.db"), restaurants=restaurants
    )
    app.config["ORDER_STORE"] = order_store or OrderStore("orders.db")
    # Real file paths (not EmailVerificationStore's own ":memory:"
    # default) so a code issued by one gunicorn worker process is
    # visible to whichever worker handles the matching /verify-code
    # request -- see that module's own docstring for the real bug this
    # fixes. Tests inject their own ":memory:"-backed instances instead
    # (see tests/test_app.py's _make_client()), same reasoning as every
    # other *_store parameter here.
    app.config["EMAIL_VERIFICATION_STORE"] = email_verification_store or EmailVerificationStore("email_verification.db")
    # Reuses the SAME verification-code flow as the customer checkout
    # email (Part 27) -- see EmailVerificationStore itself, and
    # delivery_subscribers.py's own docstring for why registering is
    # just "prove you can read this address", never a real login. A
    # SEPARATE file from the customer store above -- a code issued for
    # customer checkout must never also verify a courier registration.
    app.config["DELIVERY_VERIFICATION_STORE"] = delivery_verification_store or EmailVerificationStore(
        "delivery_email_verification.db"
    )
    # Part 83: a THIRD, equally separate code-issuing store (same
    # per-purpose isolation reasoning as delivery's own above) for the
    # checkout customer_email flow -- but see VerifiedEmailStore's own
    # docstring for why the downstream FACT "this address is proven
    # real" is deliberately NOT similarly siloed: it's shared across all
    # three flows, in ORDER_STORE's own orders.db.
    app.config["CHECKOUT_VERIFICATION_STORE"] = checkout_verification_store or EmailVerificationStore(
        "checkout_email_verification.db"
    )
    app.config["VERIFIED_EMAIL_STORE"] = verified_email_store or VerifiedEmailStore("orders.db")
    # Crowd-sourced dish photos (see dish_photos.py's own docstring) --
    # same orders.db file as every other *_store above, same reasoning.
    app.config["DISH_PHOTO_STORE"] = dish_photo_store or DishPhotoStore("orders.db")
    # Where uploaded files actually land -- defaults to static/dish_photos
    # (served straight back out by Flask's own static handler) but
    # overridable so tests never write real files into this repo's own
    # static/ folder (see tests/test_app.py's _make_client()).
    app.config["DISH_PHOTO_DIR"] = Path(dish_photo_dir) if dish_photo_dir else Path(app.static_folder) / "dish_photos"
    # A photo waits here (Part 84) until the admin approves/rejects it via
    # Telegram or /admin/dish-photos -- see pending_dish_photos.py's own
    # docstring for why this is a separate store from DISH_PHOTO_STORE
    # above, not just a status column on it.
    app.config["PENDING_DISH_PHOTO_STORE"] = pending_dish_photo_store or PendingDishPhotoStore("orders.db")
    # Luni reward points (Part 87) -- see rewards.py's own docstring for
    # why this is keyed by verified email rather than any account.
    app.config["REWARD_STORE"] = reward_store or RewardStore("orders.db")
    app.config["DELIVERY_SUBSCRIBER_STORE"] = delivery_subscriber_store or DeliverySubscriberStore("orders.db")
    app.config["COMING_SOON_CLICK_STORE"] = coming_soon_click_store or ComingSoonClickStore("orders.db")
    app.config["FEEDBACK_STORE"] = feedback_store or FeedbackStore("orders.db")
    app.config["PAGE_VIEW_STORE"] = page_view_store or PageViewStore("orders.db")
    app.config["DAILY_REPORT_STORE"] = daily_report_store or DailyReportStore("orders.db")
    app.config["RATE_LIMIT_STORE"] = rate_limit_store or RateLimitStore("orders.db")
    app.config["RESTAURANTS_BY_SLUG"] = by_slug
    # Rendered link-preview cards (see /og/dish.jpg below). Overridable so
    # tests never write into the repo.
    app.config["OG_CACHE_DIR"] = Path(og_cache_dir) if og_cache_dir else Path("og_cache")

    @app.after_request
    def security_headers(response):
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        # Deliberately minimal: the SPA shell and templates use inline
        # <script>/<style>, so a script-src policy would need a nonce
        # pass first. These three lines break nothing and still stop
        # framing, plugins and <base> hijacking.
        headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'; object-src 'none'; base-uri 'self'")
        if request.is_secure:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        # Admin pages and the email confirm/cancel pages carry their
        # secret in the URL: never send it on as a Referer, never cache it.
        if request.path.startswith(("/admin", "/o/")):
            headers["Referrer-Policy"] = "no-referrer"
            headers["Cache-Control"] = "no-store"
            headers["X-Robots-Tag"] = "noindex"
        else:
            headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    def svc() -> OrderabilityService:
        return app.config["ORDERABILITY_SERVICE"]

    def store() -> OrderStore:
        return app.config["ORDER_STORE"]

    def email_verification() -> EmailVerificationStore:
        return app.config["EMAIL_VERIFICATION_STORE"]

    def delivery_verification() -> EmailVerificationStore:
        return app.config["DELIVERY_VERIFICATION_STORE"]

    def checkout_verification() -> EmailVerificationStore:
        return app.config["CHECKOUT_VERIFICATION_STORE"]

    def verified_emails() -> VerifiedEmailStore:
        return app.config["VERIFIED_EMAIL_STORE"]

    def _presented_tokens() -> dict:
        """The identity tokens this browser holds, from the
        X-Identity-Tokens header (URL-encoded JSON {email: token}), keyed
        by lower-cased address. Anything malformed is simply "no tokens"."""
        raw = request.headers.get("X-Identity-Tokens", "")
        if not raw or len(raw) > 4096:
            return {}
        try:
            data = json.loads(unquote(raw))
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k).strip().lower(): v for k, v in data.items()}

    def _token_payload(verified: bool, email: str) -> dict:
        return {"token": verified_emails().issue_token(email)} if verified else {}

    def _is_proven(email: str) -> bool:
        """True only if `email` was verified AND this request carries the
        token issued to whoever verified it. Being verified by somebody
        is not enough -- see VerifiedEmailStore's identity-proof note.
        Callers answer a failure exactly like "not verified", so nothing
        reveals whether an address is known."""
        if not verified_emails().is_verified(email):
            return False
        return verified_emails().token_valid(email, _presented_tokens().get(email.strip().lower()))

    def dish_photos() -> DishPhotoStore:
        return app.config["DISH_PHOTO_STORE"]

    def pending_dish_photos() -> PendingDishPhotoStore:
        return app.config["PENDING_DISH_PHOTO_STORE"]

    def rewards() -> RewardStore:
        return app.config["REWARD_STORE"]

    def delivery_subscribers() -> DeliverySubscriberStore:
        return app.config["DELIVERY_SUBSCRIBER_STORE"]

    def coming_soon_clicks() -> ComingSoonClickStore:
        return app.config["COMING_SOON_CLICK_STORE"]

    def feedback() -> FeedbackStore:
        return app.config["FEEDBACK_STORE"]

    def page_views() -> PageViewStore:
        return app.config["PAGE_VIEW_STORE"]

    # Part 77: (max requests, window seconds) per client IP. Generous for
    # a real person, tight enough that one client can't flood the admin's
    # Telegram, email arbitrary addresses, or pad the evening report. See
    # rate_limits.py for why this lives in SQLite, not in memory.
    RATE_LIMITS = {
        "order_create": (10, 3600),   # each order: Telegram + courier emails + customer email
        "feedback": (5, 3600),        # each one: a Telegram ping
        "courier_action": (30, 600),  # claim/release/(un)deliver: Telegram + customer email
        "track": (60, 3600),          # per event -- the evening report's page views
        "delivery_view": (60, 3600),  # counting only; the list itself is never blocked
        "dish_photo": (20, 3600),     # each one: a file write to static/dish_photos
        # Shared by all three send-code routes: each hit emails an address
        # of the caller's choosing from our sender, so a per-address
        # resend cooldown alone still let one client mail thousands of
        # different addresses. Loose enough for a shared campus NAT.
        "send_code": (20, 3600),
        "rewards_read": (300, 3600),  # Profile re-reads the balance on every visit
        "rewards_claim": (30, 3600),
    }

    def within_rate_limit(bucket: str, suffix: str = "") -> tuple[bool, int]:
        limit, window = RATE_LIMITS[bucket]
        key = f"{bucket}{':' + suffix if suffix else ''}:{request.remote_addr}"
        return app.config["RATE_LIMIT_STORE"].hit(key, limit, window)

    def rate_limited_response(bucket: str, suffix: str = ""):
        """None if this request may proceed, else the 429 to return."""
        allowed, retry_after = within_rate_limit(bucket, suffix)
        if allowed:
            return None
        return jsonify({"error": "rate_limited", "retry_after_seconds": retry_after}), 429

    def _verified_courier_email_or_error():
        """Part 88: every courier-facing action (claim/pickup/release/
        mark-delivered/mark-not-delivered) now requires a verified
        University email, the SAME ALLOWED_EMAIL_DOMAINS/VerifiedEmailStore
        gate dish-photo uploads already use (Part 85) -- real
        accountability for who's actually handling a student's food,
        not just whatever address someone types into a one-off prompt
        (the old openCourierClaimEmailSheet flow this replaces accepted
        any domain, unverified). Reads `courier_email` from the JSON
        body every one of these routes now sends. Returns (email, None)
        on success, or (None, response) for the caller to return as-is."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("courier_email") or "").strip()
        if not email:
            return None, (jsonify({"error": "courier_email_required", "message": "'courier_email' is required"}), 400)
        if not _is_allowed_customer_email(email):
            return None, (
                jsonify(
                    {
                        "error": "courier_email_required",
                        "message": f"'courier_email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}",
                    }
                ),
                400,
            )
        if not _is_proven(email):
            return None, (
                jsonify({"error": "email_not_verified", "message": "Your University email must be verified before acting as a courier"}),
                403,
            )
        return email, None

    def _award_delivery_luni(order: dict) -> None:
        """Both delivery-time rewards -- the courier's "make a delivery"
        and the customer's "make an order" -- pay out only for a real
        hand-off: claimed AND picked up (by whoever claimed it, so the
        credit goes to order["courier_email"], never to whoever merely
        tapped "Mark as delivered"), by a courier who isn't the customer
        themselves. Anything else (an unclaimed order marked delivered,
        someone delivering their own order) still records delivered_at,
        just earns nothing. Keyed by order id, so toggling delivered/
        not-delivered can never pay twice."""
        courier = (order.get("courier_email") or "").strip()
        # The University email the customer sent along (see
        # api_create_order), else customer_email itself.
        customer = (order.get("reward_email") or order.get("customer_email") or "").strip()
        if not (order.get("claimed_at") and order.get("picked_up_at") and courier):
            return
        # Case-insensitive only for the self-delivery check; the award keys
        # keep each address exactly as stored, matching how /api/rewards
        # and every other award look balances up.
        customer_addresses = {canonical_identity(order.get(f)) for f in ("reward_email", "customer_email") if order.get(f)}
        if canonical_identity(courier) in customer_addresses:
            return
        rewards().award_once(courier, f"{DELIVERY_COMPLETED}:{order['id']}", REWARD_POINTS[DELIVERY_COMPLETED])
        if customer:
            rewards().award_once(customer, f"{ORDER_PLACED}:{order['id']}", REWARD_POINTS[ORDER_PLACED])

    def _apply_expired_order_penalties() -> None:
        """-1 Luni for whoever let a claimed order fall through, once its
        delivery day is over (is_delivery_expired -- the same clock the
        Delivery screen's "Expired" section uses) with nothing delivered:

        - the courier claimed it, the admin priced it and the CUSTOMER
          never confirmed: -1 for the customer;
        - the courier claimed it, the customer confirmed, and the courier
          never picked it up: -1 for the courier.

        Not penalised: an order nobody claimed, one the admin never priced
        (status still pending/reviewing -- the customer had nothing to
        confirm), a cancelled one, and a courier who released it in time
        (claimed_at is cleared again). Idempotent -- award_once keys each
        penalty by order id -- so it's simply re-run wherever it might
        change what a person sees (their balance, the Delivery list) rather
        than on a scheduler."""
        now = datetime.now(TZINFO)
        for order in store().list_open_claimed_orders():
            if not is_delivery_expired(date.fromisoformat(order["order_date"]), now):
                continue
            if order["status"] == "awaiting_confirmation":
                customer = (order.get("reward_email") or "").strip()
                if not customer and _is_allowed_customer_email((order.get("customer_email") or "").strip()):
                    customer = order["customer_email"].strip()
                if customer:
                    rewards().award_once(customer, f"{ORDER_NOT_CONFIRMED}:{order['id']}", REWARD_POINTS[ORDER_NOT_CONFIRMED])
            elif order["status"] == "confirmed" and not order.get("picked_up_at"):
                courier = (order.get("courier_email") or "").strip()
                if courier:
                    rewards().award_once(courier, f"{COURIER_NO_SHOW}:{order['id']}", REWARD_POINTS[COURIER_NO_SHOW])

    def get_restaurant_or_404(slug: str):
        restaurant = by_slug.get(slug)
        if restaurant is None:
            abort(404, description=f"Unknown restaurant slug {slug!r}")
        return restaurant

    def _restopolis_url_for(restaurant_code: str) -> str | None:
        """Same deep-link api_create_order builds inline (see Part 38's
        own comment there for why it can only go this far, not to the
        exact date/items) -- factored out so api_claim_order can hand the
        claiming courier the same "Open on Restopolis" link every
        registered subscriber already gets at order-creation time.
        None for a restaurant code that's since vanished from
        restaurants.yaml (shouldn't happen for a real order, but an
        order is a historical record that must never 500 over it)."""
        restaurant = restaurants.get(restaurant_code)
        if restaurant is None:
            return None
        return f"{RESTOPOLIS_BASE_URL}/Menu/BtnChangeRestaurant?pRestaurantSelection={restaurant.restaurant_id}"

    # The ONLY thing that ever live-fetches from Restopolis (see
    # menu_refresh.py's own docstring) -- fixed schedule, entirely off
    # the request path. Default ON for the real app (both the local dev
    # entry point below and gunicorn's factory call in production),
    # explicitly OFF in tests (see tests/test_app.py's _make_client()),
    # which construct their own short-lived app + FakeRestopolisClient
    # per test and have no use for a background thread outliving the
    # test itself.
    if enable_menu_refresh_scheduler:
        start_menu_refresh_scheduler(svc(), list(restaurants.values()))

    # Off in tests (see tests/test_app.py's _make_client()), same
    # reasoning as enable_menu_refresh_scheduler above -- a short-lived
    # per-test app has no use for a background thread that only ever
    # wakes up once a day, and it would otherwise outlive the test
    # itself.
    if enable_daily_report_scheduler:
        start_daily_report_scheduler(page_views(), store(), app.config["DAILY_REPORT_STORE"])

    def parse_date_arg(value: str | None):
        if not value:
            abort(400, description="Missing required 'date' parameter (YYYY-MM-DD)")
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            abort(400, description=f"Invalid date {value!r}, expected YYYY-MM-DD")

    # ---------------------------------------------------------------- API

    @app.get("/api/restaurants")
    def api_restaurants():
        return jsonify(
            [{"slug": slug, "code": r.code, "name": r.name, "building": r.building} for slug, r in by_slug.items()]
        )

    @app.get("/api/restaurants/<slug>/status")
    def api_restaurant_status(slug):
        restaurant = get_restaurant_or_404(slug)
        target_date = parse_date_arg(request.args.get("date"))
        refresh = request.args.get("refresh", "").lower() in ("1", "true", "yes")
        result = svc().check_orderability(restaurant, target_date, refresh=refresh)
        return jsonify(result.to_api_dict())

    @app.get("/api/restaurants/<slug>/available-dates")
    def api_available_dates(slug):
        restaurant = get_restaurant_or_404(slug)
        count = int(request.args.get("count", 5))
        results = svc().get_next_available_dates(restaurant, count=count)
        return jsonify([r.to_api_dict() for r in results])

    def _load_flat_menu(restaurant, d):
        """Shared by the menu API and order recalculation, so both always
        see the exact same live data for this (restaurant, date)."""
        daily_menus = get_customer_menu(svc(), restaurant, d)
        return flatten_menu_items(daily_menus), daily_menus

    def _early_cutoff_violations(flat_items, selection, early_cutoff_available):
        """Names of selected items that require the earlier 08:00 cutoff
        (see menu_service.requires_early_order()) once that cutoff has
        actually passed -- [] otherwise, including whenever
        early_cutoff_available is still True (no need to even look)."""
        if early_cutoff_available:
            return []
        by_id = {it["id"]: it for it in flat_items}
        names = []
        for entry in selection:
            item = by_id.get(entry.get("id"))
            if item and item["requires_early_order"]:
                names.append(item["name"])
        return names

    @app.get("/api/restaurants/<slug>/menu/<target_date>")
    def api_menu(slug, target_date):
        restaurant = get_restaurant_or_404(slug)
        d = parse_date_arg(target_date)
        result = svc().check_orderability(restaurant, d)
        if result.status != "available":
            return jsonify({"error": "date_not_available", "status": result.status, "reason": result.reason}), 409

        flat_items, _daily_menus = _load_flat_menu(restaurant, d)
        service_time = f"{result.service_start}-{result.service_end}" if result.service_start else None
        return jsonify(
            {
                "restaurant": restaurant.name,
                "date": d.isoformat(),
                "service_time": service_time,
                "max_quantity": MAX_QUANTITY,
                "items": flat_items,
            }
        )

    @app.get("/api/restaurants/<slug>/dish-photos")
    def api_dish_photos(slug):
        get_restaurant_or_404(slug)
        return jsonify(dish_photos().photos_visible_to(slug))

    # Raster-only, sniffed from the file's own bytes rather than trusted
    # from the client-sent MIME type or filename (both spoofable) -- this
    # is the app's first arbitrary-upload endpoint, and the result is
    # served straight back out of static/, so only formats with no
    # embedded-script risk (unlike SVG) are ever written to disk.
    _DISH_PHOTO_SIGNATURES = {
        b"\xff\xd8\xff": ".jpg",
        b"\x89PNG\r\n\x1a\n": ".png",
        b"GIF87a": ".gif",
        b"GIF89a": ".gif",
    }
    MAX_DISH_PHOTO_BYTES = 8 * 1024 * 1024
    MAX_DISH_FIELD_LENGTH = 200
    PENDING_DISH_PHOTO_MAX_AGE = timedelta(days=30)

    def _sniff_dish_photo_extension(data: bytes) -> str | None:
        for signature, ext in _DISH_PHOTO_SIGNATURES.items():
            if data.startswith(signature):
                return ext
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return ".webp"
        return None

    @app.post("/api/restaurants/<slug>/dish-photos")
    def api_upload_dish_photo(slug):
        """A student submits a real photo for a real menu item straight
        from the food card's own upload tile (see static/app.js's
        food-card-photo-input) -- but NOT immediately live (Part 84): it's
        staged in PENDING_DISH_PHOTO_STORE and pinged to the admin over
        Telegram (photo attached, plus Approve/Reject/"View full card"
        buttons -- see telegram_notify.send_dish_photo_review) rather than
        published straight into DISH_PHOTO_STORE the way the very first
        version of this endpoint did. Only /admin/dish-photos/<id>/approve
        (or /replace) actually calls dish_photos().set_photo().

        Gated by a verified University email (Part 85) -- the SAME
        ALLOWED_EMAIL_DOMAINS/_is_allowed_customer_email restriction as
        the University Email Profile field, and the SAME shared
        VerifiedEmailStore checkout/courier registration already feed
        (see VerifiedEmailStore's own docstring) -- so anyone who's
        already proven a uni.lu/student.uni.lu address anywhere in the
        app can upload without proving it again, but a wholly anonymous
        visitor, or one who only ever verified a non-uni.lu address via
        checkout, cannot."""
        restaurant = get_restaurant_or_404(slug)
        limited = rate_limited_response("dish_photo")
        if limited:
            return limited
        email = (request.form.get("email") or "").strip()
        if not email:
            abort(400, description="Form must include 'email'")
        if not _is_allowed_customer_email(email):
            abort(400, description=f"'email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")
        if not _is_proven(email):
            return jsonify({"error": "email_not_verified", "message": "Your University email must be verified before uploading a photo"}), 403
        category = (request.form.get("category") or "").strip()
        name = (request.form.get("name") or "").strip()
        if not category or not name:
            abort(400, description="Form must include 'category' and 'name'")
        # Both end up in the DB, the admin pages and the Telegram ping;
        # no real menu name or category is anywhere near this long.
        if len(category) > MAX_DISH_FIELD_LENGTH or len(name) > MAX_DISH_FIELD_LENGTH:
            abort(400, description=f"'category' and 'name' must be at most {MAX_DISH_FIELD_LENGTH} characters")
        photo = request.files.get("photo")
        if photo is None or not photo.filename:
            abort(400, description="Form must include a 'photo' file")
        data = photo.read(MAX_DISH_PHOTO_BYTES + 1)
        if len(data) > MAX_DISH_PHOTO_BYTES:
            return jsonify({"error": "too_large", "message": "Photo must be smaller than 8 MB"}), 400
        clean = sanitize_dish_photo(data) if _sniff_dish_photo_extension(data) else None
        if clean is None:
            return jsonify({"error": "unsupported_type", "message": "Photo must be a JPEG, PNG, WEBP, or GIF image"}), 400

        # A RANDOM filename here, deliberately NOT the deterministic
        # sha1(slug|category|name) scheme DISH_PHOTO_STORE's own approved
        # files use (see api_upload_dish_photo's git history) -- this
        # dish may already have a live, approved photo at that exact
        # path, and a pending resubmission must never overwrite it before
        # the admin has actually approved the new one.
        filename = f"pending-{uuid.uuid4().hex}.jpg"
        photo_dir = app.config["DISH_PHOTO_DIR"]
        photo_dir.mkdir(parents=True, exist_ok=True)
        (photo_dir / filename).write_bytes(clean)
        photo_path = f"/static/dish_photos/{filename}"

        _expire_stale_pending_photos()
        pending_id = pending_dish_photos().create(slug, category, name, photo_path, email=email)
        photo_url = f"{request.host_url.rstrip('/')}{photo_path}"
        review_url, approve_url, reject_url = _admin_dish_photo_urls(pending_id)
        send_dish_photo_review(restaurant.name, category, name, photo_url, review_url, approve_url, reject_url)
        return jsonify({"status": "pending", "id": pending_id, "photo_path": photo_path})

    # An explicit route (not just Flask's own /static/<path:filename>
    # handler) so uploaded photos are always served from DISH_PHOTO_DIR --
    # which tests point at tmp_path, separate from this repo's real
    # static/ folder (see api_upload_dish_photo above and DISH_PHOTO_DIR's
    # own comment). Registered with a longer static prefix than the
    # generic static route, so Werkzeug's routing prefers this one for
    # anything under /static/dish_photos/.
    @app.get("/static/dish_photos/<path:filename>")
    def dish_photo_file(filename):
        return send_from_directory(app.config["DISH_PHOTO_DIR"], filename)

    @app.get("/api/rewards")
    def api_rewards():
        """Part 87: Profile's "Reward" row reads its Luni balance from
        here -- keyed by the verified University email already sitting
        in state.registeredEmail client-side (see rewards.py's own
        docstring). Always 0 for an unrecognized/never-awarded email,
        same "just a fact to read" shape as api_dish_photos above --
        nothing here changes state, so no verification is required to
        merely check a balance."""
        if (limited := rate_limited_response("rewards_read")) is not None:
            return limited
        email = (request.args.get("email") or "").strip()
        if not email or not _is_allowed_customer_email(email):
            abort(400, description=f"'email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")
        # Same answer as an unverified address: a balance is only shown to
        # the browser that proved the address (and never reveals whether
        # some other address is known).
        if not _is_proven(email):
            return jsonify({"error": "email_not_verified", "message": "Your University email must be verified first"}), 403
        _apply_expired_order_penalties()
        return jsonify({"points": rewards().get_points(email)})

    # Part 90: Communication email and phone number are BOTH still purely
    # client-side/localStorage fields (see saveCommunicationEmail()/
    # saveRegisteredPhone() in app.js) -- there was never a backend call
    # for "I just saved one" to hang a Luni award off of, unlike every
    # other rule (which already piggybacks on a real, existing server
    # action: verify-code, order creation, mark-delivered, dish-photo
    # approval). A tiny, tightly-scoped allowlist rather than one generic
    # "award me N points for action X" endpoint -- the server, not the
    # client, still decides both which actions exist at all and how many
    # points each is worth (REWARD_POINTS); the client only reports
    # "this one just happened", and award_once()'s per-(email, action)
    # uniqueness means the exact same request replayed any number of
    # times still only ever pays out once.
    _CLAIMABLE_REWARD_ACTIONS = {UNIVERSITY_EMAIL_VERIFIED, COMMUNICATION_EMAIL_ADDED, PHONE_NUMBER_ADDED}

    @app.post("/api/rewards/claim")
    def api_rewards_claim():
        """Idempotent "this just happened / is on file" claim, one action
        per call. The client sends the actual value the action is about,
        because Luni for a phone number or communication email must be
        anchored to a real, unique value -- otherwise anyone could claim
        both bonuses without ever entering either, or re-use one number
        across many accounts:

        - university_email_verified: no value; needs the address verified.
          Also the catch-up for anyone verified before the rule existed.
        - communication_email_added: `value` is the address (a University
          address doesn't count -- that's the identity itself).
        - phone_number_added: `value` is the number.

        Each identity earns each action once (canonical_identity folds
        plus-tags and uni.lu/student.uni.lu together), and a number or
        address earns at most once ever, whoever presents it, compared
        normalised (spaces, +352, gmail dots ...)."""
        if (limited := rate_limited_response("rewards_claim")) is not None:
            return limited
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        action = body.get("action")
        if not email or not _is_allowed_customer_email(email):
            abort(400, description=f"'email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")
        if action not in _CLAIMABLE_REWARD_ACTIONS:
            abort(400, description=f"'action' must be one of {sorted(_CLAIMABLE_REWARD_ACTIONS)}")
        if not _is_proven(email):
            return jsonify({"error": "email_not_verified", "message": "Your University email must be verified first"}), 403
        _apply_expired_order_penalties()

        if action == UNIVERSITY_EMAIL_VERIFIED:
            outcome = CLAIM_AWARDED if rewards().award_once(email, action, REWARD_POINTS[action]) else CLAIM_ALREADY_AWARDED
        else:
            raw_value = (body.get("value") or "").strip() if isinstance(body.get("value"), str) else ""
            if action == COMMUNICATION_EMAIL_ADDED:
                if not raw_value or not _is_valid_email_format(raw_value):
                    abort(400, description="'value' must be a valid email address")
                if _is_allowed_customer_email(raw_value):
                    abort(400, description="'value' must be a communication address other than a University one")
                value_key = normalize_contact_email(raw_value)
            else:
                value_key = normalize_phone(raw_value)
                if value_key is None:
                    abort(400, description="'value' must be a valid phone number")
            outcome = rewards().claim_value(email, action, value_key, REWARD_POINTS[action])
        return jsonify(
            {
                "awarded": outcome == CLAIM_AWARDED,
                "reason": None if outcome == CLAIM_AWARDED else outcome,
                "points": rewards().get_points(email),
            }
        )

    @app.post("/api/orderability/check")
    def api_orderability_check():
        body = request.get_json(force=True, silent=True) or {}
        slug = body.get("restaurant")
        date_str = body.get("date")
        if not slug or not date_str:
            abort(400, description="Body must include 'restaurant' (slug) and 'date' (YYYY-MM-DD)")
        restaurant = get_restaurant_or_404(slug)
        d = parse_date_arg(date_str)
        refresh = bool(body.get("refresh", False))
        result = svc().check_orderability(restaurant, d, refresh=refresh)
        return jsonify(result.to_api_dict())

    @app.post("/api/orders/quote")
    def api_quote_order():
        """Recalculates totals server-side from a client selection of
        {id, quantity} pairs, WITHOUT creating an order. Used by the
        frontend to show authoritative running totals as the user edits
        their selection (the frontend also computes a local preview for
        instant feedback, but this endpoint is the source of truth)."""
        body = request.get_json(force=True, silent=True) or {}
        slug = body.get("restaurant")
        date_str = body.get("date")
        selection = body.get("items") or []

        if not slug or not date_str:
            abort(400, description="Body must include 'restaurant' and 'date'")
        restaurant = get_restaurant_or_404(slug)
        d = parse_date_arg(date_str)

        flat_items, _ = _load_flat_menu(restaurant, d)
        result = svc().check_orderability(restaurant, d)
        offending = _early_cutoff_violations(flat_items, selection, result.early_cutoff.available)
        if offending:
            return jsonify({
                "error": "early_cutoff_passed",
                "message": f"These items had to be ordered before 08:00 today: {', '.join(offending)}",
                "items": offending,
            }), 409
        try:
            quote = recalculate_order(flat_items, selection)
        except OrderValidationError as exc:
            return jsonify({"error": "invalid_selection", "message": str(exc)}), 400
        return jsonify(quote)

    @app.post("/api/orders")
    def api_create_order():
        if (limited := rate_limited_response("order_create")) is not None:
            return limited
        body = request.get_json(force=True, silent=True) or {}
        slug = body.get("restaurant")
        date_str = body.get("date")
        selection = body.get("items") or []
        delivery_location = (body.get("delivery_location") or "").strip() or None
        # Required (Part 23, tightened for real Part 89 -- the frontend's
        # Building + Delivery location fields were "(optional)" text
        # labels only, never actually enforced here despite this
        # docstring already claiming otherwise): sent to the customer's
        # own confirmation, persisted (Part 30 needs to email them again
        # once a real price is on file -- see orders.py's module
        # docstring), and included in the admin's Telegram notification --
        # the ONE guaranteed way to reach this customer if a courier ends
        # up stuck with an ambiguous delivery location and nobody to ask.
        customer_email = (body.get("customer_email") or "").strip() or None
        # Optional -- an extra admin-only contact channel alongside
        # email, same courier-privacy treatment (see api_delivery_orders()
        # below, which strips both before the Delivery screen ever sees
        # them). No format enforced beyond "looks like a phone number" --
        # see static/app.js's isValidPhoneNumber() for why it's loose.
        customer_phone = (body.get("customer_phone") or "").strip() or None
        # Optional (Part 55): relayed as-is to the admin (Telegram ping,
        # /admin/orders) and echoed in the customer's own confirmation
        # email -- never parsed/acted on here, e.g. "no onion".
        customer_note = (body.get("customer_note") or "").strip() or None
        # Optional (Part 72): the customer's own app language at the
        # moment they ordered -- shown alongside the courier's own
        # language on each item in the delivery-notification email (see
        # mailer.py's _triple_dish_names()). None (not "en") when
        # missing/unrecognized, so mailer.py can tell "genuinely unknown"
        # apart from "really is English".
        customer_lang = _normalize_lang_arg(body.get("lang"))
        # Required: the student's own verified University email (Profile's
        # state.registeredEmail). This is who the order belongs to -- it's
        # what the daily order limit, the Luni credit and the abuse trail
        # all key on -- because customer_email above is only where mail is
        # sent, and can be any throwaway address that can receive a code.
        reward_email = (body.get("reward_email") or "").strip() or None

        if not slug or not date_str or not selection:
            abort(400, description="Body must include 'restaurant', 'date', and a non-empty 'items' list of {id, quantity}")
        if not delivery_location:
            abort(400, description="'delivery_location' is required")
        if not customer_email:
            abort(400, description="'customer_email' is required")
        if not _is_valid_email_format(customer_email):
            abort(400, description="'customer_email' must be a valid email address")
        # Part 83: not just well-formed -- actually proven reachable, via
        # /api/orders/email/send-code + verify-code (or any of the other
        # two flows that feed the same VerifiedEmailStore -- see its own
        # docstring). Closes the gap that let orders through with
        # syntactically-valid but obviously fake addresses like
        # "example@example.com" -- an admin/courier's only way to reach
        # a customer is worthless if it was never real to begin with.
        if not _is_proven(customer_email):
            return jsonify({"error": "email_not_verified", "message": "'customer_email' must be verified first"}), 403
        if not reward_email:
            return jsonify({
                "error": "university_email_required",
                "message": "Verify your University email in Profile before placing an order",
            }), 403
        if not _is_allowed_customer_email(reward_email):
            abort(400, description=f"'reward_email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")
        if not _is_proven(reward_email):
            return jsonify({
                "error": "university_email_not_verified",
                "message": "Your University email must be verified before placing an order",
            }), 403
        # Stored as the canonical identity ("name+x@student.uni.lu" ->
        # "name@uni.lu"): everything that limits or pays a person reads it.
        reward_email = canonical_identity(reward_email)
        if customer_note is not None and len(customer_note) > MAX_CUSTOMER_NOTE_LENGTH:
            abort(400, description=f"'customer_note' must be at most {MAX_CUSTOMER_NOTE_LENGTH} characters")

        restaurant = get_restaurant_or_404(slug)
        d = parse_date_arg(date_str)

        # Re-check orderability AND re-fetch the live menu at confirm time,
        # not just at page-load time -- both can have changed since.
        result = svc().check_orderability(restaurant, d)
        if result.status != "available":
            return jsonify({"error": "date_not_available", "status": result.status, "reason": result.reason}), 409
        # Restopolis's own signals can say available while OUR same-day
        # 13:00 cutoff has already passed (evaluate_our_delivery) -- the
        # menu stays browsable past that point (see api_menu above, never
        # gated on our_delivery), but an order must never actually be
        # created once we've told the customer it's closed.
        if not result.our_delivery.available:
            return jsonify({"error": "date_not_available", "status": "closed", "reason": "Our ordering deadline for this date has passed."}), 409

        flat_items, _ = _load_flat_menu(restaurant, d)
        offending = _early_cutoff_violations(flat_items, selection, result.early_cutoff.available)
        if offending:
            return jsonify({
                "error": "early_cutoff_passed",
                "message": f"These items had to be ordered before 08:00 today: {', '.join(offending)}",
                "items": offending,
            }), 409
        try:
            quote = recalculate_order(flat_items, selection)
        except OrderValidationError as exc:
            return jsonify({"error": "invalid_selection", "message": str(exc)}), 400

        try:
            order_id = store().create_order(
                restaurant.code,
                restaurant.name,
                d,
                quote["items"],
                delivery_location,
                customer_email,
                customer_note,
                customer_lang,
                customer_phone,
                reward_email=reward_email,
                max_orders_per_day=MAX_ORDERS_PER_DAY,
                max_order_dates=MAX_ORDER_DATES,
                today=svc().today(),
            )
        except OrderDatesLimitError:
            return jsonify({
                "error": "order_days_limit",
                "message": f"You can have orders on at most {MAX_ORDER_DATES} different days at a time",
                "max_days": MAX_ORDER_DATES,
            }), 409
        except DailyOrderLimitError:
            return jsonify({
                "error": "daily_order_limit",
                "message": f"You can place at most {MAX_ORDERS_PER_DAY} orders for the same day",
                "max_orders": MAX_ORDERS_PER_DAY,
            }), 409
        order = store().get_order(order_id)
        # No Luni here: orders cost nothing and take one request, so paying
        # on creation made them farmable. The "order" reward pays out in
        # api_mark_order_delivered instead, once a real courier delivers it.

        # Best-effort, never fails the order itself: a flaky mail API
        # or unset RESEND_API_KEY must never turn a successful order into
        # a 500 (see mailer.py's module docstring). customer_email is
        # guaranteed present at this point (validated above), unlike
        # before it became required.
        sent, error = send_order_confirmation(customer_email, order)
        order["email_sent"] = sent
        order["email_error"] = error

        # Also best-effort (Part 30): pings the admin to go place the
        # matching reservation in real Restopolis. Never blocks or fails
        # order creation -- same reasoning as the email above.
        admin_token = os.environ.get("ADMIN_TOKEN")
        admin_url = f"{request.host_url}admin/orders?token={admin_token}" if admin_token else None
        mark_reviewing_url = (
            f"{request.host_url}admin/orders/{order['id']}/mark-reviewing?token={admin_token}" if admin_token else None
        )
        # Part 38: deep-links straight to THIS restaurant on the real
        # Restopolis site (its own BtnChangeRestaurant redirect -- see
        # telegram_notify.py's send_admin_notification docstring for why
        # it can only go this far, not to the exact date/items).
        restopolis_url = _restopolis_url_for(restaurant.code)
        cancel_url = f"{request.host_url}admin/orders/{order['id']}/cancel?token={admin_token}" if admin_token else None
        send_admin_notification(
            order,
            admin_url=admin_url,
            mark_reviewing_url=mark_reviewing_url,
            restopolis_url=restopolis_url,
            cancel_url=cancel_url,
        )

        # Part 52+: emails every registered courier the moment the order
        # is placed (not gated on admin confirmation -- a courier can
        # start planning the pickup right away). Best-effort per address,
        # same reasoning as every other notification above: one failed
        # send must never fail the order, or stop the rest from going out
        # -- wrapped here (unlike send_order_confirmation/
        # send_admin_notification above) because this one loops over an
        # unbounded, admin-uncontrolled list of addresses, so a single
        # unexpected exception must not take down order creation OR skip
        # notifying the remaining couriers.
        for courier_email, courier_lang in delivery_subscribers().list_subscribers():
            try:
                send_delivery_notification(courier_email, order, restopolis_url=restopolis_url, courier_lang=courier_lang)
            except Exception:  # noqa: BLE001 -- see comment above: must never fail the order or the remaining sends
                logging.getLogger("uniresto.mailer").warning(
                    "[MAIL] failed to notify courier %s about order #%s", courier_email, order["id"], exc_info=True
                )

        return jsonify(order), 201

    @app.get("/api/orders/<int:order_id>")
    def api_get_order(order_id):
        """Re-fetches one previously confirmed order by id -- used by Order
        History (Part 50), which itself only persists a list of order ids
        client-side (no accounts to scope a server-side list by, see
        README.md Part 46/49's same reasoning for Cart/Favorites) and
        re-fetches each order's current, authoritative record from here
        rather than trusting anything cached in the browser."""
        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order with id {order_id}")
        # Unauthenticated, and order ids are sequential -- anyone could
        # walk /api/orders/1..N. Order History never reads these fields
        # (the customer already knows their own email/phone), so strip
        # every contact detail, same treatment as api_delivery_orders.
        for field in PRIVATE_ORDER_FIELDS:
            order.pop(field, None)
        return jsonify(order)

    # ------------------------------------------------------ Email verification

    @app.post("/api/email/send-code")
    def api_email_send_code():
        """Sends a fresh 6-digit code to `email` (Part 27) -- issued/
        stored ONLY if the send itself actually succeeded, so a delivery
        failure never leaves a code silently un-sendable-but-verifiable,
        and never blocks an immediate retry either (see
        EmailVerificationStore.issue()'s docstring)."""
        if (limited := rate_limited_response("send_code")) is not None:
            return limited
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        if not email:
            abort(400, description="Body must include 'email'")
        if not _is_allowed_customer_email(email):
            abort(400, description=f"'email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")

        remaining = email_verification().seconds_until_resend_allowed(email)
        if remaining > 0:
            return jsonify({"sent": False, "error": "rate_limited", "retry_after_seconds": remaining}), 429

        code = generate_verification_code()
        sent, error = send_verification_code(email, code)
        if sent:
            email_verification().issue(email, code)
        return jsonify({"sent": sent, "error": error})

    @app.post("/api/email/verify-code")
    def api_email_verify_code():
        """Checks `code` against whatever was last issued to `email` (see
        EmailVerificationStore.verify()) -- a one-time check: correct or
        not, the entry is consumed/invalidated so it can't be replayed.
        On success, also marks the address in VerifiedEmailStore (Part
        83) -- proving control of it here is just as good as proving it
        via checkout's own flow, so a student who already verified their
        University email never has to prove it again just to order."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        code = (body.get("code") or "").strip()
        if not email or not code:
            abort(400, description="Body must include 'email' and 'code'")
        verified, reason = email_verification().verify(email, code)
        if verified:
            verified_emails().mark_verified(email)
            # Part 90: "Registration via uni.lu email" -- specifically THIS
            # flow (Profile's own University Email field), not the
            # checkout/courier ones below that share the same
            # VerifiedEmailStore fact but aren't "registering" anything.
            rewards().award_once(email, UNIVERSITY_EMAIL_VERIFIED, REWARD_POINTS[UNIVERSITY_EMAIL_VERIFIED])
        return jsonify({"verified": verified, "reason": reason, **_token_payload(verified, email)})

    @app.post("/api/orders/email/send-code")
    def api_orders_email_send_code():
        """Part 83: same verification-code flow as /api/email/send-code
        above (a SEPARATE EmailVerificationStore instance -- see that
        route's own reasoning), for checkout's customer_email. NOT
        restricted to a uni.lu domain (checkout itself never has been --
        see _is_valid_email_format's docstring on api_create_order): the
        point here is only proving the address is real and reachable,
        the same reason customer_email became required in the first
        place, not proving University affiliation."""
        if (limited := rate_limited_response("send_code")) is not None:
            return limited
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        if not email:
            abort(400, description="Body must include 'email'")
        if not _is_valid_email_format(email):
            abort(400, description="'email' must be a valid email address")

        remaining = checkout_verification().seconds_until_resend_allowed(email)
        if remaining > 0:
            return jsonify({"sent": False, "error": "rate_limited", "retry_after_seconds": remaining}), 429

        code = generate_verification_code()
        sent, error = send_verification_code(email, code)
        if sent:
            checkout_verification().issue(email, code)
        return jsonify({"sent": sent, "error": error})

    @app.post("/api/orders/email/verify-code")
    def api_orders_email_verify_code():
        """On a correct code, marks the address in VerifiedEmailStore
        (Part 83) -- what api_create_order actually checks before
        letting an order through with this customer_email; on an
        incorrect/expired one, nothing is persisted."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        code = (body.get("code") or "").strip()
        if not email or not code:
            abort(400, description="Body must include 'email' and 'code'")
        verified, reason = checkout_verification().verify(email, code)
        if verified:
            verified_emails().mark_verified(email)
        return jsonify({"verified": verified, "reason": reason, **_token_payload(verified, email)})

    # ---------------------------------------------------- Delivery (Part 52+)

    @app.post("/api/delivery/register/send-code")
    def api_delivery_register_send_code():
        """Same verification-code flow as /api/email/send-code above (a
        SEPARATE EmailVerificationStore instance -- a code issued for
        customer checkout must never also verify a courier registration,
        or vice versa), for a courier proving they can read mail at the
        address they want order notifications sent to. Deliberately NOT
        restricted to a uni.lu domain (Part 61) -- unlike the University
        Email (which proves campus affiliation and stays uni.lu-only),
        this is just the delivery destination, and a personal address is
        actually the MORE reliable choice here: university mail systems
        sometimes reject automated mail from this app's sender. Still
        code-verified, just not domain-gated."""
        if (limited := rate_limited_response("send_code")) is not None:
            return limited
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        if not email:
            abort(400, description="Body must include 'email'")
        if not _is_valid_email_format(email):
            abort(400, description="'email' must be a valid email address")

        remaining = delivery_verification().seconds_until_resend_allowed(email)
        if remaining > 0:
            return jsonify({"sent": False, "error": "rate_limited", "retry_after_seconds": remaining}), 429

        code = generate_verification_code()
        sent, error = send_verification_code(email, code)
        if sent:
            delivery_verification().issue(email, code)
        return jsonify({"sent": sent, "error": error})

    @app.post("/api/delivery/register/verify-code")
    def api_delivery_register_verify_code():
        """On a correct code, persists the address in DeliverySubscriberStore
        (idempotent -- registering twice is fine) so every future order
        notifies it, and marks it in VerifiedEmailStore (Part 83) --
        proving control of it here is just as good as proving it via
        checkout's own flow; on an incorrect/expired one, neither is
        persisted."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        code = (body.get("code") or "").strip()
        if not email or not code:
            abort(400, description="Body must include 'email' and 'code'")
        verified, reason = delivery_verification().verify(email, code)
        if verified:
            delivery_subscribers().add(email, _normalize_lang_arg(body.get("lang")) or "en")
            verified_emails().mark_verified(email)
        return jsonify({"verified": verified, "reason": reason, **_token_payload(verified, email)})

    @app.post("/api/delivery/register/quick")
    def api_delivery_register_quick():
        """Registers a courier address with NO code round-trip, for the
        one case where that's a reasonable shortcut rather than a real
        gap: the frontend only ever calls this with the SAME address
        already sitting in this browser's own state.registeredEmail --
        which itself only gets set there after that address completed
        the real customer send-code/verify-code flow (Part 25/27), on
        this same device -- already marked in VerifiedEmailStore by that
        earlier verify-code call, so there's nothing new to mark here.
        Re-proving control of an address this device already proved it
        can read is a needless second code, not stronger security. Still
        domain-checked (courier eligibility, same as every other
        delivery-registration path), just not code-checked."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        if not email:
            abort(400, description="Body must include 'email'")
        if not _is_allowed_customer_email(email):
            abort(400, description=f"'email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")
        # The docstring's premise, actually enforced: without this, anyone
        # could subscribe any uni.lu address to every future order email.
        if not _is_proven(email):
            return jsonify({"error": "email_not_verified", "message": "Your University email must be verified first"}), 403
        delivery_subscribers().add(email, _normalize_lang_arg(body.get("lang")) or "en")
        return jsonify({"registered": True})

    @app.get("/api/delivery/orders")
    def api_delivery_orders():
        """Real orders for the in-app Delivery screen (Part 52+) -- every
        order regardless of status, newest first (see
        OrderStore.list_recent_orders()'s own docstring for why a
        cancelled one is still included, for the screen's own "Closed"
        section). Deliberately strips customer_email AND customer_phone
        from every order before returning: a courier needs to know WHERE
        to bring the order, never who placed it or how to contact them
        directly -- that's the admin's job (Telegram notification), not
        a random courier's. Viewing this list needs no
        registration/verification at all (see delivery_subscribers.py's
        own docstring) -- registering only controls whether an address
        gets emailed."""
        # Part 74: a real Delivery-screen visit for the evening report --
        # counted only within the rate limit (Part 77), so a refresh loop
        # can't pad the report; the list itself is always served.
        if within_rate_limit("delivery_view")[0]:
            page_views().record("delivery")
        now = datetime.now(TZINFO)
        # Only the last DELIVERY_LIST_DAYS days: this list is public, and
        # an ever-growing history of rooms food was brought to is not
        # something any courier needs.
        oldest = now - timedelta(days=DELIVERY_LIST_DAYS)
        _apply_expired_order_penalties()
        orders = [o for o in store().list_recent_orders() if _as_utc(o["created_at"]) >= oldest]
        for order in orders:
            # Part 81: the claiming courier's own contact info is exactly
            # as private from every OTHER courier browsing this screen as
            # the customer's is -- nothing here needs to show it, and
            # nothing should.
            for field in PRIVATE_ORDER_FIELDS:
                order.pop(field, None)
            # Never shown on the Delivery screen, and free text ("call me
            # at ...", "I'm in room ...") is exactly where contact details
            # would slip in.
            order.pop("customer_note", None)
            # Once there's nothing left to deliver, the building is enough
            # for the card's heading -- the room/free-text half isn't
            # needed by anyone browsing this list anymore.
            if order.get("delivered_at") or order["status"] == "cancelled":
                order["delivery_location"] = _building_only(order.get("delivery_location"))
            # Part 76: the Delivery screen's "Expired" section reads this
            # instead of comparing dates on the courier's own device.
            order["expired"] = is_delivery_expired(date.fromisoformat(order["order_date"]), now)
        return jsonify(orders)

    @app.post("/api/orders/<int:order_id>/claim")
    def api_claim_order(order_id):
        """Courier-facing (Part 75), gated by a verified University email
        (Part 88, courier_email required Part 81 -- see
        _verified_courier_email_or_error's own docstring for why this
        replaced the old any-domain/unverified prompt). `courier_email`
        is still the one and only way this specific claimant gets the
        order's own description (dish names, in their own language) back,
        and a claim with no way to reach the claimant is exactly the gap
        that left a real courier stuck not knowing what they'd taken on.
        Only the courier who actually WINS the claim (see
        OrderStore.mark_claimed()'s own docstring on why a second tap
        never re-fires this) triggers the admin Telegram ping, the
        courier's own order-description email, and -- if the customer
        left an email -- the "order accepted" email -- all best-effort,
        same reasoning as every other notification in this app: a flaky
        send must never fail the claim itself."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        courier_email, error = _verified_courier_email_or_error()
        if error:
            return error
        courier_lang = _normalize_lang_arg((request.get_json(force=True, silent=True) or {}).get("lang"))
        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order #{order_id}")
        # The UI never offers "Take this delivery" on these, but the route
        # is ungated -- a stale tab or a direct call must not email a
        # customer "order accepted" about an order that was called off or
        # is already in their hands.
        if order["status"] == "cancelled" or order["delivered_at"]:
            return jsonify({"error": "not_claimable", "status": order["status"], "delivered": bool(order["delivered_at"])}), 409
        newly_claimed = store().mark_claimed(order_id, courier_email=courier_email, courier_lang=courier_lang)
        if newly_claimed:
            send_order_claimed_notification(order, admin_url=_admin_orders_url())
            send_delivery_notification(
                courier_email, order, restopolis_url=_restopolis_url_for(order["restaurant_code"]), courier_lang=courier_lang or "en"
            )
            # At most once per order (Part 76): a release + re-claim
            # must never email the customer again for the SAME claim.
            if order.get("customer_email") and store().mark_accepted_emailed(order_id):
                send_order_accepted(order["customer_email"], order)
        return jsonify({"claimed": True, "already_claimed": not newly_claimed})

    @app.post("/api/orders/<int:order_id>/picked-up")
    def api_mark_picked_up(order_id):
        """Part 81: a courier confirms they've physically grabbed the food
        from the canteen counter -- a separate, later fact than claiming
        the job (see OrderStore.mark_picked_up()'s own docstring). Gated
        by a verified University email (Part 88) same as claim above --
        no re-verification against the ORIGINAL claimant's own
        courier_email though: this app has no accounts, so "some other
        verified student" is the same trust level the Delivery screen
        already gives everyone claiming/releasing/marking-delivered.
        Only the tap that actually wins (claimed but not yet picked up)
        emails the customer "on its way" -- best-effort, same as every
        other notification here."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        _courier_email, error = _verified_courier_email_or_error()
        if error:
            return error
        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order #{order_id}")
        newly_picked_up = store().mark_picked_up(order_id)
        if not newly_picked_up:
            return jsonify({"error": "not_pickupable"}), 409
        if order.get("customer_email") and store().mark_on_way_emailed(order_id):
            send_order_out_for_delivery(order["customer_email"], order)
        return jsonify({"picked_up": True})

    @app.post("/api/orders/<int:order_id>/unclaim")
    def api_unclaim_order(order_id):
        """Part 76: "I can't deliver this after all" -- the courier who
        took it gives it back, so it shows "Take this delivery" again for
        everyone else (only possible before pickup -- see
        OrderStore.mark_unclaimed()'s own docstring). Gated by a verified
        University email (Part 88), same reasoning as picked-up above.
        Pings the admin (who was told it was claimed); the customer is
        NOT emailed -- they were told it was accepted once, and the next
        courier to take it is what actually matters to them."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        _courier_email, error = _verified_courier_email_or_error()
        if error:
            return error
        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order #{order_id}")
        if not store().mark_unclaimed(order_id):
            return jsonify({"error": "not_claimed"}), 409
        send_order_released_notification(order, admin_url=_admin_orders_url())
        return jsonify({"claimed": False})

    @app.post("/api/orders/<int:order_id>/mark-delivered")
    def api_mark_order_delivered(order_id):
        """Courier-facing (Part 73), gated by a verified University email
        (Part 88) same as every other courier action above -- same trust
        level otherwise: any verified student can confirm it, same as
        everyone already seeing every order on the Delivery screen."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        _courier_email, error = _verified_courier_email_or_error()
        if error:
            return error
        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order #{order_id}")
        if order["status"] == "cancelled":
            return jsonify({"error": "not_deliverable", "status": "cancelled"}), 409
        store().mark_delivered(order_id)
        _award_delivery_luni(order)
        return jsonify({"delivered": True})

    @app.post("/api/orders/<int:order_id>/mark-not-delivered")
    def api_mark_order_not_delivered(order_id):
        """Undoes the above -- a courier tapping the wrong order, or too
        early, must be able to reverse it. Same Part 88 gate."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        _courier_email, error = _verified_courier_email_or_error()
        if error:
            return error
        if not store().mark_not_delivered(order_id):
            abort(404, description=f"No order #{order_id}")
        return jsonify({"delivered": False})

    # The exact 4 "coming soon" cards static/app.js's own
    # COMING_SOON_LOCATIONS list shows on the restaurant list (Part 66) --
    # kept here too (rather than trusting whatever string the client
    # sends) so this can't be used to log arbitrary text.
    COMING_SOON_LOCATIONS = ("Food House", "Food Café", "Food Lab", "Food Zone")

    @app.post("/api/coming-soon/click")
    def api_coming_soon_click():
        """Records a tap on one of the not-yet-real restaurant cards (Part
        69) -- a raw interest count (see coming_soon_clicks.py's own
        docstring for why it's never deduplicated), visible to the admin
        at /admin/coming-soon-clicks. Never fails loudly on the frontend
        either way -- this is a best-effort signal, not something that
        should ever block or error out the "opening soon" toast it fires
        alongside."""
        body = request.get_json(force=True, silent=True) or {}
        location = (body.get("location") or "").strip()
        if location not in COMING_SOON_LOCATIONS:
            abort(400, description=f"'location' must be one of {', '.join(COMING_SOON_LOCATIONS)}")
        coming_soon_clicks().record(location)
        return jsonify({"recorded": True})

    # Page views only the CLIENT can tell apart from noise (Part 74):
    # "home" -- GET / is also fetched by link-preview crawlers; "menu" --
    # the date picker prefetches every orderable day's menu in the
    # background, so counting at api_menu() inflated one real view into
    # ~5. "delivery" stays server-side in api_delivery_orders(), which is
    # only ever called when that screen actually renders.
    CLIENT_TRACKED_EVENTS = ("home", "menu")

    @app.post("/api/track/<event>")
    def api_track(event):
        """Fired by static/app.js -- "home" once from init(), "menu" from
        selectDate() once a day's menu has actually loaded for someone
        who picked it. Best-effort on the client: never blocks anything.

        `source` (Part 78, "home" only in practice -- see init()) is
        whatever ?src= the URL was opened with, e.g. a QR code's own
        label -- an open string, truncated rather than validated against
        a fixed list, since a new QR/flyer needs no code change here."""
        if event not in CLIENT_TRACKED_EVENTS:
            abort(404)
        if (limited := rate_limited_response("track", event)) is not None:
            return limited
        body = request.get_json(force=True, silent=True) or {}
        source = (body.get("source") or "").strip()[:MAX_SOURCE_LENGTH] or None
        page_views().record(event, source=source)
        return jsonify({"recorded": True})

    @app.post("/api/feedback")
    def api_feedback():
        """The Profile screen's free-text "Send feedback" field (Part 71)
        -- always stored (visible at /admin/feedback) and, best-effort,
        pinged to the admin over Telegram the same way a new order is
        (never fails the request if that ping fails, same reasoning as
        send_admin_notification's own call site above)."""
        if (limited := rate_limited_response("feedback")) is not None:
            return limited
        body = request.get_json(force=True, silent=True) or {}
        message = (body.get("message") or "").strip()
        contact_email = (body.get("email") or "").strip() or None
        if not message:
            abort(400, description="'message' must not be empty")
        if len(message) > MAX_FEEDBACK_LENGTH:
            abort(400, description=f"'message' must be at most {MAX_FEEDBACK_LENGTH} characters")
        if contact_email is not None and not _is_valid_email_format(contact_email):
            abort(400, description="'email' is not a valid email address")
        feedback().record(message, contact_email)
        admin_token = os.environ.get("ADMIN_TOKEN")
        admin_url = f"{request.host_url}admin/feedback?token={admin_token}" if admin_token else None
        send_feedback_notification(message, contact_email, admin_url=admin_url)
        return jsonify({"recorded": True})

    @app.post("/api/smart-lunch")
    def api_smart_lunch():
        """Deterministic Smart Lunch search (Part 51) over the live menu --
        never a ranking, never a fabricated combination; see
        orderability_engine/smart_lunch.py's module docstring for the full
        constraint-relaxation algorithm this just validates input for and
        delegates to."""
        body = request.get_json(force=True, silent=True) or {}
        slug = body.get("restaurant")
        date_str = body.get("date")
        if not slug or not date_str:
            abort(400, description="Body must include 'restaurant' and 'date'")

        restaurant = get_restaurant_or_404(slug)
        d = parse_date_arg(date_str)

        result = svc().check_orderability(restaurant, d)
        if result.status != "available":
            return jsonify({"error": "date_not_available", "status": result.status, "reason": result.reason}), 409

        dietary_preferences = body.get("dietary_preferences") or []
        if not isinstance(dietary_preferences, list) or any(v not in ("vegetarian", "vegan") for v in dietary_preferences):
            abort(400, description="'dietary_preferences' must be a list containing only 'vegetarian'/'vegan'")

        excluded_allergens = body.get("excluded_allergens") or []
        if not isinstance(excluded_allergens, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in excluded_allergens):
            abort(400, description="'excluded_allergens' must be a list of integer allergen codes")

        meal_preference = body.get("meal_preference")
        if meal_preference is not None and meal_preference not in TIER_ORDER:
            abort(400, description=f"'meal_preference' must be one of {sorted(TIER_ORDER)}")

        def optional_number(key):
            value = body.get(key)
            if value is None:
                return None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                abort(400, description=f"'{key}' must be a number")
            return value

        max_price = optional_number("max_price")
        min_weight = optional_number("min_weight")
        max_calories = optional_number("max_calories")

        flat_items, _ = _load_flat_menu(restaurant, d)
        outcome = find_smart_lunch(
            flat_items,
            {
                "dietary_preferences": dietary_preferences,
                "excluded_allergens": excluded_allergens,
                "meal_preference": meal_preference,
                "max_price": max_price,
                "min_weight": min_weight,
                "max_calories": max_calories,
            },
        )
        return jsonify(outcome)

    # -------------------------------------------------------------- Admin

    @app.get("/admin/orderability")
    def admin_orderability():
        rows = []
        today = svc().today()
        for restaurant in by_slug.values():
            for offset in range(ADMIN_LOOKAHEAD_DAYS):
                d = today + timedelta(days=offset)
                result = svc().check_orderability(restaurant, d)
                rows.append(result)
        return render_template("admin.html", rows=rows, status_values=STATUS_VALUES)

    @app.get("/admin/orders")
    def admin_orders():
        """Part 30: lists orders an admin still needs to (1) place in real
        Restopolis and record a price for ('pending' and 'reviewing' --
        see OrderStore.mark_reviewing(), Part 37), or (2) has already sent
        to the customer and is waiting on ('awaiting_confirmation').
        Gated by ADMIN_TOKEN (see _is_admin_authorized()) -- unlike
        /admin/orderability above, this page can trigger a real customer
        email and change order status, so it's not left wide open."""
        if not _is_admin_authorized():
            abort(404)
        return render_template(
            "admin_orders.html",
            pending=store().list_orders_by_status("pending"),
            reviewing=store().list_orders_by_status("reviewing"),
            awaiting=store().list_orders_by_status("awaiting_confirmation"),
            token=request.args.get("token"),
        )

    @app.get("/admin/coming-soon-clicks")
    def admin_coming_soon_clicks():
        """Interest signal for the coming-soon restaurant cards (Part 69) --
        gated the same way as /admin/orders since it's accumulated visitor
        behavior data, not a public read-only debug view like
        /admin/orderability above."""
        if not _is_admin_authorized():
            abort(404)
        return render_template(
            "admin_coming_soon_clicks.html", counts=coming_soon_clicks().counts(), token=request.args.get("token")
        )

    @app.get("/admin/sources")
    def admin_sources():
        """Part 78: how many app opens each ?src= label (e.g. a printed
        flyer's own QR code) brought in, all-time -- gated the same way
        as /admin/coming-soon-clicks above."""
        if not _is_admin_authorized():
            abort(404)
        return render_template(
            "admin_sources.html", counts=page_views().source_counts("home"), token=request.args.get("token")
        )

    @app.get("/admin/feedback")
    def admin_feedback():
        """Free-text feedback inbox (Part 71) -- gated the same way as
        /admin/orders since it's user-submitted content, not a public
        read-only debug view."""
        if not _is_admin_authorized():
            abort(404)
        return render_template("admin_feedback.html", entries=feedback().list_recent(), token=request.args.get("token"))

    @app.get("/admin/dish-photos")
    def admin_dish_photos():
        """Part 84: every pending student-submitted dish photo, oldest
        first -- the same queue send_dish_photo_review's Telegram ping is
        drawn from, for browsing/deciding from a browser instead."""
        if not _is_admin_authorized():
            abort(404)
        _expire_stale_pending_photos()
        return render_template("admin_dish_photos.html", entries=pending_dish_photos().all_pending(), token=request.args.get("token"))

    @app.get("/admin/dish-photos/<int:pending_id>")
    def admin_dish_photo_review(pending_id):
        """Part 84: "View full card" from the Telegram ping -- a bigger
        look at the exact same photo/dish before deciding. Already-
        decided (or never-existed) ids get a friendly explanation, same
        as /o/<id>/confirm|cancel's own "not valid anymore" page, rather
        than a bare 404."""
        if not _is_admin_authorized():
            abort(404)
        entry = pending_dish_photos().get(pending_id)
        if entry is None:
            return render_template(
                "order_action.html",
                icon="✅",
                title="Nothing left to review here",
                message="This photo was already approved or rejected (or never existed).",
            )
        return render_template("dish_photo_review.html", entry=entry, token=request.args.get("token"))

    def _delete_dish_photo_file(photo_path: str) -> None:
        (app.config["DISH_PHOTO_DIR"] / Path(photo_path).name).unlink(missing_ok=True)

    def _expire_stale_pending_photos() -> None:
        """Submissions nobody decided on within PENDING_DISH_PHOTO_MAX_AGE
        are dropped, file and row -- run on every new upload and every
        visit to the review queue, so there's no scheduler to maintain."""
        cutoff = datetime.now(TZINFO) - PENDING_DISH_PHOTO_MAX_AGE
        for stale in pending_dish_photos().pop_submitted_before(cutoff):
            _delete_dish_photo_file(stale["photo_path"])

    def _discard_other_pending_submissions(entry: dict) -> None:
        """Part 86: `entry`'s dish just got a real decision (approve or
        replace) -- any OTHER still-pending submission for that exact
        dish is now moot (a dish only ever shows one live photo), so it's
        discarded here too rather than sitting in the review queue, and
        on disk, forever undecided."""
        others = pending_dish_photos().pop_other_pending_for_dish(entry["slug"], entry["category"], entry["name"], entry["id"])
        for other in others:
            _delete_dish_photo_file(other["photo_path"])

    def _award_dish_photo_luni(entry: dict) -> None:
        """Part 90: +1 Luni to whoever SUBMITTED this photo (entry["email"],
        set at upload time -- see api_upload_dish_photo), the moment it
        actually goes live -- whether that's a plain approve of their own
        photo, or the admin replacing it with their own and publishing
        that instead (still the original submitter's credit: their
        submission is what prompted a real photo to end up on this dish
        either way). None for a pre-Part-90 row this old migration never
        backfilled an email onto -- never crashes, just nothing to credit."""
        if entry.get("email"):
            rewards().award_once(entry["email"], f"{DISH_PHOTO_APPROVED}:{entry['id']}", REWARD_POINTS[DISH_PHOTO_APPROVED])

    def _dish_photo_decision_page(pending_id: int, decision: str):
        """GET on an approve/reject link (the Telegram buttons): shows the
        button that actually does it, instead of doing it -- anything that
        prefetches the URL (a link preview, a browser, a scanner) must
        never publish or delete a photo."""
        if not _is_admin_authorized():
            abort(404)
        entry = pending_dish_photos().get(pending_id)
        if entry is None:
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="This link isn't valid anymore",
                message="This photo was already approved or rejected.",
            )
        approve = decision == "approve"
        return render_template(
            "order_action.html",
            icon="✅" if approve else "❌",
            title=f"{'Approve' if approve else 'Reject'} this photo?",
            message=f"{entry['name']} ({entry['category']})",
            form_action=f"/admin/dish-photos/{pending_id}/{decision}",
            form_fields={"token": request.args.get("token", "")},
            form_button="Approve photo" if approve else "Reject photo",
            form_danger=not approve,
        )

    @app.get("/admin/dish-photos/<int:pending_id>/approve")
    def admin_approve_dish_photo_page(pending_id):
        return _dish_photo_decision_page(pending_id, "approve")

    @app.get("/admin/dish-photos/<int:pending_id>/reject")
    def admin_reject_dish_photo_page(pending_id):
        return _dish_photo_decision_page(pending_id, "reject")

    @app.post("/admin/dish-photos/<int:pending_id>/approve")
    def admin_approve_dish_photo(pending_id):
        """Part 84: the "✅ Approve" Telegram button (plain URL, same
        no-webhook reasoning as admin_mark_order_reviewing below) --
        publishes the pending photo into DISH_PHOTO_STORE (now live for
        every student browsing this dish) and removes it from the
        pending queue. Whatever photo this dish had live BEFORE this one
        (Part 86) is now unreferenced anywhere, so its file is deleted --
        a dish never keeps more than one photo on disk, no matter how
        many times it gets re-approved."""
        if not _is_admin_authorized():
            abort(404)
        entry = pending_dish_photos().get(pending_id)
        if entry is None:
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="This link isn't valid anymore",
                message="This photo was already approved or rejected.",
            )
        previous_photo_path = dish_photos().set_photo(entry["slug"], entry["category"], entry["name"], entry["photo_path"])
        if previous_photo_path and previous_photo_path != entry["photo_path"]:
            _delete_dish_photo_file(previous_photo_path)
        _discard_other_pending_submissions(entry)
        _award_dish_photo_luni(entry)
        pending_dish_photos().delete(pending_id)
        return render_template(
            "order_action.html",
            icon="✅",
            title="Photo approved",
            message=f"{entry['name']} now shows this photo for every student.",
        )

    @app.post("/admin/dish-photos/<int:pending_id>/reject")
    def admin_reject_dish_photo(pending_id):
        """Part 84: the "❌ Reject" Telegram button -- discards the
        submission (file and pending row both). Never published, and
        since this app has no accounts there's no submitter to notify;
        the dish's card simply goes back to showing the plain "Add dish
        pic here!" placeholder until someone submits another photo."""
        if not _is_admin_authorized():
            abort(404)
        entry = pending_dish_photos().get(pending_id)
        if entry is None:
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="This link isn't valid anymore",
                message="This photo was already approved or rejected.",
            )
        _delete_dish_photo_file(entry["photo_path"])
        pending_dish_photos().delete(pending_id)
        return render_template(
            "order_action.html",
            icon="❌",
            title="Photo rejected",
            message=f"{entry['name']} is back to showing the placeholder until a new photo comes in.",
        )

    @app.post("/admin/dish-photos/<int:pending_id>/replace")
    def admin_replace_dish_photo(pending_id):
        """From the "View full card" page (Part 84): lets the admin publish
        their OWN photo for this dish instead of the student's submission
        -- e.g. it's blurry, or of the wrong dish entirely. Publishes
        straight to DISH_PHOTO_STORE (no further review -- the admin IS
        the reviewer here) and discards the original submission (file and
        pending row both), same cleanup as reject."""
        if not _is_admin_authorized():
            abort(404)
        entry = pending_dish_photos().get(pending_id)
        if entry is None:
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="This link isn't valid anymore",
                message="This photo was already approved or rejected.",
            )
        photo = request.files.get("photo")
        if photo is None or not photo.filename:
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="No photo given",
                message="Choose a file before submitting.",
            )
        data = photo.read(MAX_DISH_PHOTO_BYTES + 1)
        if len(data) > MAX_DISH_PHOTO_BYTES:
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="That photo is too large",
                message="Photos must be smaller than 8 MB.",
            )
        clean = sanitize_dish_photo(data) if _sniff_dish_photo_extension(data) else None
        if clean is None:
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="Unsupported file type",
                message="Photos must be a JPEG, PNG, WEBP, or GIF image.",
            )

        photo_dir = app.config["DISH_PHOTO_DIR"]
        photo_dir.mkdir(parents=True, exist_ok=True)
        filename = f"admin-{uuid.uuid4().hex}.jpg"
        (photo_dir / filename).write_bytes(clean)
        new_photo_path = f"/static/dish_photos/{filename}"
        previous_photo_path = dish_photos().set_photo(entry["slug"], entry["category"], entry["name"], new_photo_path)
        if previous_photo_path and previous_photo_path != new_photo_path:
            _delete_dish_photo_file(previous_photo_path)

        _delete_dish_photo_file(entry["photo_path"])
        _discard_other_pending_submissions(entry)
        _award_dish_photo_luni(entry)
        pending_dish_photos().delete(pending_id)
        return render_template(
            "order_action.html",
            icon="✅",
            title="Your photo is published",
            message=f"{entry['name']} now shows the photo you just uploaded.",
        )

    @app.get("/admin/orders/<int:order_id>/mark-reviewing")
    def admin_mark_order_reviewing(order_id):
        """Part 37: the link on the Telegram admin ping (a plain URL
        button, see telegram_notify.py -- no webhook needed). GET, not
        POST, since Telegram's inline URL buttons can only open a link;
        same ADMIN_TOKEN gate as the rest of this page, and same
        "state-changing GET" pattern this app already uses for the
        customer's /o/<id>/confirm|cancel email links below."""
        if not _is_admin_authorized():
            abort(404)
        store().mark_reviewing(order_id)
        return redirect(f"/admin/orders?token={request.args.get('token', '')}")

    @app.get("/admin/orders/<int:order_id>/cancel")
    def admin_cancel_order_page(order_id):
        """The Telegram "Remove this order" button (a plain URL, so it can
        only GET): asks first instead of cancelling, so a link preview or
        a stray tap never removes an order -- the button on this page is
        what POSTs."""
        if not _is_admin_authorized():
            abort(404)
        order = store().get_order(order_id)
        if order is None or order["status"] not in ("pending", "reviewing", "awaiting_confirmation"):
            return render_template(
                "order_action.html",
                icon="⚠️",
                title="This order can't be removed anymore",
                message="It doesn't exist, or it's already confirmed or cancelled.",
            )
        return render_template(
            "order_action.html",
            icon="🗑",
            title=f"Remove order #{order_id}?",
            message=f"{order['restaurant_name']} · {order['order_date']} · {sum(i['quantity'] for i in order['items'])} portions. This can't be undone.",
            form_action=f"/admin/orders/{order_id}/cancel",
            form_fields={"token": request.args.get("token", "")},
            form_button="Remove order",
            form_danger=True,
        )

    @app.post("/admin/orders/<int:order_id>/cancel")
    def admin_cancel_order(order_id):
        """Lets the admin cancel an order from the /admin/orders panel --
        e.g. spam or a test order, which otherwise sat there (and on the
        public Delivery list) forever. A cancelled order costs nobody
        Luni, frees the customer's daily-order slot and shows up under
        "Closed" for couriers."""
        if not _is_admin_authorized():
            abort(404)
        if store().get_order(order_id) is None:
            abort(404, description=f"No order with id {order_id}")
        store().admin_cancel_order(order_id)
        return redirect(f"/admin/orders?token={request.args.get('token') or request.form.get('token', '')}")

    @app.post("/admin/orders/<int:order_id>/set-price")
    def admin_set_order_price(order_id):
        """Records what Restopolis actually charged (an admin-supplied
        FACT from having placed the real reservation, never guessed) and
        emails the customer to confirm it -- showing both the real price
        and the app's own approximate one side by side (never silently
        replacing one with the other, see mailer.py's
        send_order_needs_confirmation docstring)."""
        if not _is_admin_authorized():
            abort(404)

        real_price_raw = request.form.get("real_price")
        try:
            real_price = float(real_price_raw)
        except (TypeError, ValueError):
            abort(400, description="'real_price' must be a number")

        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order with id {order_id}")
        if not order.get("customer_email"):
            abort(400, description="This order has no customer email on file -- nothing to send a confirmation to")

        token = store().set_real_price(order_id, real_price)
        if token is None:
            abort(409, description="This order isn't in a state a real price can be recorded for (already actioned?)")

        confirm_url = f"{request.host_url}o/{order_id}/confirm?token={token}"
        cancel_url = f"{request.host_url}o/{order_id}/cancel?token={token}"
        order = store().get_order(order_id)  # re-fetch: now carries the real_price/awaiting_confirmation status
        send_order_needs_confirmation(order["customer_email"], order, real_price, confirm_url, cancel_url)

        return redirect(f"/admin/orders?token={request.args.get('token', '')}")

    # ------------------------------------------------ Customer confirmation
    #
    # Public (no admin token, no login) -- reachable only via the one-time
    # link in send_order_needs_confirmation's email, guarded by the
    # per-order confirmation_token OrderStore.confirm_order/cancel_order
    # requires (see orders.py's docstring for the full state machine).

    def _order_link_not_valid():
        return render_template(
            "order_action.html",
            icon="⚠️",
            title="This link isn't valid anymore",
            message="It may have already been used, or the order was already confirmed or cancelled.",
        )

    # GET only shows the button; the POST behind it is what acts. Mail
    # security scanners (Microsoft Safe Links, which uni.lu mailboxes sit
    # behind) open every link in an email -- when these were plain GETs,
    # that alone could confirm or cancel a student's order.
    @app.get("/o/<int:order_id>/confirm")
    def order_confirm_page(order_id):
        token = request.args.get("token", "")
        if not store().is_awaiting_confirmation(order_id, token):
            return _order_link_not_valid()
        return render_template(
            "order_action.html",
            icon="🧾",
            title="Confirm your order?",
            message="Confirm at the real price from the email, and we'll get it to you.",
            form_action=f"/o/{order_id}/confirm",
            form_fields={"token": token},
            form_button="Confirm order",
        )

    @app.post("/o/<int:order_id>/confirm")
    def order_confirm(order_id):
        token = request.form.get("token") or request.args.get("token", "")
        if store().confirm_order(order_id, token):
            return render_template(
                "order_action.html",
                icon="✅",
                title="Order confirmed",
                message="Thanks -- your order is confirmed. See you at the canteen!",
            )
        return _order_link_not_valid()

    @app.get("/o/<int:order_id>/cancel")
    def order_cancel_page(order_id):
        token = request.args.get("token", "")
        if not store().is_awaiting_confirmation(order_id, token):
            return _order_link_not_valid()
        return render_template(
            "order_action.html",
            icon="🚫",
            title="Cancel your order?",
            message="Nothing has been charged. This can't be undone.",
            form_action=f"/o/{order_id}/cancel",
            form_fields={"token": token},
            form_button="Cancel order",
            form_danger=True,
        )

    @app.post("/o/<int:order_id>/cancel")
    def order_cancel(order_id):
        token = request.form.get("token") or request.args.get("token", "")
        if store().cancel_order(order_id, token):
            return render_template(
                "order_action.html",
                icon="🚫",
                title="Order cancelled",
                message="Your order has been cancelled. No charge was made.",
            )
        return _order_link_not_valid()

    # ----------------------------------------------------------- Telegram bot
    #
    # The admin's "📊 Stats" button: Telegram POSTs every message sent to the
    # bot here (registered once by scripts/telegram_setup.py). Only Telegram
    # itself (the secret header) and only the admin's own chat get anywhere.

    @app.post("/telegram/webhook")
    def telegram_webhook():
        expected = webhook_secret()
        given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if expected is None or not secrets.compare_digest(given, expected):
            abort(404)
        update = request.get_json(force=True, silent=True) or {}
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        # Always 200 for a valid Telegram call, even when there's nothing to
        # do: any other status makes Telegram retry the same update.
        if chat_id is not None and is_admin_chat(chat_id) and is_stats_request(message.get("text")):
            send_admin_text(build_stats_message(page_views(), store()), with_stats_button=True)
        return jsonify({"ok": True})

    # ----------------------------------------------------------- Customer
    #
    # Task 3 replaces the Task 2 server-rendered flow with a mobile-first
    # client-rendered app (static/app.js) that talks only to the JSON API
    # above (never fetches Restopolis directly -- see README.md Part 3).
    # One shell route serves it for every restaurant/date/order state.

    # ---------------------------------------------------- Shared dish previews
    #
    # Sharing a dish from the app links to  /?dish=<slug>&date=<date>&cat=<category>&name=<raw name>
    # (&lang=..). The same URL is what a chat app's crawler fetches to build
    # the link preview, so GET / answers a dish link with THAT dish's Open
    # Graph tags and a picture of its card (/og/dish.jpg), instead of the
    # generic app banner; a person's browser runs the app, which opens the
    # dish (static/app.js's openSharedDish()).

    def _short_restaurant_name(full_name: str) -> str:
        """"UDL-CKB - Altius - Restaurant" -> "Altius" (what the app's own
        shortName() shows)."""
        parts = [p.strip() for p in full_name.split(" - ")]
        return parts[1] if len(parts) >= 3 else full_name

    def _dish_share_context(slug: str, date_str: str, category: str, name: str):
        """Everything a preview of one dish needs, or None when any part of
        the link doesn't check out (unknown restaurant, bad date, no such
        dish on that day's menu, no menu at all)."""
        restaurant = by_slug.get(slug)
        if restaurant is None or not category or not name:
            return None
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            flat_items, _ = _load_flat_menu(restaurant, d)
        except Exception:  # noqa: BLE001 -- any of these just means "no dish preview", never a 500 for a crawler
            return None
        item = next((it for it in flat_items if it["category"] == category and it["name"] == name), None)
        if item is None:
            return None
        title, size = split_dish_size(name)
        if INCLUDED_SIDE_CATEGORIES and category in INCLUDED_SIDE_CATEGORIES:
            price_text = "Included with a main dish"
        else:
            total = compute_formula_total([{"category": category, "name": name, "quantity": 1}], tier="adulte")["total"]
            price_text = f"€{total:.2f}" if total is not None else "Canteen Price"
        photo_path = dish_photos().photos_visible_to(slug).get(category, {}).get(name)
        photo_file = None
        if photo_path:
            candidate = app.config["DISH_PHOTO_DIR"] / Path(photo_path).name
            photo_file = candidate if candidate.is_file() else None
        return {
            "restaurant": restaurant,
            "date": d,
            "item": item,
            "title": title,
            "size": size,
            "price_text": price_text,
            "photo_file": photo_file,
        }

    def _og_image_file(ctx: dict, category: str, name: str) -> Path:
        """The rendered card for this dish, from the on-disk cache when it's
        still valid. The key covers everything drawn on it (and the photo's
        mtime), so a new price, photo or menu change makes a new file; old
        ones are swept after two weeks."""
        photo = ctx["photo_file"]
        badge = "VEGAN" if ctx["item"].get("vegan") else "VEGETARIAN" if ctx["item"].get("vegetarian") else None
        footer = f"{_short_restaurant_name(ctx['restaurant'].name)} · {ctx['date'].strftime('%a %d %b')} · UniResto"
        fields = [
            "v1", ctx["restaurant"].code, ctx["date"].isoformat(), category, name, ctx["price_text"], badge or "", footer,
            str(photo.stat().st_mtime_ns) if photo else "",
        ]
        key = hashlib.sha1("|".join(fields).encode("utf-8")).hexdigest()
        cache_dir = app.config["OG_CACHE_DIR"]
        target = cache_dir / f"{key}.jpg"
        if target.is_file():
            return target
        cache_dir.mkdir(parents=True, exist_ok=True)
        english_title = split_dish_size(dish_name_label(name, "en"))[0]
        png = render_dish_card(
            title=english_title,
            size=ctx["size"],
            category=category,
            price_text=ctx["price_text"],
            badge=badge,
            footer=footer,
            photo_path=photo,
        )
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(png)
        tmp.replace(target)
        cutoff = time.time() - 14 * 86400
        for old in cache_dir.glob("*.jpg"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass
        return target

    @app.get("/og/dish.jpg")
    def og_dish_image():
        ctx = _dish_share_context(
            request.args.get("dish", ""), request.args.get("date", ""), request.args.get("cat", ""), request.args.get("name", "")
        )
        if ctx is None:
            abort(404)
        response = send_from_directory(app.config["OG_CACHE_DIR"], _og_image_file(ctx, request.args["cat"], request.args["name"]).name)
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    @app.get("/")
    def mobile_app():
        # ?lang=<code> reflects whichever language the SHARER's app was in
        # when they copied/shared this URL (see static/app.js's
        # syncLangInUrl()) -- not this visitor's own language yet, since
        # nothing server-side has run their client-side i18n. It only
        # drives the Open Graph/Twitter Card preview text below; the app
        # itself picks its language up from localStorage/this same param
        # once static/app.js loads.
        og_lang = request.args.get("lang", "en")
        if og_lang not in OG_PREVIEW_TEXT:
            og_lang = "en"
        og = OG_PREVIEW_TEXT[og_lang]
        og_title, og_description = og["title"], og["description"]
        og_image = url_for("static", filename="og-image.png", _external=True)

        slug, date_str = request.args.get("dish", ""), request.args.get("date", "")
        category, name = request.args.get("cat", ""), request.args.get("name", "")
        ctx = _dish_share_context(slug, date_str, category, name) if slug else None
        if ctx is not None:
            label = split_dish_size(dish_name_label(name, og_lang))[0]
            og_title = f"{label} · {ctx['price_text']}"
            details = [_short_restaurant_name(ctx["restaurant"].name), ctx["date"].strftime("%a %d %b")]
            if ctx["size"]:
                details.append(ctx["size"])
            if ctx["item"].get("vegan"):
                details.append("Vegan")
            elif ctx["item"].get("vegetarian"):
                details.append("Vegetarian")
            og_description = " · ".join(details) + " — order on UniResto"
            og_image = url_for("og_dish_image", dish=slug, date=date_str, cat=category, name=name, _external=True)
        return render_template(
            "mobile.html", og_lang=og_lang, og_title=og_title, og_description=og_description, og_image=og_image
        )

    # Browsers/crawlers request this path directly regardless of the
    # <link rel="icon"> tags in <head> -- without this it 404s even
    # though a favicon is otherwise fully wired up.
    @app.get("/favicon.ico")
    def favicon():
        return redirect(url_for("static", filename="favicon-32.png"))

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5050, use_reloader=False)
