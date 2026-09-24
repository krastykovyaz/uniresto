#!/usr/bin/env python3
"""Flask app: JSON API + admin debug page + customer-facing UI for the
orderability engine. Dev server only (see README.md) -- no payment, no
real Restopolis order placement, no delivery routing.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request

from orderability_engine.cache import OrderabilityCache
from orderability_engine.email_verification import EmailVerificationStore
from orderability_engine.mailer import (
    generate_verification_code,
    send_order_confirmation,
    send_order_needs_confirmation,
    send_verification_code,
)
from orderability_engine.menu_service import flatten_menu_items, get_customer_menu
from orderability_engine.models import STATUS_VALUES, TZINFO
from orderability_engine.orders import MAX_QUANTITY, OrderStore, OrderValidationError, recalculate_order
from orderability_engine.service import OrderabilityService
from orderability_engine.smart_lunch import TIER_ORDER, find_smart_lunch
from orderability_engine.telegram_notify import send_admin_notification
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


def _is_allowed_customer_email(email: str) -> bool:
    normalized = email.strip().lower()
    if normalized.count("@") != 1 or normalized.startswith("@"):
        return False
    return normalized.endswith(ALLOWED_EMAIL_DOMAINS)


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


def create_app(
    service: OrderabilityService | None = None,
    order_store: OrderStore | None = None,
    email_verification_store: EmailVerificationStore | None = None,
) -> Flask:
    app = Flask(__name__)

    restaurants = load_restaurants()
    by_slug = {slug_for(code): cfg for code, cfg in restaurants.items()}

    app.config["ORDERABILITY_SERVICE"] = service or OrderabilityService(
        cache=OrderabilityCache("orderability.db"), restaurants=restaurants
    )
    app.config["ORDER_STORE"] = order_store or OrderStore("orders.db")
    app.config["EMAIL_VERIFICATION_STORE"] = email_verification_store or EmailVerificationStore()
    app.config["RESTAURANTS_BY_SLUG"] = by_slug

    def svc() -> OrderabilityService:
        return app.config["ORDERABILITY_SERVICE"]

    def store() -> OrderStore:
        return app.config["ORDER_STORE"]

    def email_verification() -> EmailVerificationStore:
        return app.config["EMAIL_VERIFICATION_STORE"]

    def get_restaurant_or_404(slug: str):
        restaurant = by_slug.get(slug)
        if restaurant is None:
            abort(404, description=f"Unknown restaurant slug {slug!r}")
        return restaurant

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
        try:
            quote = recalculate_order(flat_items, selection)
        except OrderValidationError as exc:
            return jsonify({"error": "invalid_selection", "message": str(exc)}), 400
        return jsonify(quote)

    @app.post("/api/orders")
    def api_create_order():
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

        if not slug or not date_str or not selection:
            abort(400, description="Body must include 'restaurant', 'date', and a non-empty 'items' list of {id, quantity}")
        if customer_email is not None and not _is_allowed_customer_email(customer_email):
            abort(400, description=f"'customer_email' must be a valid address ending in {' or '.join(ALLOWED_EMAIL_DOMAINS)}")

        restaurant = get_restaurant_or_404(slug)
        d = parse_date_arg(date_str)

        # Re-check orderability AND re-fetch the live menu at confirm time,
        # not just at page-load time -- both can have changed since.
        result = svc().check_orderability(restaurant, d)
        if result.status != "available":
            return jsonify({"error": "date_not_available", "status": result.status, "reason": result.reason}), 409
        # Restopolis's own signals can say available while OUR same-day
        # 08:00 cutoff has already passed (evaluate_our_delivery) -- the
        # menu stays browsable past that point (see api_menu above, never
        # gated on our_delivery), but an order must never actually be
        # created once we've told the customer it's closed.
        if not result.our_delivery.available:
            return jsonify({"error": "date_not_available", "status": "closed", "reason": "Our ordering deadline for this date has passed."}), 409

        flat_items, _ = _load_flat_menu(restaurant, d)
        try:
            quote = recalculate_order(flat_items, selection)
        except OrderValidationError as exc:
            return jsonify({"error": "invalid_selection", "message": str(exc)}), 400

        order_id = store().create_order(
            restaurant.code, restaurant.name, d, quote["items"], delivery_location, customer_email
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
        send_admin_notification(order, admin_url=admin_url, mark_reviewing_url=mark_reviewing_url)

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
        today = datetime.now(TZINFO).date()
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
        return render_template("mobile.html")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5050, use_reloader=False)
