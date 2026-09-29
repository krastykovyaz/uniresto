"""OUR OWN meal-formula pricing rule -- NOT Restopolis data.

Restopolis's public Menu page never exposes a price at all (verified,
see README.md Part 3 §21) -- every scraped `MenuItem.price` is always
`None`. This module is a *separate*, explicitly non-Restopolis pricing
rule: these are the REAL, OFFICIAL Restopolis "Food4Future" price lists
for Campus Kirchberg (2026/27 tariffs, effective 01.09.2026), covering
BOTH real tiers the same lists carry -- "adultes" (staff/professor) and
"apprenants" (student). `compute_formula_total()` defaults to adultes
(the tier the app itself charges/displays everywhere a customer sees a
single number) but takes an explicit `tier` argument so a caller that
genuinely needs both at once (the delivery-notification email, Part
52+, which shows a courier/admin both prices side by side) can ask for
either without duplicating this module's whole pairing algorithm. The
"visiteurs" (visitor) tier the same lists also carry is not covered --
nothing in this app is ever priced for a visitor.

THE MEAL FORMULA (dine-in "RESTAURANT" price list, Formules 1-3):

                                                        adulte   apprenant
    Formule 3: main dish alone                       -> EUR 6.70 / 3.70
    Formule 2: main + starter/salad, OR main+dessert -> EUR 7.70 / 4.20
    Formule 1: main + starter/salad + dessert        -> EUR 8.70 / 4.70

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
one Formule 2 meal and one Formule 3 meal, not both at the upgraded tier.

SNACK À EMPORTER (salads/wraps -- Restopolis's own category, a complete
item on its own, not a side of anything) is priced independently at a
flat rate (EUR 4.80 adulte / 3.50 apprenant) each, from the same
"CAFÉTÉRIA" price list's own "Snack à emporter" line -- never gated on
a main dish being present.

EVERYTHING ELSE PRICED BY NAME (sandwiches, viennoiseries, homemade
cakes/muffins, takeaway soup/salads, fruit, the daily pastry, hot
drinks, cold drinks, and packaging) is ALSO priced independently of the
meal formula, one real per-item price each -- transcribed directly from
the same official "CAFÉTÉRIA"/"RESTAURANT" price lists, never one flat
rate per category. See NAME_PRICED_GROUPS/NAME_PRICED_GROUPS_APPRENANT
below. Several of these categories (viennoiseries, homemade cakes,
reusable/single-use packaging, Thermo Café, edible cups/spoons) turned
out to be priced IDENTICALLY at both tiers on the official list -- those
categories deliberately reuse the exact same price table for both,
rather than a duplicated-but-identical second one. An item whose exact
name isn't in its category's price table (the real menu occasionally
carries one not yet seen and catalogued here) is simply left out of the
total rather than guessed at -- same "never invent a price" rule as
everywhere else in this module.

Two categories (Féculents/starches, Légumes/vegetables) still ride
along free with any main dish -- see INCLUDED_SIDE_CATEGORIES. Laitages
(dairy) are priced from the official 2026/27 "LISTE DE PRIX" (Cafétéria,
apprenants / adultes / visiteurs columns): the lines the list leaves blank
for a tier ("/" -- the apprenants column of the organic milk) or only marks
"*" (the official
"Schoulmëllechprogramm" price, no number given -- chocolate milk for
apprenants) are simply absent from that tier's table, i.e. unpriced there,
never guessed. Glaces (ice cream) still have NO price: that official list
has no ice cream section at all.
"""

from __future__ import annotations

import re

# Restopolis sometimes slots a seasonal name into a dish ('Mini muesli maison
# "Douceur d'automne" 150 g') where the official price list has the plain
# 'Mini muesli maison 150 g'. Price lookups try the exact name first (so
# names that legitimately contain quotes, like 'Banane "commerce
# équitable"', still match as written), then the name with any quoted
# segment removed.
_QUOTED_SEGMENT = re.compile(r'\s*[«“"][^»”"]*[»”"]')


def price_for_name(prices: dict, name: str) -> float | None:
    if name in prices:
        return prices[name]
    return prices.get(_QUOTED_SEGMENT.sub("", name))


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
LAITAGES_CATEGORIES = {"05. Laitages"}
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
MEAL_TIER_PRICES_APPRENANT = {
    "main": 3.70,
    "main_starter": 4.20,
    "main_starter_dessert": 4.70,
}
SNACK_PRICE = 4.80
SNACK_PRICE_APPRENANT = 3.50

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
SANDWICH_PRICES_APPRENANT = {
    "1/2 Levain Cheesy Mushroom": 3.70,
    "1/2 Levain fromage": 3.15,
    "1/2 Levain Green Sandwich": 3.70,
    "1/2 Levain Parmigiana Sandwich": 3.70,
    "1/2 Levain The ultimate egg Sandwich": 3.70,
    "1/2 Levain Tortilla Olé": 3.70,
    "Ciabatta tomate-mozzarella et pesto": 3.70,
    "Petit pain blanc fromage": 2.20,
    "1/2 Levain Humi (houmous aux légumes locaux grillés)": 3.70,
    "1/2 tranche de pain": 0.25,
    "Petit pain blanc nature": 0.70,
    'Petit pain blanc "Schockelasbotter végan"': 1.75,
    "1/2 Flaguette Kebab de boeuf (sauce Tzatziki)": 3.70,
    '1/2 Levain "Great César"': 3.70,
    '1/2 Levain "Pastrami"': 3.15,
    "1/2 Levain jambon cuit": 3.15,
    "1/2 Levain salami": 2.20,
    "Petit pain blanc jambon cuit": 2.20,
    "Petit pain blanc salami": 2.20,
    'Mini baguette sans gluten "Schockelasbotter végan"': 3.70,
    "Mini baguette sans gluten fromage": 3.70,
    "Mini baguette sans gluten jambon cuit": 3.70,
    "Mini baguette sans gluten salami": 3.70,
}

# All flat: every Viennoiserie is priced the same across apprenants/
# adultes/visiteurs on the official list (unlike sandwiches/meals, which
# vary by tier) -- verified directly off a clean, head-on photo of the
# price list, not assumed. No separate apprenant table: the apprenant
# tier reuses this exact dict (see NAME_PRICED_GROUPS_APPRENANT).
VIENNOISERIE_PRICES = {
    "Bretzel salé 80 g": 1.61,
    "Croissant 50 g": 1.58,
    "Croissant fourré 70 g": 1.77,
    "Huit 80 g": 1.81,
    "Pain au chocolat 70 g": 1.68,
    "Poche aux pommes 80 g": 1.74,
    "Streusel 80 g": 1.54,
}

# Also flat across tiers -- same "reuses the same dict" note as
# VIENNOISERIE_PRICES above. "Banaboom" and "Dark Secret" aren't in the
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
TAKEAWAY_VITAMIN_PRICES_APPRENANT = {
    "Mini salades 150 g": 2.50,
    "Petit bol de potage": 1.90,
}

FRUIT_PRICES = {
    'Banane "commerce équitable"': 1.40,
    "Fruit frais entier": 1.40,
    "Mini fruits découpés mélangés/non-mélangés 150 g": 3.50,
}
FRUIT_PRICES_APPRENANT = {
    'Banane "commerce équitable"': 1.25,
    "Fruit frais entier": 1.25,
    "Mini fruits découpés mélangés/non-mélangés 150 g": 2.50,
}

# Official 2026/27 Cafétéria list, "LAITAGES" block. Adultes column. The
# free school milk ("gratuit") is "/" there -- not sold to adults at all --
# but it is the very same Lait Luxlait BIO 0,25 l pack, so the app prices
# it like the regular one (0.95) for everyone above the school programme:
# the owner's call, not a number on the list.
LAITAGES_PRICES = {
    "Mini fromage frais avec coulis de fruits de saison 150 g": 3.50,
    "Mini muesli maison 150 g": 3.50,
    "Lait chocolaté Luxlait 0,25 l Tétra Pack": 1.10,
    "Lait Luxlait BIO 0,25 l Tétra Pack": 0.95,
    "Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)": 0.95,
    "Yaourt aux fruits Luxlait 125 g": 1.35,
    "Yaourt nature Luxlait 125 g": 1.15,
}
# Apprenants column. Absent on purpose: the chocolate milk (list says only
# "*" = the official Schoulmëllechprogramm price, no number) and the
# organic milk ("/").
LAITAGES_PRICES_APPRENANT = {
    "Mini fromage frais avec coulis de fruits de saison 150 g": 2.50,
    "Mini muesli maison 150 g": 2.50,
    "Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)": 0.00,
    "Yaourt aux fruits Luxlait 125 g": 1.25,
    "Yaourt nature Luxlait 125 g": 1.05,
}

PASTRY_PRICES = {
    "Dessert du Jour": 2.20,
}
PASTRY_PRICES_APPRENANT = {
    "Dessert du Jour": 1.90,
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
COLD_DRINK_PRICES_APPRENANT = {
    "Lodyss fine pétillante 0,25 l btl": 0.75,
    "Lodyss plate 0,25 l btl": 0.75,
    "Rosport Blue 0,25 l btl": 0.75,
    "Rosport Blue 0,50 l btl": 1.20,
    "Rosport Blue 0,50 l non consigné": 1.30,
    "Rosport Blue 1,00 l btl": 2.65,
    "Rosport mat Menthe 0,50 l non consigné": 1.60,
    "Rosport mat Zitroun 0,50 l non consigné": 1.60,
    "Viva 0,25 l btl": 0.75,
    "Viva 0,50 l btl": 1.20,
    "Viva 0,50 l non consigné": 1.30,
    "Viva 1,00 l btl": 2.65,
    "Lëtzbuerger Drauwejus 0,25 l btl": 1.50,
    "Ramborn Apple & Quince Juice 0,33 l btl": 1.60,
    "Ramborn Apple Juice 0,33 btl": 1.60,
    "Ramborn Apple Soda 0,33 l btl": 1.60,
    "Ramborn Pear Apple Juice 0,33 l btl": 1.60,
    "Rosport Sunny Citron-Citron vert 0,50 l non consigné": 1.60,
    "Rosport Sunny Pêche 0,50 l non consigné": 1.60,
    "Coca Cola 0,20 l btl": 1.60,
    "Coca Cola 0,50 l non consigné": 2.00,
    "Fuze Tea - Black Tea Pêche/Hibiscus 0,20 l btl": 1.60,
    "Fuze Tea - Black Tea Pêche/Hibiscus 0,40 l non consigné": 2.00,
    "Lët'z kola 0,33 btl": 1.60,
    "Lët'z limo lemon & lime 0,33 btl": 1.60,
    "Lët'z limo orange 0,33 btl": 1.60,
    "Rosport Pom's 0,50 l non consigné": 2.00,
    "Rosport Wave 0,50 l non-consigné": 2.00,
}

# Matches the "Boissons chaudes" adultes column on both official lists
# exactly (cross-checked, identical on both -- hot drinks aren't
# restaurant-specific). Thermo Café is priced IDENTICALLY at both tiers
# on the official list (verified on both sheets) -- kept as a single
# shared value in both tables below rather than treated as an oversight.
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
HOT_DRINK_PRICES_APPRENANT = {
    'Café "commerce équitable"': 1.65,
    "Cappuccino": 1.95,
    'Chocolat chaud "Commerce équitable"': 1.65,
    "Espresso": 1.65,
    "Espresso double": 1.95,
    'Thé "commerce équitable"': 1.45,
    "Thermo Café 1,00 l": 5.00,
    "Thermo Café 1,50 l": 7.50,
    "Tisane": 1.45,
}

# ECOBOX deposits are genuinely negative for the "Remboursement" (refund)
# lines on the official list -- a customer returning a box gets money
# back, so that line reduces the order total rather than adding to it,
# same as the real price sheet states. Every item in this category is
# priced identically at both tiers (only the visiteurs tier differs) --
# same shared-dict note as VIENNOISERIE_PRICES above.
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

# Also priced identically at both tiers -- same shared-dict note as above.
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
# `label` is a short, stable English name for this group used ONLY by
# category_breakdown() below (e.g. in the delivery-notification email);
# it is NOT a translation and never shown in the customer-facing app UI,
# which uses static/i18n.js's categoryLabel() against the real raw
# Restopolis category strings instead.
NAME_PRICED_GROUPS = [
    ("sandwiches", SANDWICH_CATEGORIES, SANDWICH_PRICES),
    ("viennoiseries", VIENNOISERIE_CATEGORIES, VIENNOISERIE_PRICES),
    ("homemade cakes", HOMEMADE_CAKE_CATEGORIES, HOMEMADE_CAKE_PRICES),
    ("takeaway vitamins", TAKEAWAY_VITAMIN_CATEGORIES, TAKEAWAY_VITAMIN_PRICES),
    ("fruit", FRUIT_CATEGORIES, FRUIT_PRICES),
    ("dairy", LAITAGES_CATEGORIES, LAITAGES_PRICES),
    ("pastry", PASTRY_CATEGORIES, PASTRY_PRICES),
    ("cold drinks", COLD_DRINK_CATEGORIES, COLD_DRINK_PRICES),
    ("hot drinks", HOT_DRINK_CATEGORIES, HOT_DRINK_PRICES),
    ("reusable packaging", REUSABLE_PACKAGING_CATEGORIES, REUSABLE_PACKAGING_PRICES),
    ("single-use packaging", SINGLE_USE_PACKAGING_CATEGORIES, SINGLE_USE_PACKAGING_PRICES),
]
NAME_PRICED_GROUPS_APPRENANT = [
    ("sandwiches", SANDWICH_CATEGORIES, SANDWICH_PRICES_APPRENANT),
    ("viennoiseries", VIENNOISERIE_CATEGORIES, VIENNOISERIE_PRICES),
    ("homemade cakes", HOMEMADE_CAKE_CATEGORIES, HOMEMADE_CAKE_PRICES),
    ("takeaway vitamins", TAKEAWAY_VITAMIN_CATEGORIES, TAKEAWAY_VITAMIN_PRICES_APPRENANT),
    ("fruit", FRUIT_CATEGORIES, FRUIT_PRICES_APPRENANT),
    ("dairy", LAITAGES_CATEGORIES, LAITAGES_PRICES_APPRENANT),
    ("pastry", PASTRY_CATEGORIES, PASTRY_PRICES_APPRENANT),
    ("cold drinks", COLD_DRINK_CATEGORIES, COLD_DRINK_PRICES_APPRENANT),
    ("hot drinks", HOT_DRINK_CATEGORIES, HOT_DRINK_PRICES_APPRENANT),
    ("reusable packaging", REUSABLE_PACKAGING_CATEGORIES, REUSABLE_PACKAGING_PRICES),
    ("single-use packaging", SINGLE_USE_PACKAGING_CATEGORIES, SINGLE_USE_PACKAGING_PRICES),
]


def _tier_tables(tier: str) -> tuple[dict, float, list]:
    if tier == "adulte":
        return MEAL_TIER_PRICES, SNACK_PRICE, NAME_PRICED_GROUPS
    if tier == "apprenant":
        return MEAL_TIER_PRICES_APPRENANT, SNACK_PRICE_APPRENANT, NAME_PRICED_GROUPS_APPRENANT
    raise ValueError(f"tier must be 'adulte' or 'apprenant', got {tier!r}")


def compute_formula_total(line_items: list[dict], tier: str = "adulte") -> dict:
    """line_items: recalculate_order()'s line items (each has `category`,
    `name`, and `quantity`; category is Restopolis's raw, e.g.
    "Non-végétarien"). `tier`: "adulte" (default -- staff/professor, the
    one the app itself charges/displays everywhere else) or "apprenant"
    (student) -- see this module's docstring for why both exist.

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
    meal_tier_prices, snack_price, name_priced_groups = _tier_tables(tier)

    main_qty = sum(it["quantity"] for it in line_items if it["category"] in MAIN_CATEGORIES)
    starter_qty = sum(it["quantity"] for it in line_items if it["category"] in STARTER_CATEGORIES)
    dessert_qty = sum(it["quantity"] for it in line_items if it["category"] in DESSERT_CATEGORIES)
    sandwich_qty = sum(it["quantity"] for it in line_items if it["category"] in SANDWICH_CATEGORIES)
    snack_qty = sum(it["quantity"] for it in line_items if it["category"] in SNACK_CATEGORIES)
    other_items_qty = sum(
        it["quantity"]
        for it in line_items
        if any(it["category"] in categories for _, categories, _ in name_priced_groups) and it["category"] not in SANDWICH_CATEGORIES
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
        full_qty * meal_tier_prices["main_starter_dessert"]
        + partial_qty * meal_tier_prices["main_starter"]
        + plain_qty * meal_tier_prices["main"]
    )
    snack_total = snack_qty * snack_price
    name_priced_total = sum(
        price_for_name(prices, it["name"]) * it["quantity"]
        for _, categories, prices in name_priced_groups
        for it in line_items
        if it["category"] in categories and price_for_name(prices, it["name"]) is not None
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


def category_breakdown(line_items: list[dict]) -> list[dict]:
    """A per-category subtotal at BOTH tiers, for the delivery
    notification email (Part 52+) -- never shown as one lump total
    there, so a courier/admin can see what's actually in the order group
    by group, same as the admin Telegram ping already groups items by
    category (see telegram_notify.py). One entry per real Restopolis
    category present in the order, PLUS one combined "Meal formula"
    entry for main/starter/dessert together (those three don't have a
    stable per-item price on their own -- only the whole combination
    does, see compute_formula_total()'s pairing algorithm) when at least
    one of them is present. Order: meal formula first (if any), then
    every other category in first-seen order. A category with no price
    at either tier for what's actually in the cart (e.g. an unmapped
    item, or Laitages/Glaces, never priced at all) is skipped entirely
    rather than shown as a fabricated EUR 0.00 row.

    Returns: [{"category": str, "adulte_total": float, "apprenant_total":
    float}, ...] -- "category" is "Meal formula" for the combined entry,
    otherwise the raw Restopolis category string (the caller translates
    it for display if needed, same as everywhere else in this app)."""
    entries: list[dict] = []

    meal_categories = MAIN_CATEGORIES | STARTER_CATEGORIES | DESSERT_CATEGORIES
    if any(it["category"] in meal_categories for it in line_items):
        adulte = compute_formula_total(line_items, tier="adulte")
        apprenant = compute_formula_total(line_items, tier="apprenant")
        # Only the meal-formula's OWN contribution, not snacks/name-priced
        # groups also folded into compute_formula_total()'s total -- those
        # get their own entries below instead.
        adulte_meal = (adulte["total"] or 0) - _non_meal_total(line_items, "adulte")
        apprenant_meal = (apprenant["total"] or 0) - _non_meal_total(line_items, "apprenant")
        if adulte["reason"] is None and (adulte_meal > 0 or apprenant_meal > 0):
            entries.append(
                {"category": "Meal formula", "adulte_total": round(adulte_meal, 2), "apprenant_total": round(apprenant_meal, 2)}
            )

    seen_categories: list[str] = []
    for it in line_items:
        if it["category"] in meal_categories or it["category"] in INCLUDED_SIDE_CATEGORIES:
            continue
        if it["category"] not in seen_categories:
            seen_categories.append(it["category"])

    for category in seen_categories:
        category_items = [it for it in line_items if it["category"] == category]
        adulte_total = _name_priced_total_for(category_items, "adulte")
        apprenant_total = _name_priced_total_for(category_items, "apprenant")
        if adulte_total > 0 or apprenant_total > 0:
            entries.append({"category": category, "adulte_total": round(adulte_total, 2), "apprenant_total": round(apprenant_total, 2)})

    return entries


def _non_meal_total(line_items: list[dict], tier: str) -> float:
    _, snack_price, name_priced_groups = _tier_tables(tier)
    snack_qty = sum(it["quantity"] for it in line_items if it["category"] in SNACK_CATEGORIES)
    name_priced_total = sum(
        price_for_name(prices, it["name"]) * it["quantity"]
        for _, categories, prices in name_priced_groups
        for it in line_items
        if it["category"] in categories and price_for_name(prices, it["name"]) is not None
    )
    return snack_qty * snack_price + name_priced_total


def _name_priced_total_for(category_items: list[dict], tier: str) -> float:
    _, snack_price, name_priced_groups = _tier_tables(tier)
    if category_items and category_items[0]["category"] in SNACK_CATEGORIES:
        return sum(it["quantity"] for it in category_items) * snack_price
    total = 0.0
    for _, categories, prices in name_priced_groups:
        for it in category_items:
            if it["category"] in categories and price_for_name(prices, it["name"]) is not None:
                total += price_for_name(prices, it["name"]) * it["quantity"]
    return total
