#!/usr/bin/env python3
"""Flask app: JSON API + admin debug page + customer-facing UI for the
orderability engine. Dev server only (see README.md) -- no payment, no
real Restopolis order placement, no delivery routing.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from orderability_engine.cache import OrderabilityCache
from orderability_engine.cache_warmer import start_cache_warmer
from orderability_engine.coming_soon_clicks import ComingSoonClickStore
from orderability_engine.daily_report import DailyReportStore, start_daily_report_scheduler
from orderability_engine.delivery_subscribers import DeliverySubscriberStore
from orderability_engine.email_verification import EmailVerificationStore
from orderability_engine.feedback import FeedbackStore
from orderability_engine.mailer import (
    generate_verification_code,
    send_delivery_notification,
    send_order_confirmation,
    send_order_needs_confirmation,
    send_order_out_for_delivery,
    send_verification_code,
)
from orderability_engine.menu_service import flatten_menu_items, get_customer_menu
from orderability_engine.delivery_rules import is_delivery_expired
from orderability_engine.models import STATUS_VALUES, TZINFO
from orderability_engine.orders import MAX_QUANTITY, OrderStore, OrderValidationError, recalculate_order
from orderability_engine.page_views import MAX_SOURCE_LENGTH, PageViewStore
from orderability_engine.rate_limits import RateLimitStore
from orderability_engine.service import OrderabilityService
from orderability_engine.smart_lunch import TIER_ORDER, find_smart_lunch
from orderability_engine.telegram_notify import (
    send_admin_notification,
    send_feedback_notification,
    send_order_claimed_notification,
    send_order_released_notification,
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


def create_app(
    service: OrderabilityService | None = None,
    order_store: OrderStore | None = None,
    email_verification_store: EmailVerificationStore | None = None,
    delivery_verification_store: EmailVerificationStore | None = None,
    delivery_subscriber_store: DeliverySubscriberStore | None = None,
    coming_soon_click_store: ComingSoonClickStore | None = None,
    feedback_store: FeedbackStore | None = None,
    page_view_store: PageViewStore | None = None,
    daily_report_store: DailyReportStore | None = None,
    rate_limit_store: RateLimitStore | None = None,
    enable_cache_warmer: bool = True,
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
    app.config["DELIVERY_SUBSCRIBER_STORE"] = delivery_subscriber_store or DeliverySubscriberStore("orders.db")
    app.config["COMING_SOON_CLICK_STORE"] = coming_soon_click_store or ComingSoonClickStore("orders.db")
    app.config["FEEDBACK_STORE"] = feedback_store or FeedbackStore("orders.db")
    app.config["PAGE_VIEW_STORE"] = page_view_store or PageViewStore("orders.db")
    app.config["DAILY_REPORT_STORE"] = daily_report_store or DailyReportStore("orders.db")
    app.config["RATE_LIMIT_STORE"] = rate_limit_store or RateLimitStore("orders.db")
    app.config["RESTAURANTS_BY_SLUG"] = by_slug

    def svc() -> OrderabilityService:
        return app.config["ORDERABILITY_SERVICE"]

    def store() -> OrderStore:
        return app.config["ORDER_STORE"]

    def email_verification() -> EmailVerificationStore:
        return app.config["EMAIL_VERIFICATION_STORE"]

    def delivery_verification() -> EmailVerificationStore:
        return app.config["DELIVERY_VERIFICATION_STORE"]

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

    def get_restaurant_or_404(slug: str):
        restaurant = by_slug.get(slug)
        if restaurant is None:
            abort(404, description=f"Unknown restaurant slug {slug!r}")
        return restaurant

    # Keeps the orderability/menu cache warm on its own schedule, off the
    # request path (see cache_warmer.py's own docstring) -- default ON
    # for the real app (both the local dev entry point below and
    # gunicorn's factory call in production), explicitly OFF in tests
    # (see tests/test_app.py's _make_client()), which construct their own
    # short-lived app + FakeRestopolisClient per test and have no use for
    # a background thread outliving the test itself.
    if enable_cache_warmer:
        start_cache_warmer(svc(), list(restaurants.values()))

    # Off in tests (see tests/test_app.py's _make_client()), same
    # reasoning as enable_cache_warmer above -- a short-lived per-test app
    # has no use for a background thread that only ever wakes up once a
    # day, and it would otherwise outlive the test itself.
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
        delivery_location = body.get("delivery_location")
        # Optional (Part 23): only sent when the customer filled in the
        # checkout email field. No account system, so this is never
        # persisted -- it's used once, right here, to send the
        # confirmation, then discarded (see mailer.py).
        customer_email = (body.get("customer_email") or "").strip() or None
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

        if not slug or not date_str or not selection:
            abort(400, description="Body must include 'restaurant', 'date', and a non-empty 'items' list of {id, quantity}")
        if customer_email is not None and not _is_valid_email_format(customer_email):
            abort(400, description="'customer_email' must be a valid email address")
        if customer_note is not None and len(customer_note) > 500:
            abort(400, description="'customer_note' must be at most 500 characters")

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

        order_id = store().create_order(
            restaurant.code,
            restaurant.name,
            d,
            quote["items"],
            delivery_location,
            customer_email,
            customer_note,
            customer_lang,
        )
        order = store().get_order(order_id)

        # Best-effort, never fails the order itself: a flaky mail API
        # or unset RESEND_API_KEY must never turn a successful
        # order into a 500 (see mailer.py's module docstring). Only
        # attempted when an email was actually given -- most orders in
        # this dev-only app won't have one.
        if customer_email is not None:
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
        # restaurant.restaurant_id is real, verified data from
        # restaurants.yaml (see its own header comment), never guessed.
        restopolis_url = f"{RESTOPOLIS_BASE_URL}/Menu/BtnChangeRestaurant?pRestaurantSelection={restaurant.restaurant_id}"
        send_admin_notification(
            order, admin_url=admin_url, mark_reviewing_url=mark_reviewing_url, restopolis_url=restopolis_url
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
        return jsonify(order)

    # ------------------------------------------------------ Email verification

    @app.post("/api/email/send-code")
    def api_email_send_code():
        """Sends a fresh 6-digit code to `email` (Part 27) -- issued/
        stored ONLY if the send itself actually succeeded, so a delivery
        failure never leaves a code silently un-sendable-but-verifiable,
        and never blocks an immediate retry either (see
        EmailVerificationStore.issue()'s docstring)."""
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
        not, the entry is consumed/invalidated so it can't be replayed."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        code = (body.get("code") or "").strip()
        if not email or not code:
            abort(400, description="Body must include 'email' and 'code'")
        verified, reason = email_verification().verify(email, code)
        return jsonify({"verified": verified, "reason": reason})

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
        notifies it; on an incorrect/expired one, nothing is persisted."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        code = (body.get("code") or "").strip()
        if not email or not code:
            abort(400, description="Body must include 'email' and 'code'")
        verified, reason = delivery_verification().verify(email, code)
        if verified:
            delivery_subscribers().add(email, _normalize_lang_arg(body.get("lang")) or "en")
        return jsonify({"verified": verified, "reason": reason})

    @app.post("/api/delivery/register/quick")
    def api_delivery_register_quick():
        """Registers a courier address with NO code round-trip, for the
        one case where that's a reasonable shortcut rather than a real
        gap: the frontend only ever calls this with the SAME address
        already sitting in this browser's own state.registeredEmail --
        which itself only gets set there after that address completed
        the real customer send-code/verify-code flow (Part 25/27), on
        this same device. Re-proving control of an address this device
        already proved it can read is a needless second code, not
        stronger security -- and this app's own checkout already accepts
        a typed customer_email with zero verification at all (see
        _is_valid_email_format's docstring), so trusting a client-echoed
        address here is no looser than the rest of this app's standing
        trust model. Still domain-checked (courier eligibility, same as
        every other delivery-registration path), just not code-checked."""
        body = request.get_json(force=True, silent=True) or {}
        email = (body.get("email") or "").strip()
        if not email:
            abort(400, description="Body must include 'email'")
        if not _is_allowed_customer_email(email):
            abort(400, description=f"'email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")
        delivery_subscribers().add(email, _normalize_lang_arg(body.get("lang")) or "en")
        return jsonify({"registered": True})

    @app.get("/api/delivery/orders")
    def api_delivery_orders():
        """Real orders for the in-app Delivery screen (Part 52+) -- every
        order regardless of status, newest first (see
        OrderStore.list_recent_orders()'s own docstring for why a
        cancelled one is still included, for the screen's own "Closed"
        section). Deliberately strips customer_email from every order
        before returning: a courier needs to know WHERE to bring the
        order, never who placed it. Viewing this list needs no
        registration/verification at all (see delivery_subscribers.py's
        own docstring) -- registering only controls whether an address
        gets emailed."""
        # Part 74: a real Delivery-screen visit for the evening report --
        # counted only within the rate limit (Part 77), so a refresh loop
        # can't pad the report; the list itself is always served.
        if within_rate_limit("delivery_view")[0]:
            page_views().record("delivery")
        orders = store().list_recent_orders()
        now = datetime.now(TZINFO)
        for order in orders:
            order.pop("customer_email", None)
            # Part 76: the Delivery screen's "Expired" section reads this
            # instead of comparing dates on the courier's own device.
            order["expired"] = is_delivery_expired(date.fromisoformat(order["order_date"]), now)
        return jsonify(orders)

    @app.post("/api/orders/<int:order_id>/claim")
    def api_claim_order(order_id):
        """Courier-facing (Part 75), same no-account/no-gate reasoning as
        /api/delivery/orders -- anyone looking at the Delivery screen can
        claim an order, same trust level as everyone already seeing every
        order on it. Only the courier who actually WINS the claim (see
        OrderStore.mark_claimed()'s own docstring on why a second tap
        never re-fires this) triggers the admin Telegram ping and, if the
        customer left an email, the "on its way" email -- both
        best-effort, same reasoning as every other notification in this
        app: a flaky send must never fail the claim itself."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order #{order_id}")
        # The UI never offers "Take this delivery" on these, but the route
        # is ungated -- a stale tab or a direct call must not email a
        # customer "on its way" about an order that was called off or is
        # already in their hands.
        if order["status"] == "cancelled" or order["delivered_at"]:
            return jsonify({"error": "not_claimable", "status": order["status"], "delivered": bool(order["delivered_at"])}), 409
        newly_claimed = store().mark_claimed(order_id)
        if newly_claimed:
            send_order_claimed_notification(order, admin_url=_admin_orders_url())
            # At most once per order (Part 76): a release + re-claim, or a
            # claim/release loop, must never email the customer again.
            if order.get("customer_email") and store().mark_on_way_emailed(order_id):
                send_order_out_for_delivery(order["customer_email"], order)
        return jsonify({"claimed": True, "already_claimed": not newly_claimed})

    @app.post("/api/orders/<int:order_id>/unclaim")
    def api_unclaim_order(order_id):
        """Part 76: "I can't deliver this after all" -- the courier who
        took it gives it back, so it shows "Take this delivery" again for
        everyone else. Pings the admin (who was told it was claimed); the
        customer is NOT emailed -- they were told it's on its way once,
        and the next courier to take it is what actually matters to them."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        order = store().get_order(order_id)
        if order is None:
            abort(404, description=f"No order #{order_id}")
        if not store().mark_unclaimed(order_id):
            return jsonify({"error": "not_claimed"}), 409
        send_order_released_notification(order, admin_url=_admin_orders_url())
        return jsonify({"claimed": False})

    @app.post("/api/orders/<int:order_id>/mark-delivered")
    def api_mark_order_delivered(order_id):
        """Courier-facing (Part 73), same no-account/no-gate reasoning as
        /api/delivery/orders above -- anyone looking at the Delivery
        screen can mark an order delivered, same trust level as everyone
        already seeing every order on it."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
        if not store().mark_delivered(order_id):
            abort(404, description=f"No order #{order_id}")
        return jsonify({"delivered": True})

    @app.post("/api/orders/<int:order_id>/mark-not-delivered")
    def api_mark_order_not_delivered(order_id):
        """Undoes the above -- a courier tapping the wrong order, or too
        early, must be able to reverse it."""
        if (limited := rate_limited_response("courier_action")) is not None:
            return limited
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
        if len(message) > 2000:
            abort(400, description="'message' must be at most 2000 characters")
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

    @app.get("/o/<int:order_id>/confirm")
    def order_confirm(order_id):
        token = request.args.get("token", "")
        if store().confirm_order(order_id, token):
            return render_template(
                "order_action.html",
                icon="✅",
                title="Order confirmed",
                message="Thanks -- your order is confirmed. See you at the canteen!",
            )
        return render_template(
            "order_action.html",
            icon="⚠️",
            title="This link isn't valid anymore",
            message="It may have already been used, or the order was already confirmed or cancelled.",
        )

    @app.get("/o/<int:order_id>/cancel")
    def order_cancel(order_id):
        token = request.args.get("token", "")
        if store().cancel_order(order_id, token):
            return render_template(
                "order_action.html",
                icon="🚫",
                title="Order cancelled",
                message="Your order has been cancelled. No charge was made.",
            )
        return render_template(
            "order_action.html",
            icon="⚠️",
            title="This link isn't valid anymore",
            message="It may have already been used, or the order was already confirmed or cancelled.",
        )

    # ----------------------------------------------------------- Customer
    #
    # Task 3 replaces the Task 2 server-rendered flow with a mobile-first
    # client-rendered app (static/app.js) that talks only to the JSON API
    # above (never fetches Restopolis directly -- see README.md Part 3).
    # One shell route serves it for every restaurant/date/order state.

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
        return render_template("mobile.html", og_lang=og_lang, og_title=og["title"], og_description=og["description"])

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
