"""Smart Lunch: a deterministic backend search over the live menu for a
lunch combination matching a set of constraints -- never a ranking of
"best"/"healthiest" (no medical or nutritional-quality claim is made or
implied anywhere in this module or its output; see README.md Part 51).

Reuses the EXISTING meal-formula pricing system (orderability_engine/
pricing.py) rather than inventing a separate one: a candidate combo's
price is always its bundle-tier total, computed via
compute_formula_total(). This module only ever GENERATES the 3
structural shapes that system actually prices -- main alone /
main+starter / main+starter+dessert -- for genuine "simple / regular /
full" variety (see select_options()); a starter or dessert without the
course below it isn't a priced combination at all (see pricing.py), so
this module never even builds a candidate that lacks one.

Two constraint classes:

  - HARD constraints (dietary_preferences, excluded_allergens): never
    relaxed. If they leave zero eligible main dishes, the search fails
    outright with an explanation naming that as the cause.
  - SOFT constraints (meal_preference, max_calories, min_weight,
    max_price): tried together first; if no combination satisfies all of
    them, they're dropped ONE AT A TIME, least-important first (see
    _SOFT_CONSTRAINT_DROP_ORDER), until at least one combination is
    found or every soft constraint has been dropped. Each drop is
    recorded in `unavailable_constraints` with a reason, never silently.

Never treats an unknown weight/calorie value as zero: min_weight and
max_calories can only be confirmed for a combination whose every item
has a KNOWN value in that dimension (see _combo_weight/_combo_calories);
an item with no published weight/calorie estimate simply can't prove or
disprove either constraint, so a combination that can't be proven to
satisfy one is never claimed to. Given real Restopolis data mostly
lacks weight/calories for daily-formula dishes (Part 3/7), this means a
min_weight or max_calories constraint routinely has to be relaxed on
real menus -- an honest, expected outcome, not a bug (see README.md
Part 51's "Verified live" section for a concrete example).
"""

from __future__ import annotations

from orderability_engine.pricing import (
    DESSERT_CATEGORIES,
    MAIN_CATEGORIES,
    STARTER_CATEGORIES,
    compute_formula_total,
)

TIER_ORDER = ["main", "main_starter", "main_starter_dessert"]

# Drop order when a soft constraint can't be satisfied together with the
# others -- least-important (most negotiable) first. A documented v1
# design choice, not a derived fact: price is treated as the constraint
# a student is least likely to want relaxed; which exact tier they get
# is treated as the most negotiable.
_SOFT_CONSTRAINT_DROP_ORDER = ["meal_preference", "max_calories", "min_weight", "max_price"]

MAX_OPTIONS = 3


def _item_matches_dietary(item: dict, dietary_preferences: list[str]) -> bool:
    if "vegan" in dietary_preferences and not item.get("vegan"):
        return False
    if "vegetarian" in dietary_preferences and not (item.get("vegetarian") or item.get("vegan")):
        return False
    return True


def _item_matches_allergens(item: dict, excluded_allergen_codes: set[int]) -> bool:
    if not excluded_allergen_codes:
        return True
    codes = {a["code"] for a in item.get("allergens") or []}
    return not (codes & excluded_allergen_codes)


def _combo_weight(items: list[dict]) -> tuple[float | None, bool]:
    """Sums weight ONLY across items with a known gram weight -- an item
    measured in a different unit (ml/piece) or with no weight at all
    simply isn't counted, never treated as 0 g. `fully_known` is True
    only when EVERY item in the combo has a known gram weight; the
    min_weight constraint (see find_smart_lunch) requires that to be
    True before it will claim the combo satisfies it."""
    known = [it["weight_value"] for it in items if it.get("weight_value") is not None and it.get("weight_unit") == "g"]
    fully_known = len(known) == len(items)
    total = round(sum(known), 1) if known else None
    return total, fully_known


def _combo_calories(items: list[dict]) -> tuple[float | None, bool]:
    known = [it["calories"] for it in items if it.get("calories") is not None]
    fully_known = len(known) == len(items)
    total = round(sum(known), 1) if known else None
    return total, fully_known


def _candidate_combos_for_tier(tier: str, mains: list[dict], starters: list[dict], desserts: list[dict]) -> list[dict]:
    """One candidate combo per main dish, always paired with the FIRST
    available starter/dessert (by menu order) when the tier calls for
    one -- not every starter x dessert pairing. A documented v1
    simplification: enumerating every pairing would multiply the
    candidate count for no real benefit (candidates are deduplicated
    down to MAX_OPTIONS anyway, see select_options), at real complexity
    cost."""
    combos = []
    for main in mains:
        items = [main]
        if tier in ("main_starter", "main_starter_dessert"):
            if not starters:
                continue
            items.append(starters[0])
        if tier == "main_starter_dessert":
            if not desserts:
                continue
            items.append(desserts[0])

        formula = compute_formula_total([{"category": it["category"], "quantity": 1} for it in items])
        if formula["total"] is None:
            continue  # should not happen given the tier gating above, but never guess a price
        combos.append({"tier": tier, "items": items, "price": formula["total"]})
    return combos


def _relax_reason(constraint: str, mains: list[dict], starters: list[dict], desserts: list[dict]) -> str:
    pool = mains + starters + desserts
    if constraint == "min_weight":
        any_known = any(it.get("weight_value") is not None and it.get("weight_unit") == "g" for it in pool)
        return "no_weight_data_available" if not any_known else "no_combination_meets_minimum_weight"
    if constraint == "max_calories":
        any_known = any(it.get("calories") is not None for it in pool)
        return "no_calorie_data_available" if not any_known else "no_combination_within_calorie_limit"
    if constraint == "max_price":
        return "no_combination_within_price"
    if constraint == "meal_preference":
        return "no_combination_at_requested_tier"
    return "no_matching_combination"


def select_options(combos: list[dict], meal_preference: str | None) -> list[dict]:
    """Picks up to MAX_OPTIONS combos with genuine variety, never a
    quality ranking (no score, no sort by price/weight/calories):

    - meal_preference given: one tier only, so options vary by MAIN DISH
      instead (first combo found per distinct main, in menu order).
    - no meal_preference: one option per TIER (main, then main+starter,
      then main+starter+dessert, in that fixed structural order) -- the
      natural "simple / regular / full" variety a canteen menu already
      implies, not a ranking of any one being better.
    """
    if meal_preference:
        seen_mains: set[int] = set()
        selected = []
        for combo in combos:
            main_id = combo["items"][0]["id"]
            if main_id in seen_mains:
                continue
            seen_mains.add(main_id)
            selected.append(combo)
            if len(selected) == MAX_OPTIONS:
                break
        return selected

    selected = []
    for tier in TIER_ORDER:
        for combo in combos:
            if combo["tier"] == tier:
                selected.append(combo)
                break
    return selected[:MAX_OPTIONS]


def _serialize_option(combo: dict) -> dict:
    # No English "Option N" label or any other display prose here on
    # purpose -- this is data, not UI text (same "reason codes, not
    # prose" rule Part 6/39's pricing formula reasons already follow).
    # The frontend derives "Option {n}" from this list's own position
    # via static/i18n.js, in whichever language is active.
    weight_total, weight_known = _combo_weight(combo["items"])
    cal_total, cal_known = _combo_calories(combo["items"])
    return {
        "tier": combo["tier"],
        "items": combo["items"],
        "total_price": combo["price"],
        "total_known_weight_g": weight_total,
        "weight_fully_known": weight_known,
        "total_calories": cal_total,
        "calories_fully_known": cal_known,
    }


def find_smart_lunch(menu_items: list[dict], params: dict) -> dict:
    """menu_items: the live, backend-fetched flat menu (see
    menu_service.flatten_menu_items()) -- the ONLY source of dishes this
    ever considers, never a fabricated one.

    params (all optional):
        dietary_preferences: list[str], subset of {"vegetarian", "vegan"} -- HARD
        excluded_allergens: list[int], EU allergen codes -- HARD
        meal_preference: str, one of TIER_ORDER's values -- SOFT
        max_price: float -- SOFT
        min_weight: float (grams) -- SOFT
        max_calories: float -- SOFT

    Returns {"options": [...], "matched_constraints": [...],
    "unavailable_constraints": [{"constraint": ..., "reason": ...}]}.
    `options` is [] (never a fabricated combo) when even the hard
    constraints alone leave nothing viable; the single explanatory entry
    in `unavailable_constraints` in that case names the real cause."""
    dietary_preferences = params.get("dietary_preferences") or []
    excluded_allergens = set(params.get("excluded_allergens") or [])
    meal_preference = params.get("meal_preference")
    max_price = params.get("max_price")
    min_weight = params.get("min_weight")
    max_calories = params.get("max_calories")

    def hard_ok(item: dict) -> bool:
        return _item_matches_dietary(item, dietary_preferences) and _item_matches_allergens(item, excluded_allergens)

    mains = [it for it in menu_items if it["category"] in MAIN_CATEGORIES and hard_ok(it)]
    starters = [it for it in menu_items if it["category"] in STARTER_CATEGORIES and hard_ok(it)]
    desserts = [it for it in menu_items if it["category"] in DESSERT_CATEGORIES and hard_ok(it)]

    soft_order = []
    if meal_preference:
        soft_order.append("meal_preference")
    if max_calories is not None:
        soft_order.append("max_calories")
    if min_weight is not None:
        soft_order.append("min_weight")
    if max_price is not None:
        soft_order.append("max_price")
    # Fixed priority regardless of request order -- see module docstring.
    soft_order.sort(key=_SOFT_CONSTRAINT_DROP_ORDER.index)

    active = set(soft_order)
    droppable = list(soft_order)
    unavailable: list[dict] = []
    combos: list[dict] = []

    while True:
        tiers_to_try = [meal_preference] if ("meal_preference" in active and meal_preference) else TIER_ORDER
        raw_combos = []
        for tier in tiers_to_try:
            raw_combos.extend(_candidate_combos_for_tier(tier, mains, starters, desserts))

        combos = []
        for combo in raw_combos:
            if "max_price" in active and combo["price"] > max_price:
                continue
            weight_total, weight_known = _combo_weight(combo["items"])
            if "min_weight" in active and not (weight_known and weight_total is not None and weight_total >= min_weight):
                continue
            cal_total, cal_known = _combo_calories(combo["items"])
            if "max_calories" in active and not (cal_known and cal_total is not None and cal_total <= max_calories):
                continue
            combos.append(combo)

        if combos or not droppable:
            break
        dropped = droppable.pop(0)
        active.discard(dropped)
        unavailable.append({"constraint": dropped, "reason": _relax_reason(dropped, mains, starters, desserts)})

    matched_constraints = []
    if dietary_preferences:
        matched_constraints.append("dietary_preferences")
    if excluded_allergens:
        matched_constraints.append("excluded_allergens")
    matched_constraints.extend(c for c in soft_order if c in active)

    if not combos:
        if not mains:
            reason = "no_main_dishes_match_dietary_or_allergen_filters" if (dietary_preferences or excluded_allergens) else "no_main_dishes_available"
        else:
            reason = "no_valid_combination_found"
        return {"options": [], "matched_constraints": [], "unavailable_constraints": [{"constraint": "availability", "reason": reason}]}

    chosen = select_options(combos, meal_preference if "meal_preference" in active else None)
    options = [_serialize_option(combo) for combo in chosen]
    return {"options": options, "matched_constraints": matched_constraints, "unavailable_constraints": unavailable}
