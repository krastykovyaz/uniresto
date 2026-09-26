"""OUR OWN meal-formula pricing rule -- NOT Restopolis data.

Restopolis's public Menu page never exposes a price at all (verified,
see README.md Part 3 §21) -- every scraped `MenuItem.price` is always
`None`. This module is a *separate*, explicitly non-Restopolis pricing
rule. Unlike every earlier version of this file (see git history: a
flat per-course sum, then a bundle-tier rule with prices "supplied
directly" as placeholders), these are the REAL, OFFICIAL Restopolis
"Food4Future" price lists for Campus Kirchberg (2026/27 tariffs,
effective 01.09.2026) -- specifically the "adultes" (staff/professor)
tier, not the cheaper "apprenants" (student) tier or the pricier
"visiteurs" tier the same lists also carry. UniResto has no concept of
who's ordering, so this module only ever prices the one tier it's been
told to use.

THE MEAL FORMULA (dine-in "RESTAURANT" price list, Formules 1-3):

    Formule 3: main dish alone                          -> EUR 6.70
    Formule 2: main + starter/salad, OR main + dessert   -> EUR 7.70
    Formule 1: main + starter/salad + dessert            -> EUR 8.70

Formule 2 is genuinely an OR: a starter alone upgrades the tier, and
SEPARATELY so does a dessert alone -- unlike the previous version of
this rule, a dessert no longer requires a starter to be present first.
A starter/dessert with NO main at all still isn't a priced combination
(`reason` = "no_main_dish") -- every real formule requires a "Plat".

Multiple mains are paired greedily: first every main that has BOTH a
starter and a dessert available reaches the full Formule 1 tier, then
remaining mains pair with whatever single side (starter OR dessert) is
still available for the Formule 2 tier, and any main left over with
neither prices as Formule 3 alone. E.g. 2 mains + 1 starter prices as
one EUR 7.70 meal and one EUR 6.70 meal, not both at the upgraded tier.

SNACK À EMPORTER (salads/wraps -- Restopolis's own category, a complete
item on its own, not a side of anything) is priced independently at a
flat EUR 4.80 each, from the same "CAFÉTÉRIA" price list's own
"Snack à emporter" line -- never gated on a main dish being present.

SANDWICHES (Constant Products, the 4 real Restopolis sandwich
categories) are ALSO priced independently of the meal formula, but --
unlike every earlier version of this rule, which charged one flat price
for any sandwich -- each real sandwich has its own official price
(EUR 0.25 to EUR 4.00), transcribed directly from the same "CAFÉTÉRIA"
price list's "Sandwiches" section. A sandwich whose exact name isn't in
SANDWICH_PRICES (the real menu occasionally carries an item not yet
seen and catalogued here) is simply left out of the total rather than
guessed at -- same "never invent a price" rule as everywhere else in
this module.

Two categories (Féculents/starches, Légumes/vegetables) still ride
along free with any main dish -- see INCLUDED_SIDE_CATEGORIES -- and the
REST of Constant Products (drinks, viennoiseries, dairy, etc) are still
not priced by this module at all -- real official prices exist for
those too (same price lists), but transcribing them is a separate,
follow-up piece of work, not rushed into this one.
"""

from __future__ import annotations

MAIN_CATEGORIES = {"Non-végétarien", "Végétarien", "Végan"}
STARTER_CATEGORIES = {"Entrée"}
DESSERT_CATEGORIES = {"Dessert"}
SNACK_CATEGORIES = {"Snack à emporter"}
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
    "main": 6.70,
    "main_starter": 7.70,
    "main_starter_dessert": 8.70,
}
SNACK_PRICE = 4.80

# Transcribed directly from Restopolis's official "LISTE DE PRIX 26/27 --
# CAFÉTÉRIA" (adultes column), keyed by the exact name Restopolis's own
# scraped HTML uses for that item (see restopolis/parser.py) -- not the
# price list's own wording where the two differ (e.g. its "Parmigana"
# vs the real site's "Parmigiana Sandwich"), since the lookup has to
# match what actually comes back from a live menu fetch. Sandwiches
# on the real menu but not yet seen/catalogued here (e.g. "1/2 Levain
# Cheesy Mushroom", "1/2 Levain Green Sandwich", "1/2 Flaguette Kebab de
# boeuf (sauce Tzatziki)" -- all real, priced items on the official
# list, just not yet spotted on a live Altius/Brasserie John's menu)
# are included anyway so they price correctly the moment they appear.
SANDWICH_PRICES = {
    # 01.1 Sandwiches végétariens
    "1/2 Levain Cheesy Mushroom": 4.00,
    "1/2 Levain fromage": 3.30,
    "1/2 Levain Green Sandwich": 4.00,
    "1/2 Levain Parmigiana Sandwich": 4.00,
    "1/2 Levain The ultimate egg Sandwich": 4.00,
    "1/2 Levain Tortilla Olé": 4.00,
    "Ciabatta tomate-mozzarella et pesto": 4.00,
    "Petit pain blanc fromage": 2.30,
    # 01.2 Sandwiches végans
    "1/2 Levain Humi (houmous aux légumes locaux grillés)": 4.00,
    "1/2 tranche de pain": 0.25,
    "Petit pain blanc nature": 0.70,
    'Petit pain blanc "Schockelasbotter végan"': 1.85,
    # 01.3 Sandwiches non-végétariens
    "1/2 Flaguette Kebab de boeuf (sauce Tzatziki)": 4.00,
    '1/2 Levain "Great César"': 4.00,
    '1/2 Levain "Pastrami"': 3.30,
    "1/2 Levain jambon cuit": 3.30,
    "1/2 Levain salami": 2.30,
    "Petit pain blanc jambon cuit": 2.30,
    "Petit pain blanc salami": 2.30,
    # 01.4 Sandwiches sans gluten -- every gluten-free variant is the
    # same flat price on the official list ("Mini baguette sans gluten
    # et ses garnitures"), regardless of filling.
    'Mini baguette sans gluten "Schockelasbotter végan"': 4.00,
    "Mini baguette sans gluten fromage": 4.00,
    "Mini baguette sans gluten jambon cuit": 4.00,
    "Mini baguette sans gluten salami": 4.00,
}


def compute_formula_total(line_items: list[dict]) -> dict:
    """line_items: recalculate_order()'s line items (each has `category`,
    `name`, and `quantity`; category is Restopolis's raw, e.g.
    "Non-végétarien").

    Returns:
        {"formula_count": int, "main_count": int, "starter_count": int,
         "dessert_count": int, "sandwich_count": int, "snack_count": int,
         "total": float | None, "reason": str | None}

    `total` is the combined meal-bundle + snack + sandwich total, or
    `None` when formula_count is 0 (nothing priced at all) OR when the
    selection includes a starter or dessert with no main dish at all
    (`reason` = "no_main_dish"). Snacks and sandwiches never block: a
    snack/sandwich alongside an unpriceable meal-formula combination
    still contributes nothing when `reason` is set, matching the
    pre-existing binary total-or-reason contract the frontend expects.
    """
    main_qty = sum(it["quantity"] for it in line_items if it["category"] in MAIN_CATEGORIES)
    starter_qty = sum(it["quantity"] for it in line_items if it["category"] in STARTER_CATEGORIES)
    dessert_qty = sum(it["quantity"] for it in line_items if it["category"] in DESSERT_CATEGORIES)
    sandwich_qty = sum(it["quantity"] for it in line_items if it["category"] in SANDWICH_CATEGORIES)
    snack_qty = sum(it["quantity"] for it in line_items if it["category"] in SNACK_CATEGORIES)
    formula_count = main_qty + starter_qty + dessert_qty + sandwich_qty + snack_qty

    result = {
        "formula_count": formula_count,
        "main_count": main_qty,
        "starter_count": starter_qty,
        "dessert_count": dessert_qty,
        "sandwich_count": sandwich_qty,
        "snack_count": snack_qty,
        "total": None,
        "reason": None,
    }

    if formula_count == 0:
        return result

    if main_qty == 0 and (starter_qty > 0 or dessert_qty > 0):
        result["reason"] = "no_main_dish"
        return result

    # Full tier first: pair each main with BOTH a starter AND a dessert,
    # as many times as all three allow. Then the partial tier: pair
    # whatever mains are left with EITHER a remaining starter OR a
    # remaining dessert (Formule 2's "OR" -- either alone upgrades the
    # tier the same amount). Whatever mains still have neither price as
    # Formule 3 alone.
    full_qty = min(main_qty, starter_qty, dessert_qty)
    remaining_main = main_qty - full_qty
    remaining_starter = starter_qty - full_qty
    remaining_dessert = dessert_qty - full_qty

    paired_with_starter = min(remaining_main, remaining_starter)
    remaining_main -= paired_with_starter
    paired_with_dessert = min(remaining_main, remaining_dessert)
    remaining_main -= paired_with_dessert
    partial_qty = paired_with_starter + paired_with_dessert
    plain_qty = remaining_main

    meal_total = (
        full_qty * MEAL_TIER_PRICES["main_starter_dessert"]
        + partial_qty * MEAL_TIER_PRICES["main_starter"]
        + plain_qty * MEAL_TIER_PRICES["main"]
    )
    snack_total = snack_qty * SNACK_PRICE
    sandwich_total = sum(
        SANDWICH_PRICES[it["name"]] * it["quantity"]
        for it in line_items
        if it["category"] in SANDWICH_CATEGORIES and it["name"] in SANDWICH_PRICES
    )

    grand_total = meal_total + snack_total + sandwich_total
    # Can genuinely be 0 here despite formula_count > 0: e.g. a cart
    # containing ONLY a sandwich whose exact name isn't in
    # SANDWICH_PRICES (no main dish either, so meal_total is also 0).
    # That means nothing was actually priced -- the total must read as
    # "we don't have a price for this" (None), not a misleading
    # EUR 0.00 that would imply the order is free.
    result["total"] = round(grand_total, 2) if grand_total > 0 else None
    return result
