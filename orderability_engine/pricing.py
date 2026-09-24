"""OUR OWN meal-formula pricing rule -- NOT Restopolis data.

Restopolis's public Menu page never exposes a price at all (verified,
see README.md Part 3 §21) -- every scraped `MenuItem.price` is always
`None`. This module is a *separate*, explicitly non-Restopolis pricing
rule, supplied directly (University of Luxembourg Campus Kirchberg
canteen's real course pricing), the same way Part 2's delivery deadline
(orderability_engine/delivery_rules.py) is OUR rule kept structurally
apart from Restopolis's (also always-null) own deadline. It is not
scraped, not derived from the site, and must never be confused with a
per-dish Restopolis price.

The canteen prices a MEAL as a 3-tier bundle, not each course
separately (Part 32, supplied directly):

    main dish alone                                    -> EUR 6.00
    main dish + starter/salad (Entrée)                 -> EUR 7.00
    main dish + starter/salad + dessert                -> EUR 8.00

A starter only upgrades the tier when it accompanies a main dish, and a
dessert only upgrades further when a starter is also present -- a
starter with no main, or a dessert with no starter, isn't a priced
combination at all (`reason` explains which). This restores the
bundle-tier shape Part 18 had flattened into flat per-course sums
(6.00/2.00/2.00); see git history for that intermediate flat rule.

Multiple mains are paired one-for-one, greedily, against however many
starters/desserts are actually in the cart -- e.g. 2 mains + 1 starter
prices as one EUR 7.00 meal (main+starter) and one EUR 6.00 meal
(main alone), not both mains at the upgraded tier. This avoids
overcharging a main that has no starter of its own to pair with.

Sandwiches (Constant Products, any of the 4 real Restopolis sandwich
categories) are priced independently of the meal-formula bundle, at a
flat EUR 4.00 each -- they're a standalone purchase, not part of the
main+starter+dessert tiers above.

Two categories (Féculents/starches, Légumes/vegetables) still ride
along free with any main dish -- see INCLUDED_SIDE_CATEGORIES -- and the
REST of Constant Products / Snack à emporter (drinks, pastries, etc) are
still not part of this pricing at all, since no price for them was ever
given either -- only sandwiches, specifically, per Part 26.
"""

from __future__ import annotations

MAIN_CATEGORIES = {"Non-végétarien", "Végétarien", "Végan"}
STARTER_CATEGORIES = {"Entrée"}
DESSERT_CATEGORIES = {"Dessert"}
INCLUDED_SIDE_CATEGORIES = {"Féculents", "Légumes"}  # bundled free with a main, never separately priced

# The 4 real Restopolis "Constant products" sandwich categories (see
# tests/fixtures and data/menus.json) -- every sandwich on the real menu
# falls into exactly one of these, split by dietary type, never a
# separate "Sandwich" category of its own.
SANDWICH_CATEGORIES = {
    "01.1 Sandwiches végétariens",
    "01.2 Sandwiches végans",
    "01.3 Sandwiches non-végétariens",
    "01.4 Sandwiches sans gluten",
}

MEAL_TIER_PRICES = {
    "main": 6.00,
    "main_starter": 7.00,
    "main_starter_dessert": 8.00,
}
SANDWICH_PRICE = 4.00


def compute_formula_total(line_items: list[dict]) -> dict:
    """line_items: recalculate_order()'s line items (each has `category`
    and `quantity`; category is Restopolis's raw, e.g. "Non-végétarien").

    Returns:
        {"formula_count": int, "main_count": int, "starter_count": int,
         "dessert_count": int, "sandwich_count": int, "total": float | None,
         "reason": str | None}

    Each of main_count/starter_count/dessert_count/sandwich_count is the
    total quantity ordered in that course category; `formula_count` is
    their sum. `total` is the combined meal-bundle + sandwich total, or
    `None` when formula_count is 0 (nothing priced at all) OR when the
    selection includes a starter with no main, or a dessert with no
    starter -- see `reason` (one of "no_main_dish" /
    "dessert_without_starter") for which. Sandwiches never block: a
    sandwich alongside an unpriceable combination still contributes
    nothing when `reason` is set, matching the pre-existing binary
    total-or-reason contract the frontend already expects.
    """
    main_qty = sum(it["quantity"] for it in line_items if it["category"] in MAIN_CATEGORIES)
    starter_qty = sum(it["quantity"] for it in line_items if it["category"] in STARTER_CATEGORIES)
    dessert_qty = sum(it["quantity"] for it in line_items if it["category"] in DESSERT_CATEGORIES)
    sandwich_qty = sum(it["quantity"] for it in line_items if it["category"] in SANDWICH_CATEGORIES)
    formula_count = main_qty + starter_qty + dessert_qty + sandwich_qty

    result = {
        "formula_count": formula_count,
        "main_count": main_qty,
        "starter_count": starter_qty,
        "dessert_count": dessert_qty,
        "sandwich_count": sandwich_qty,
        "total": None,
        "reason": None,
    }

    if formula_count == 0:
        return result

    if main_qty == 0 and (starter_qty > 0 or dessert_qty > 0):
        result["reason"] = "no_main_dish"
        return result

    if dessert_qty > 0 and starter_qty == 0:
        result["reason"] = "dessert_without_starter"
        return result

    # Greedily pair each main with a starter (if any remain), then each
    # of those with a dessert (if any remain) -- see module docstring on
    # why this is per-main pairing, not a single order-wide tier flag.
    paired_starter = min(main_qty, starter_qty)
    paired_dessert = min(paired_starter, dessert_qty)
    mains_full = paired_dessert
    mains_with_starter_only = paired_starter - paired_dessert
    mains_plain = main_qty - paired_starter

    meal_total = (
        mains_full * MEAL_TIER_PRICES["main_starter_dessert"]
        + mains_with_starter_only * MEAL_TIER_PRICES["main_starter"]
        + mains_plain * MEAL_TIER_PRICES["main"]
    )
    sandwich_total = sandwich_qty * SANDWICH_PRICE

    result["total"] = round(meal_total + sandwich_total, 2)
    return result
