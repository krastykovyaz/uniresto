"""Approximate calorie estimation -- NOT Restopolis data, and not exact.

Restopolis exposes zero nutrition/calorie data anywhere on the public
Menu page (verified directly: zero occurrences of "kcal", "calor",
"nutrit", "energ", "kJ" in the raw HTML, for both restaurants). This
module is the "separate, explicitly trusted nutrition source" needed to
estimate calories at all, per this feature's own ground rule: never
invent a number with no basis. Two real things ARE available and used
here:

  1. A dish's REAL, Restopolis-scraped weight (`weight_value`/`weight_unit`
     -- see restopolis/weight.py). Without a known weight there is
     nothing to multiply a density by, so no estimate is produced --
     never a fabricated default.
  2. A REAL, public nutritional-science reference: approximate calorie
     density (kcal per 100 g/ml) for common food types, the same kind of
     generic reference figures a standard calorie-counting app uses for
     an unbranded "grilled chicken" or "boiled potatoes" entry (broadly
     consistent with USDA FoodData Central / EU generic food composition
     tables, rounded to the nearest 5). 1 ml is treated as ~1 g for this
     purpose, which is fine at this level of approximation.

The food TYPE itself is guessed from the dish's raw (French) name via
keyword matching -- inherently approximate, sometimes wrong for a
compound or unusual dish name. Matching is done on WHOLE WORDS (regex
word boundaries), not naive substrings: an earlier version of this table
used plain substring checks and got real, verified-wrong results from
it -- "Cornet **Lux**LAIT" (an ice cream brand name) and "Rosport
**men**THE" (mint-flavoured water) both silently matched "lait"/"the"
(milk/tea) purely because those letters happened to appear inside a
longer, unrelated word. Word-boundary matching fixes both; where a table
entry still needs to match a multi-word phrase (e.g. "fromage frais"),
the whole phrase is compiled as its own boundary-anchored pattern.

Every result this module produces is therefore always `is_estimated=True`
and must be displayed as "≈ estimated", never presented as a precise or
Restopolis-sourced fact -- see static/nutrition.js's mirror and
static/i18n.js's "estimated"/"nutritionNotAvailable" strings for how the
frontend labels it.

No medical/health claims are made or implied by this module or its
callers (see the Smart Lunch feature, which explicitly avoids ranking
results as "healthiest").
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Reference calorie density table: (keywords, food_type, kcal_per_100).
# ONE unified table regardless of solid/liquid -- an earlier version
# split solid vs. liquid by unit alone and routed ml-labelled ice cream
# ("Glace ... 100 ml", "Cornet Luxlait 130 ml") into the liquid/beverage
# table, where it obviously doesn't belong. Matching is now purely by
# keyword; the unit only decides the weight-vs-volume multiplier.
#
# More specific multi-word entries are listed before the more general
# single-word ones they'd otherwise be shadowed by (longest match wins
# regardless of table order -- see classify_food_type -- so this
# ordering is for human readability, not correctness).
# ---------------------------------------------------------------------------

_TABLE: list[tuple[list[str], str, float]] = [
    # -- Protein / mains --
    (["quorn", "tofu"], "plant_protein", 140),
    (["boeuf", "bœuf", "steak", "roti de porc", "rôti de porc", "porc", "veau", "agneau",
      "saucisse", "jambon", "salami", "bacon", "chorizo"], "red_meat", 220),
    (["poulet", "dinde", "volaille", "canard", "nuggets", "renuggets"], "poultry", 190),
    (["poisson", "saumon", "thon", "cabillaud", "truite", "merlan", "crevette", "colin"], "fish_seafood", 150),
    (["oeuf", "œuf", "omelette"], "egg", 155),
    # -- Starches --
    (["pomme de terre", "pommes de terre", "frite", "frites", "puree", "purée", "gratin dauphinois"], "potato", 95),
    (["riz", "quinoa", "boulgour", "semoule", "couscous", "polenta"], "grain", 135),
    (["pate", "pâte", "pates", "pâtes", "linguine", "spaghetti", "penne", "lasagne",
      "cannelloni", "nouilles", "gnocchi"], "pasta", 155),
    (["lentille", "pois chiche", "haricot rouge", "haricot blanc"], "legume", 115),
    # -- Bread / bakery (savory) --
    (["sandwich", "wrap", "baguette", "panini", "burger", "hot-dog", "hot dog"], "bread_savory", 250),
    (["poche aux pommes", "chausson aux pommes"], "pastry_sweet", 260),
    (["croissant", "pain au chocolat", "viennoiserie", "brioche", "muffin", "bretzel"], "pastry_savory_sweet", 350),
    # -- Sweets / desserts / ice cream -- listed BEFORE fruit/vegetable
    # below: these keywords name the dish's actual TYPE (a cornet or a
    # glace *is* an ice cream), whereas fruit words like "fraise"/
    # "vanille" often only appear as a flavor list in parentheses (e.g.
    # "Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)"). On a same-
    # length tie between a type keyword and a flavor keyword, whichever
    # is found first wins (see classify_food_type) -- so the dish-type
    # keywords need to be checked first.
    (["glace", "cornet", "dame blanche", "esquimau", "cassata"], "ice_cream", 200),
    (["gateau", "gâteau", "tarte", "cookie", "biscuit", "flan", "mousse",
      "brest", "eclair", "éclair", "cheesecake", "brownie", "cheescake",
      "streusel", "paris"], "dessert", 320),
    # -- Vegetables / salads / soups --
    (["salade", "crudites", "crudités", "mezze", "mezzés"], "composed_salad", 90),
    (["soupe", "potage", "bouillon", "veloute", "velouté", "minestrone", "gaspacho"], "soup", 45),
    (["legume", "légume", "carotte", "courgette", "brocoli", "epinard", "épinard",
      "chou", "tomate", "poivron", "aubergine", "champignon", "haricot vert",
      "petit pois", "betterave"], "vegetable", 35),
    (["fruit", "pomme", "banane", "orange", "poire", "fraise", "peche", "pêche",
      "ananas", "raisin"], "fruit", 55),
    # -- Dairy / cheese --
    (["fromage frais", "faisselle"], "fresh_cheese", 90),
    (["fromage", "cheddar", "mozzarella", "emmental", "gruyere", "gruyère", "parmesan"], "cheese", 350),
    (["yaourt", "yogourt"], "dairy", 70),
    # -- Beverages --
    (["eau"], "water", 0),
    (["coca", "soda", "fanta", "sprite", "rosport sunny", "rosport wave"], "soda", 42),
    # "fuze tea"/"black tea"/"iced tea" are longer than fruit-flavor
    # words like "peche" (peach) that appear alongside them as a flavor
    # descriptor (e.g. "Fuze Tea - Black Tea Pêche/Hibiscus"), so the
    # longest-match rule picks the drink type correctly without needing
    # table-order tricks -- unlike the ice-cream/fruit tie above.
    (["fuze tea", "black tea", "iced tea", "ice tea"], "iced_tea", 40),
    (["limo", "drauwejus", "jus"], "juice", 45),
    (["chocolat chaude", "chocolat chaud", "chocolate"], "hot_chocolate", 70),
    (["cafe", "café", "espresso", "cappuccino"], "hot_beverage_coffee", 5),
    (["the", "thé", "tisane"], "hot_beverage_tea", 1),
    (["lait"], "milk", 60),
]


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", without_accents).strip()


def classify_food_type(name: str) -> tuple[str, float] | None:
    """Returns (food_type, kcal_per_100) for the best keyword match in
    the raw (French) dish name, or None if nothing matched -- never a
    default/fallback density.

    Matches whole words/phrases only (`\\b...\\b`), and picks the LONGEST
    matching keyword when more than one matches -- table order must not
    silently decide the result. See the module docstring for two real
    bugs this combination caught and fixed: "Luxlait" (brand name)
    falsely matching "lait" (milk), and "Menthe" (mint) falsely matching
    "the" (tea) -- both only possible with naive substring matching.
    """
    normalized = _normalize(name)

    best: tuple[str, float, str] | None = None  # (food_type, kcal_per_100, matched_keyword)
    for keywords, food_type, kcal_per_100 in _TABLE:
        for kw in keywords:
            normalized_kw = _normalize(kw)
            pattern = r"\b" + re.escape(normalized_kw) + r"\b"
            if re.search(pattern, normalized):
                if best is None or len(normalized_kw) > len(best[2]):
                    best = (food_type, kcal_per_100, normalized_kw)

    return (best[0], best[1]) if best else None


def estimate_calories(name: str, weight_value: float | None, weight_unit: str | None) -> dict:
    """Returns {"calories": float | None, "food_type": str | None,
    "is_estimated": bool}. `calories` is None whenever there's no known
    weight to base an estimate on, or the name doesn't match any known
    food-type keyword -- never a guessed default. `is_estimated` is
    always True when `calories` is not None (there is no "exact" case
    here at all, see module docstring)."""
    if weight_value is None or weight_unit is None:
        return {"calories": None, "food_type": None, "is_estimated": False}
    if weight_unit == "piece":
        # No reliable typical mass for "1 piece" across arbitrary dishes
        # -- would require guessing a weight, which this module never does.
        return {"calories": None, "food_type": None, "is_estimated": False}

    match = classify_food_type(name)
    if match is None:
        return {"calories": None, "food_type": None, "is_estimated": False}

    food_type, kcal_per_100 = match
    grams_or_ml = weight_value * 1000 if weight_unit == "l" else weight_value
    calories = round(kcal_per_100 * grams_or_ml / 100, 1)
    return {"calories": calories, "food_type": food_type, "is_estimated": True}
