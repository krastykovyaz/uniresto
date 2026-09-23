"""Loads the actual dish list for a date once orderability has confirmed
it's valid (status == "available"), reusing Task 1's parser.

Reuses whatever week HTML the OrderabilityService already fetched/cached
for that (restaurant, date) rather than issuing a second round of
requests to Restopolis.
"""

from __future__ import annotations

from datetime import date

from restopolis.models import DailyMenu, RestaurantConfig
from restopolis.parser import SERVICE_NAME_MENU, parse_week_html
from restopolis.weight import format_weight

from orderability_engine.detector import MENU_SOURCE_URL
from orderability_engine.nutrition import estimate_calories
from orderability_engine.service import OrderabilityService


def get_menu_for_date(
    service: OrderabilityService,
    restaurant: RestaurantConfig,
    target_date: date,
    include_constant_products: bool = False,
) -> list[DailyMenu]:
    """Returns the DailyMenu entries (one per service_name) for this date.
    Raises the same PastDateError/HorizonExceededError/MenuParseError as
    the detector if the date can't be reached -- callers should have
    already confirmed status == "available" via check_orderability."""
    html, _weeks_ahead = service.get_week_html(restaurant, target_date)
    all_menus = parse_week_html(
        html,
        restaurant.code,
        restaurant.name,
        MENU_SOURCE_URL,
        include_constant_products=include_constant_products,
    )
    return [m for m in all_menus if m.menu_date == target_date]


def get_daily_formula(service: OrderabilityService, restaurant: RestaurantConfig, target_date: date) -> DailyMenu | None:
    menus = get_menu_for_date(service, restaurant, target_date, include_constant_products=False)
    return next((m for m in menus if m.service_name == SERVICE_NAME_MENU), None)


def get_customer_menu(service: OrderabilityService, restaurant: RestaurantConfig, target_date: date) -> list[DailyMenu]:
    """Returns everything the mobile UI (Task 3) should be able to offer:
    the daily formula (Entrée/Végétarien/...) AND Constant products
    (sandwiches/snacks/drinks). Both are real Restopolis categories for
    this date; Constant products is where portion weight is actually
    present in the source data (see restopolis/weight.py) so including
    it is what makes the weight feature demonstrable with real data
    rather than permanently empty."""
    return get_menu_for_date(service, restaurant, target_date, include_constant_products=True)


def flatten_menu_items(daily_menus: list[DailyMenu]) -> list[dict]:
    """Flattens the DailyMenu list (one per service_name) into the item
    shape the Task 3 frontend/API expects, with a stable sequential `id`
    (stable within one response; the backend re-derives it fresh from the
    live menu on every request rather than trusting a client-cached one --
    see orderability_engine/orders.recalculate_order).

    `portions` is always [] here: Restopolis never exposes more than one
    priced/weighed variant of the same dish (confirmed: no price data at
    all on the public Menu page), so there is nothing to group into
    portions without fabricating it. The field exists so the frontend's
    portion-selector code path is exercised structurally even though it
    never actually renders for today's real data.
    """
    flat = []
    next_id = 0
    for menu in daily_menus:
        for item in menu.items:
            nutrition = estimate_calories(item.name, item.weight_value, item.weight_unit)
            flat.append(
                {
                    "id": next_id,
                    "service": menu.service_name,
                    "category": item.category,
                    "name": item.name,
                    "description": item.description,
                    "price": item.price,
                    "weight_value": item.weight_value,
                    "weight_unit": item.weight_unit,
                    "weight_display": format_weight(item.weight_value, item.weight_unit),
                    "allergens": item.allergens,
                    "dietary": item.dietary,
                    "vegetarian": item.is_vegetarian,
                    "vegan": item.is_vegan,
                    "portions": [],
                    "calories": nutrition["calories"],
                    "calories_food_type": nutrition["food_type"],
                    "calories_estimated": nutrition["is_estimated"],
                }
            )
            next_id += 1
    return flat
