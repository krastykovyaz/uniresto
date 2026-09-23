"""OUR OWN per-item course pricing rule -- NOT Restopolis data.

Restopolis's public Menu page never exposes a price at all (verified,
see README.md Part 3 §21) -- every scraped `MenuItem.price` is always
`None`. This module is a *separate*, explicitly non-Restopolis pricing
rule, supplied directly (University of Luxembourg Campus Kirchberg
canteen's real course pricing), the same way Part 2's delivery deadline
(orderability_engine/delivery_rules.py) is OUR rule kept structurally
apart from Restopolis's (also always-null) own deadline. It is not
scraped, not derived from the site, and must never be confused with a
per-dish Restopolis price.

The canteen prices each COURSE independently -- not the whole meal as
one bundle:

    main dish (Non-végétarien / Végétarien / Végan)   -> EUR 6.00
    starter / salad (Entrée)                          -> EUR 2.00
    dessert                                            -> EUR 2.00

Each category's line total is quantity x its own flat price, and the
order total is simply their sum -- there is no bundled "meal formula"
tier lookup here (an earlier v1 rule priced main-alone/main+starter/
main+starter+dessert as 3 fixed bundle totals of 3.70/4.20/5.20; this
supersedes it with flat per-item prices, supplied directly, 2026-09).
Unlike the old bundle rule, every combination is now priceable,
including a starter or dessert bought on its own -- there is no
"combination this data has no price for" case left to guard against.

Two categories (Féculents/starches, Légumes/vegetables) still ride
along free with any main dish -- see INCLUDED_SIDE_CATEGORIES -- and
Constant Products / Snack à emporter items (sandwiches, drinks,
pastries) are still not part of this pricing at all, since no price for
them was ever given either.
"""

from __future__ import annotations

MAIN_CATEGORIES = {"Non-végétarien", "Végétarien", "Végan"}
STARTER_CATEGORIES = {"Entrée"}
DESSERT_CATEGORIES = {"Dessert"}
INCLUDED_SIDE_CATEGORIES = {"Féculents", "Légumes"}  # bundled free with a main, never separately priced

CATEGORY_PRICES = {
    "main": 6.00,
    "starter": 2.00,
    "dessert": 2.00,
}


def compute_formula_total(line_items: list[dict]) -> dict:
    """line_items: recalculate_order()'s line items (each has `category`
    and `quantity`; category is Restopolis's raw, e.g. "Non-végétarien").

    Returns:
        {"formula_count": int, "main_count": int, "starter_count": int,
         "dessert_count": int, "total": float | None, "reason": str | None}

    Each of main_count/starter_count/dessert_count is the total quantity
    ordered in that course category; `formula_count` is their sum -- the
    total quantity of priced items this total covers. `total` is
    main_count*6.00 + starter_count*2.00 + dessert_count*2.00, or `None`
    only when formula_count is 0 (nothing in the selection falls into a
    priced course category at all -- an empty cart, or a cart containing
    only sides/Constant-Products/snacks). `reason` is always `None`: kept
    in the shape for API/frontend compatibility with the old bundle
    rule's "combination this data can't price" case, which flat per-item
    pricing no longer has.
    """
    main_qty = sum(it["quantity"] for it in line_items if it["category"] in MAIN_CATEGORIES)
    starter_qty = sum(it["quantity"] for it in line_items if it["category"] in STARTER_CATEGORIES)
    dessert_qty = sum(it["quantity"] for it in line_items if it["category"] in DESSERT_CATEGORIES)
    formula_count = main_qty + starter_qty + dessert_qty

    if formula_count == 0:
        return {
            "formula_count": 0,
            "main_count": 0,
            "starter_count": 0,
            "dessert_count": 0,
            "total": None,
            "reason": None,
        }

    total = main_qty * CATEGORY_PRICES["main"] + starter_qty * CATEGORY_PRICES["starter"] + dessert_qty * CATEGORY_PRICES["dessert"]
    return {
        "formula_count": formula_count,
        "main_count": main_qty,
        "starter_count": starter_qty,
        "dessert_count": dessert_qty,
        "total": round(total, 2),
        "reason": None,
    }
