#!/usr/bin/env python3
"""Flask app: JSON API + admin debug page + customer-facing UI for the
orderability engine. Dev server only (see README.md) -- no payment, no
real Restopolis order placement, no delivery routing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, render_template, request

from orderability_engine.cache import OrderabilityCache
from orderability_engine.mailer import send_order_confirmation
from orderability_engine.menu_service import flatten_menu_items, get_customer_menu
from orderability_engine.models import STATUS_VALUES, TZINFO
from orderability_engine.orders import MAX_QUANTITY, OrderStore, OrderValidationError, recalculate_order
from orderability_engine.service import OrderabilityService
from orderability_engine.smart_lunch import TIER_ORDER, find_smart_lunch
from restopolis.config import load_restaurants
from scraper import slug_for

# Loads SMTP_USER/SMTP_PASSWORD/etc from a git-ignored .env file in the
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


def create_app(service: OrderabilityService | None = None, order_store: OrderStore | None = None) -> Flask:
    app = Flask(__name__)

    restaurants = load_restaurants()
    by_slug = {slug_for(code): cfg for code, cfg in restaurants.items()}

    app.config["ORDERABILITY_SERVICE"] = service or OrderabilityService(
        cache=OrderabilityCache("orderability.db"), restaurants=restaurants
    )
    app.config["ORDER_STORE"] = order_store or OrderStore("orders.db")
    app.config["RESTAURANTS_BY_SLUG"] = by_slug

    def svc() -> OrderabilityService:
        return app.config["ORDERABILITY_SERVICE"]

    def store() -> OrderStore:
        return app.config["ORDER_STORE"]

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
            [{"slug": slug, "code": r.code, "name": r.name} for slug, r in by_slug.items()]
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

        flat_items, _ = _load_flat_menu(restaurant, d)
        try:
            quote = recalculate_order(flat_items, selection)
        except OrderValidationError as exc:
            return jsonify({"error": "invalid_selection", "message": str(exc)}), 400

        order_id = store().create_order(restaurant.code, restaurant.name, d, quote["items"], delivery_location)
        order = store().get_order(order_id)

        # Best-effort, never fails the order itself: a flaky mail server
        # or unset SMTP_USER/SMTP_PASSWORD must never turn a successful
        # order into a 500 (see mailer.py's module docstring). Only
        # attempted when an email was actually given -- most orders in
        # this dev-only app won't have one.
        if customer_email is not None:
            sent, error = send_order_confirmation(customer_email, order)
            order["email_sent"] = sent
            order["email_error"] = error

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
