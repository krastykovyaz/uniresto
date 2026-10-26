"""Nutrition facts for the packaged / fixed-composition products on the menu (water, soda, juice, flavoured milk,
ice cream, fresh cheese).

Unlike a cooked dish, a bottle of Coca-Cola or a pot of Luxlait fromage frais is the same every day, so its
nutrition label can be looked up once. The figures below are the values printed on the packaging as recorded in
Open Food Facts (an open, crowd-sourced product database -- barcode in `source`) or, for Rosport, the maker's own
nutrition tables on rosport.com; they are per 100 g or 100 ml
exactly as a label gives them, and every entry says how close the match is:

  "label"   -- the very product on the menu (same brand and variety)
  "similar" -- the same brand's closest product (named in `source`); the menu item has no entry of its own
  "typical" -- no entry for this brand: a typical value for that KIND of drink, not this product

Nothing here is Restopolis data, it is not medical or dietary advice, and a missing product means "not looked up
or not found" -- never a guessed zero. Products whose variety is ambiguous on the menu (for example plain
"Luxlait BIO" milk: semi-skimmed 47 kcal vs whole 65 kcal) are deliberately left out until someone reads the carton.
"""

from __future__ import annotations

import re

from orderability_engine.nutrition import _normalize

_FIELDS = ("kcal", "fat", "saturates", "carbs", "sugars", "protein", "salt")


def _per100(kcal, fat, saturates, carbs, sugars, protein, salt=None) -> dict:
    return dict(zip(_FIELDS, (kcal, fat, saturates, carbs, sugars, protein, salt)))


_WATER = _per100(0, 0, 0, 0, 0, 0, 0)

# (regex on the normalized menu name, category prefix, per-100 values, basis, source[, usual amount])
# The optional last element is the usual amount of ONE item when the menu name gives no size (one banana, one cup of
# coffee); it is only ever used for the "typical" basis.
_PRODUCTS: list[tuple] = [
    (r"^(viva)\b", "10.1", _WATER, "label", "Open Food Facts 5450038030572 (Viva)"),
    (r"^rosport blue\b", "10.1", _WATER, "label", "Open Food Facts 5450038010574 (Rosport)"),
    (r"^lodyss\b", "10.1", _WATER, "label", "Open Food Facts 5450154904016 (Lodyss)"),
    (r"^coca cola\b", "10.3", _per100(42, 0, 0, 10.6, 10.6, 0, 0), "label", "Open Food Facts 54490147 (Coca-Cola)"),
    (r"^fuze tea\b", "10.3", _per100(19, 0, 0, 4.3, 4.3, 0, 0.03), "label",
     "Open Food Facts 5449000237620 (Fuze Tea Peach Hibiscus)"),
    (r"^let'?z kola\b", "10.3", _per100(27, 0, 0, 6.8, 6.6, 0), "label", "Open Food Facts 5450322059395 (Lët'z kola)"),
    (r"^rosport mat\b", "10.1", _per100(0, 0, 0, 0, 0, 0, 0.012), "label", "rosport.com/en/products/rosport-mat (mint, lemon)"),
    (r"^rosport wave\b", "10.3", _per100(16, 0.5, None, 3.6, 3.4, 0.5, None), "label",
     "rosport.com/en/products/rosport-wave (grape and grapefruit juice; saturates < 0.1 g, salt < 0.015 g)"),
    (r"^rosport sunny peche\b", "10.2", _per100(20, 0, 0, 4.6, 4.4, 0, 0.02), "label",
     "rosport.com/en/products/rosport-sunny (peach)"),
    (r"^rosport sunny citron\b", "10.2", _per100(19, 0, 0, 4.3, 4.3, 0, 0.02), "label",
     "rosport.com/en/products/rosport-sunny (lemon-lime)"),
    (r"^rosport pom'?s\b", "10.3", _per100(30, 0, 0, 7.3, 6.9, 0, 0.032), "label",
     "rosport.com/en/products/rosport-poms (65% apple juice)"),
    (r"^ramborn (apple|pear apple|apple & quince) juice\b", "10.2", _per100(46, 0.1, 0, 11, 10, 0.1, 0), "typical",
     "typical clear apple juice"),
    (r"^letzbuerger drauwejus\b", "10.2", _per100(65, 0.1, 0, 16, 16, 0.4, 0), "typical", "typical grape juice"),
    (r"^banane\b", "06.", _per100(89, 0.3, 0.1, 22.8, 12.2, 1.1, 0), "typical",
     "typical banana, one medium (about 120 g peeled)", (120, "g")),
    (r"^mini fruits decoupes\b", "06.", _per100(50, 0.2, 0, 11.5, 9.5, 0.6, 0), "typical", "typical mixed cut fruit"),
    (r"^fruit frais entier\b", "06.", _per100(50, 0.2, 0, 12, 10, 0.6, 0), "typical",
     "typical apple, pear or plum (the kind changes); a piece is about 150 g"),
    (r"^thermo cafe\b", "11.", _per100(1, 0, 0, 0, 0, 0.1, 0), "typical", "typical brewed black coffee, no milk or sugar"),
    (r"^espresso double\b", "11.", _per100(9, 0.2, 0, 1.7, 0, 0.1, 0), "typical",
     "typical espresso, no sugar; a double is about 60 ml", (60, "ml")),
    (r"^espresso\b", "11.", _per100(9, 0.2, 0, 1.7, 0, 0.1, 0), "typical",
     "typical espresso, no sugar; a single is about 30 ml", (30, "ml")),
    (r"^cafe\b", "11.", _per100(1, 0, 0, 0, 0, 0.1, 0), "typical",
     "typical brewed black coffee, no milk or sugar; a cup is about 150 ml", (150, "ml")),
    (r"^the\b", "11.", _per100(1, 0, 0, 0.2, 0, 0, 0), "typical",
     "typical unsweetened tea, no milk; a cup is about 200 ml", (200, "ml")),
    (r"^tisane\b", "11.", _per100(1, 0, 0, 0.2, 0, 0, 0), "typical",
     "typical unsweetened herbal infusion; a cup is about 200 ml", (200, "ml")),
    (r"^lait luxlait bio\b", "05.", _per100(65, 3.6, 2.5, 5, 5, 3.3, 0.11), "label",
     "Open Food Facts 5450168519145 (Luxlait lait bio 3,5%); luxlait.lu: the 250 ml organic pack is the fresh 3.5% milk"),
    (r"^yaourt nature luxlait\b", "05.", _per100(65, 3.5, 2.5, 5, 5, 3.3, 0.11), "label",
     "Open Food Facts 5450168544901 (Yaourt du Luxembourg nature, 2 pots); luxlait.lu: the plain one is 3.5% fat"),
    (r"^lait chocolate luxlait\b", "05.", _per100(94, 3.7, 2.6, 11.6, 10.9, 3.5, 0.1), "label",
     "Open Food Facts 5450168551282 (Luxlait chocolate milk)"),
    (r"^mini fromage frais\b", "05.", _per100(128, 5, 3.5, 14.6, 10.8, 6.1, 0.17), "similar",
     "Open Food Facts 5450168561144 (Luxlait fromage blanc sur fraises)"),
    (r"^dame blanche luxlait\b", "07.", _per100(165, 3.5, 2.5, 28.1, 26.6, 3.3, 0.12), "label",
     "Open Food Facts 5450007611450 (Luxlait dame blanche)"),
]
_COMPILED = [(re.compile(e[0]), e[1], e[2], e[3], e[4], e[5] if len(e) > 5 else None) for e in _PRODUCTS]


def _amount(weight_value: float | None, weight_unit: str | None) -> tuple[float, str] | None:
    """The package size as (amount, "g" | "ml"), or None when the name states none."""
    if weight_value is None or weight_unit is None or weight_unit == "piece":
        return None
    if weight_unit == "l":
        return weight_value * 1000, "ml"
    if weight_unit in ("g", "ml"):
        return weight_value, weight_unit
    return None


# "Lët'z kola 0,33 btl" / "Ramborn Apple Juice 0,33 btl" state litres without the "l"; the weight parser leaves
# those without a size, so the bottle size is read here instead.
_BOTTLE_RE = re.compile(r"(\d+[.,]\d+)\s*btl\b")


def fixed_product_nutrition(category: str, name: str, weight_value: float | None = None,
                            weight_unit: str | None = None) -> dict | None:
    """{"per100", "unit", "serving", "serving_amount", "basis", "source"} for a known fixed product, else None.
    `serving` is the per-package values (None when the menu name gives no size); `unit` is "g" or "ml"."""
    normalized = _normalize(name)
    for pattern, cat_prefix, per100, basis, source, usual in _COMPILED:
        if category.startswith(cat_prefix) and pattern.search(normalized):
            amount = _amount(weight_value, weight_unit)
            if amount is None and cat_prefix.startswith("10"):
                bottle = _BOTTLE_RE.search(normalized)
                if bottle:
                    amount = (float(bottle.group(1).replace(",", ".")) * 1000, "ml")
            if amount is None and basis == "typical" and usual is not None:
                amount = (float(usual[0]), usual[1])
            serving = None
            if amount is not None:
                factor = amount[0] / 100.0
                serving = {k: (None if v is None else round(v * factor, 1)) for k, v in per100.items()}
            return {
                "per100": dict(per100),
                "unit": amount[1] if amount else ("ml" if cat_prefix.startswith(("10", "11")) else "g"),
                "serving": serving,
                "serving_amount": amount[0] if amount else None,
                "basis": basis,
                "source": source,
            }
    return None
