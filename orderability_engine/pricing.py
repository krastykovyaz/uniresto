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

EVERYTHING ELSE PRICED BY NAME (sandwiches, viennoiseries, homemade
cakes/muffins, takeaway soup/salads, fruit, the daily pastry, hot
drinks, cold drinks, and packaging) is ALSO priced independently of the
meal formula, one real per-item adultes price each -- transcribed
directly from the same official "CAFÉTÉRIA"/"RESTAURANT" price lists,
never one flat rate per category. See NAME_PRICED_GROUPS below for the
full list of categories this covers and their price tables. An item
whose exact name isn't in its category's price table (the real menu
occasionally carries one not yet seen and catalogued here) is simply
left out of the total rather than guessed at -- same "never invent a
price" rule as everywhere else in this module.

Two categories (Féculents/starches, Légumes/vegetables) still ride
along free with any main dish -- see INCLUDED_SIDE_CATEGORIES -- and
Laitages (dairy -- some lines are subsidy-priced per a "Schoulmëttchprogramm"
notation the source price list doesn't fully spell out) and Glaces
(ice cream -- no price list photo of this section was available) are
still not priced by this module -- real official prices likely exist
for those too, but transcribing them needs a clearer source than what
was available for this pass, not a guess rushed into this one.
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
VIENNOISERIE_CATEGORIES = {"02. Viennoiseries"}
HOMEMADE_CAKE_CATEGORIES = {"03. Gâteaux et cookies maison"}
TAKEAWAY_VITAMIN_CATEGORIES = {"04. Vitamines à emporter"}
FRUIT_CATEGORIES = {"06. Fruits"}
PASTRY_CATEGORIES = {"08. Pâtisserie"}
# The 3 real Restopolis "Boissons froides" (cold drinks) categories --
# water, juice and soda are split into separate raw categories, but all
# priced from the same combined official table below.
COLD_DRINK_CATEGORIES = {
    "10.1 Boissons froides - Eau minérale et pétillante",
    "10.2 Boissons froides - Jus",
    "10.3 Boissons froides - Sodas",
}
HOT_DRINK_CATEGORIES = {"11. Boissons chaudes"}
REUSABLE_PACKAGING_CATEGORIES = {"12.1 Emballages et articles réutilisables"}
SINGLE_USE_PACKAGING_CATEGORIES = {"12.2 Emballages et articles à usage unique"}

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

# All flat: every Viennoiserie is priced the same across apprenants/
# adultes/visiteurs on the official list (unlike sandwiches/meals, which
# vary by tier) -- verified directly off a clean, head-on photo of the
# price list, not assumed.
VIENNOISERIE_PRICES = {
    "Bretzel salé 80 g": 1.61,
    "Croissant 50 g": 1.58,
    "Croissant fourré 70 g": 1.77,
    "Huit 80 g": 1.81,
    "Pain au chocolat 70 g": 1.68,
    "Poche aux pommes 80 g": 1.74,
    "Streusel 80 g": 1.54,
}

# Also flat across tiers. "Banaboom" and "Dark Secret" aren't in the
# live fixture data (data/menus.json) yet but are real, priced items on
# the same official list, alongside the 3 that are -- same "include it
# anyway so it prices correctly the moment it appears" precedent as
# SANDWICH_PRICES above. Dark Secret's own price cell was cut off in
# every available photo; every other item in this category shares one
# flat price, so that same price is used for it too, not a guess at an
# unrelated number.
HOMEMADE_CAKE_PRICES = {
    "Tasty Crunchy": 1.65,
    "Nutchy": 1.65,
    "Crispy Apple": 1.65,
    "Banaboom": 1.65,
    "Dark Secret": 1.65,
}

TAKEAWAY_VITAMIN_PRICES = {
    "Mini salades 150 g": 3.50,
    "Petit bol de potage": 2.20,
}

FRUIT_PRICES = {
    'Banane "commerce équitable"': 1.40,
    "Fruit frais entier": 1.40,
    "Mini fruits découpés mélangés/non-mélangés 150 g": 3.50,
}

PASTRY_PRICES = {
    "Dessert du Jour": 2.20,
}

# Cross-checked across BOTH official lists (the dine-in "RESTAURANT"
# sheet, which sells these by the bottle/"btl", and the "CAFÉTÉRIA"
# sheet, which sells "non consigné" -- no deposit -- versions at
# different sizes/prices) -- every real item name in data/menus.json
# across all 3 cold-drink categories matched exactly one line on one of
# the two sheets, with no ambiguity.
COLD_DRINK_PRICES = {
    # Eau minérale et pétillante
    "Lodyss fine pétillante 0,25 l btl": 0.95,
    "Lodyss plate 0,25 l btl": 0.95,
    "Rosport Blue 0,25 l btl": 0.95,
    "Rosport Blue 0,50 l btl": 1.45,
    "Rosport Blue 0,50 l non consigné": 1.50,
    "Rosport Blue 1,00 l btl": 3.10,
    "Rosport mat Menthe 0,50 l non consigné": 1.80,
    "Rosport mat Zitroun 0,50 l non consigné": 1.80,
    "Viva 0,25 l btl": 0.95,
    "Viva 0,50 l btl": 1.45,
    "Viva 0,50 l non consigné": 1.50,
    "Viva 1,00 l btl": 3.10,
    # Jus
    "Lëtzbuerger Drauwejus 0,25 l btl": 1.70,
    "Ramborn Apple & Quince Juice 0,33 l btl": 1.80,
    "Ramborn Apple Juice 0,33 btl": 1.80,
    "Ramborn Apple Soda 0,33 l btl": 1.80,
    "Ramborn Pear Apple Juice 0,33 l btl": 1.80,
    "Rosport Sunny Citron-Citron vert 0,50 l non consigné": 1.80,
    "Rosport Sunny Pêche 0,50 l non consigné": 1.80,
    # Sodas
    "Coca Cola 0,20 l btl": 1.80,
    "Coca Cola 0,50 l non consigné": 2.20,
    "Fuze Tea - Black Tea Pêche/Hibiscus 0,20 l btl": 1.80,
    "Fuze Tea - Black Tea Pêche/Hibiscus 0,40 l non consigné": 2.20,
    "Lët'z kola 0,33 btl": 1.80,
    "Lët'z limo lemon & lime 0,33 btl": 1.80,
    "Lët'z limo orange 0,33 btl": 1.80,
    "Rosport Pom's 0,50 l non consigné": 2.20,
    "Rosport Wave 0,50 l non-consigné": 2.20,
}

# Matches the "Boissons chaudes" adultes column on both official lists
# exactly (cross-checked, identical on both -- hot drinks aren't
# restaurant-specific).
HOT_DRINK_PRICES = {
    'Café "commerce équitable"': 1.90,
    "Cappuccino": 2.25,
    'Chocolat chaud "Commerce équitable"': 1.90,
    "Espresso": 1.90,
    "Espresso double": 2.25,
    'Thé "commerce équitable"': 1.65,
    "Thermo Café 1,00 l": 5.00,
    "Thermo Café 1,50 l": 7.50,
    "Tisane": 1.65,
}

# ECOBOX deposits are genuinely negative for the "Remboursement" (refund)
# lines on the official list -- a customer returning a box gets money
# back, so that line reduces the order total rather than adding to it,
# same as the real price sheet states.
REUSABLE_PACKAGING_PRICES = {
    "Consigne ECOBOX (500 ml)": 5.00,
    "Consigne ECOBOX (1000 ml)": 5.00,
    "Remboursement Consigne ECOBOX (500 ml)": -5.00,
    "Remboursement Consigne ECOBOX (1000 ml)": -5.00,
    "myFrupstut": 3.00,
    "myCan": 9.00,
    "myKit": 3.00,
    "myNapkin": 2.00,
    "myBento": 9.00,
    "myMug": 5.00,
    "myBowl": 5.00,
    "myMiniBowl": 2.50,
}

SINGLE_USE_PACKAGING_PRICES = {
    "Serviette en papier (à partir de la 2e serviette)": 0.10,
    "Fourchette en bois": 0.20,
    "Barquette pour pâtes/salades à emporter": 0.50,
    "Couvercle pour barquette à emporter": 0.50,
    "Sachet pour sandwiches": 0.10,
    "Gobelet comestible 220 ml": 0.60,
    "Cuillère comestible": 0.15,
}

# Every category priced by exact item name (as opposed to the
# main/starter/dessert meal-formula tiers and the flat SNACK_PRICE) --
# each entry pairs a category set with its own price table, so
# compute_formula_total() can sum across all of them uniformly. A name
# not present in its category's table is left unpriced, never guessed.
NAME_PRICED_GROUPS = [
    (SANDWICH_CATEGORIES, SANDWICH_PRICES),
    (VIENNOISERIE_CATEGORIES, VIENNOISERIE_PRICES),
    (HOMEMADE_CAKE_CATEGORIES, HOMEMADE_CAKE_PRICES),
    (TAKEAWAY_VITAMIN_CATEGORIES, TAKEAWAY_VITAMIN_PRICES),
    (FRUIT_CATEGORIES, FRUIT_PRICES),
    (PASTRY_CATEGORIES, PASTRY_PRICES),
    (COLD_DRINK_CATEGORIES, COLD_DRINK_PRICES),
    (HOT_DRINK_CATEGORIES, HOT_DRINK_PRICES),
    (REUSABLE_PACKAGING_CATEGORIES, REUSABLE_PACKAGING_PRICES),
    (SINGLE_USE_PACKAGING_CATEGORIES, SINGLE_USE_PACKAGING_PRICES),
]


def compute_formula_total(line_items: list[dict]) -> dict:
    """line_items: recalculate_order()'s line items (each has `category`,
    `name`, and `quantity`; category is Restopolis's raw, e.g.
    "Non-végétarien").

    Returns:
        {"formula_count": int, "main_count": int, "starter_count": int,
         "dessert_count": int, "sandwich_count": int, "snack_count": int,
         "other_items_count": int, "total": float | None,
         "reason": str | None}

    `total` is the combined meal-bundle + snack + name-priced-groups
    total (sandwiches, viennoiseries, drinks, packaging, etc -- see
    NAME_PRICED_GROUPS), or `None` when formula_count is 0 (nothing
    priced at all) OR when the selection includes a starter or dessert
    with no main dish at all (`reason` = "no_main_dish"). Snacks and
    every name-priced group never block: alongside an unpriceable
    meal-formula combination they still contribute nothing when
    `reason` is set, matching the pre-existing binary total-or-reason
    contract the frontend expects.
    """
    main_qty = sum(it["quantity"] for it in line_items if it["category"] in MAIN_CATEGORIES)
    starter_qty = sum(it["quantity"] for it in line_items if it["category"] in STARTER_CATEGORIES)
    dessert_qty = sum(it["quantity"] for it in line_items if it["category"] in DESSERT_CATEGORIES)
    sandwich_qty = sum(it["quantity"] for it in line_items if it["category"] in SANDWICH_CATEGORIES)
    snack_qty = sum(it["quantity"] for it in line_items if it["category"] in SNACK_CATEGORIES)
    other_items_qty = sum(
        it["quantity"]
        for it in line_items
        if any(it["category"] in categories for categories, _ in NAME_PRICED_GROUPS) and it["category"] not in SANDWICH_CATEGORIES
    )
    formula_count = main_qty + starter_qty + dessert_qty + sandwich_qty + snack_qty + other_items_qty

    result = {
        "formula_count": formula_count,
        "main_count": main_qty,
        "starter_count": starter_qty,
        "dessert_count": dessert_qty,
        "sandwich_count": sandwich_qty,
        "snack_count": snack_qty,
        "other_items_count": other_items_qty,
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
    name_priced_total = sum(
        prices[it["name"]] * it["quantity"]
        for categories, prices in NAME_PRICED_GROUPS
        for it in line_items
        if it["category"] in categories and it["name"] in prices
    )

    grand_total = meal_total + snack_total + name_priced_total
    # Can genuinely be 0 here despite formula_count > 0: e.g. a cart
    # containing ONLY an item whose exact name isn't in its category's
    # price table (no main dish either, so meal_total is also 0). That
    # means nothing was actually priced -- the total must read as "we
    # don't have a price for this" (None), not a misleading EUR 0.00
    # that would imply the order is free.
    result["total"] = round(grand_total, 2) if grand_total > 0 else None
    return result
