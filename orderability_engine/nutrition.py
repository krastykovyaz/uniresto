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


# ---------------------------------------------------------------------------
# Typical-portion estimate: a range for dishes whose weight Restopolis does not publish
# ---------------------------------------------------------------------------
#
# The weight-based estimate above stays exactly as it was: it needs a published weight and says nothing without
# one. Most hot dishes have none ("Chipolatas rôties", "Strudel ...", a wrap), so for those -- and ONLY those --
# this adds a clearly separate, clearly rougher number: a typical portion of that kind of dish times a generic
# calorie density, shown as a RANGE ("about 650-800 kcal") and labelled "typical portion". It lives in its own
# fields (calories_typical_low/high), never in `calories`, so the calorie filter and Smart Lunch -- which only
# trust a known value -- do not start acting on a guess.
#
# The densities are generic reference values rounded to 5 (the same kind of figures as the table above);
# the portions are ordinary canteen portions of THAT one item (mains and sides are separate items on the menu).
# Nothing here is Restopolis data and it is no medical or dietary advice.

# Foods the table above doesn't know, matched like it (whole words, longest match wins) but tolerant of a plural.
_TYPICAL_EXTRA: list[tuple[list[str], str, float]] = [
    (["quiche", "tourte", "feuillete", "feuilleté", "strudel", "samossa", "samosa", "bouchee", "bouchée", "pizza"],
     "savory_pastry", 270),
    (["roastbeef", "roast beef", "rosbif", "pastrami", "chipolata", "merguez", "cordon bleu", "escalope",
      "schnitzel", "kottbullar", "köttbullar", "boulette", "burger", "steakhouse"], "red_meat", 235),
    (["paella", "paëlla", "risotto"], "rice_dish", 155),
    (["wrap", "tortilla", "panini", "kebab", "burrito", "fajita"], "bread_savory", 230),
    (["fish and chips", "fish & chips"], "fried_fish", 230),
    (["chili", "curry", "ragout", "ragoût", "bolognaise", "bolognese", "tajine", "gyros", "goulash"], "stew", 120),
    (["salad'bar", "salad bar", "salad", "buddha bowl", "bowl"], "composed_salad", 90),
    (["creme brulee", "crème brûlée", "panna cotta", "tiramisu", "banaboom", "beignet", "crumble"], "dessert", 300),
    (["creme de", "crème de"], "soup", 55),
    (["potiron", "oignon", "poireau", "epinard", "épinard", "navet", "celeri", "céleri", "fenouil",
      "romanesco", "choux", "haricot", "champignon", "mais", "maïs"], "vegetable", 40),
]

# Typical portion in grams of the ITEM as listed, by what it is. Keys of the first dict are food types; the second
# dict is the fallback by menu category when the name says nothing.
_PORTION_BY_TYPE = {
    "red_meat": 150, "poultry": 150, "fish_seafood": 150, "plant_protein": 150, "egg": 120,
    "stew": 300, "fried_fish": 250, "rice_dish": 300, "savory_pastry": 190, "pasta": 300, "bread_savory": 230,
    "potato": 200, "grain": 180, "legume": 170, "vegetable": 150, "soup": 250, "composed_salad": 200,
    "dessert": 110, "fruit": 150, "ice_cream": 100, "dairy": 125, "fresh_cheese": 125, "cheese": 30,
}
_PORTION_BY_CATEGORY = {
    "Entrée": (130, 110), "Végétarien": (250, 170), "Végan": (250, 170), "Non-végétarien": (250, 190), "Pasta": (320, 155),
    "Féculents": (180, 130), "Légumes": (150, 50), "Dessert": (110, 260), "Snack à emporter": (260, 180),
}  # category -> (grams, kcal per 100 g)
_TYPICAL_CATEGORIES = set(_PORTION_BY_CATEGORY)
# A range, not a point: the same dish is served in different amounts, with different amounts of butter/oil.
TYPICAL_SPREAD = 0.25


def _match_extra(name: str) -> tuple[str, float] | None:
    normalized = _normalize(name)
    best: tuple[str, float, str] | None = None
    for keywords, food_type, kcal_per_100 in _TYPICAL_EXTRA:
        for kw in keywords:
            normalized_kw = _normalize(kw)
            if re.search(r"\b" + re.escape(normalized_kw) + r"(?:s|x)?\b", normalized):
                if best is None or len(normalized_kw) > len(best[2]):
                    best = (food_type, kcal_per_100, normalized_kw)
    return (best[0], best[1]) if best else None


def _classify_typical(name: str) -> tuple[str, float] | None:
    """The dish's food type and density. The part before the first comma is the dish itself ("Chipolatas rôties");
    what follows is sauce and side ("jus réduit", "dip yaourt"), which must not decide what the dish is -- so the
    head is tried first (extra table, then the main one), and only then the whole name."""
    head = name.split(",", 1)[0]
    for text in (head, name):
        found = _match_extra(text) or classify_food_type(text)
        if found is not None:
            return found
    return None


def _round10(value: float) -> int:
    return int(round(value / 10.0) * 10)


def estimate_typical(name: str, category: str) -> dict | None:
    """{"low", "high", "portion_g", "food_type"} for a dish with no published weight, or None when the item is not
    one this applies to (a drink, a packaged product, anything outside the daily categories). Rounded to 10 kcal."""
    if category.startswith("01."):  # the sandwich counter: one ordinary sandwich
        grams, density, food_type = 190, 250.0, "bread_savory"
    elif category.startswith("03."):  # house cakes and cookies
        grams, density, food_type = 90, 420.0, "dessert"
    elif category in _TYPICAL_CATEGORIES:
        default_grams, default_density = _PORTION_BY_CATEGORY[category]
        match = _classify_typical(name)
        if match is None:
            grams, density, food_type = default_grams, float(default_density), None
        else:
            food_type, density = match[0], match[1]
            grams = _PORTION_BY_TYPE.get(food_type, default_grams)
    else:
        return None
    middle = grams * density / 100.0
    return {
        "low": _round10(middle * (1 - TYPICAL_SPREAD)),
        "high": _round10(middle * (1 + TYPICAL_SPREAD)),
        "portion_g": grams,
        "food_type": food_type,
    }
