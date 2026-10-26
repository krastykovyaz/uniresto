from datetime import date

from orderability_engine.dish_estimates import _DISHES, dish_estimate
from orderability_engine.menu_service import flatten_menu_items
from restopolis.models import DailyMenu, MenuItem
from restopolis.weight import parse_weight


def test_every_entry_adds_up():
    # kcal should be about 9 per g of fat and 4 per g of carbs or protein; a typo in one number breaks this.
    for name, (grams, kcal, fat, carbs, protein) in _DISHES.items():
        computed = 9 * fat + 4 * carbs + 4 * protein
        assert abs(computed - kcal) <= 0.15 * kcal + 15, f"{name}: {kcal} kcal vs {computed} from its macros"
        assert 0 < grams <= 500 and fat + carbs + protein <= grams, name


def test_lookup_ignores_case_and_accents_and_unknown_names_have_none():
    assert dish_estimate("CHIPOLATAS ROTIES, JUS REDUIT")["serving"]["kcal"] == 430
    assert dish_estimate("A dish nobody photographed") is None


def _flat(category, name):
    w = parse_weight(name)
    menu = DailyMenu("x", "X", date(2026, 10, 27), "L", None, "",
                     items=[MenuItem(category, name, None, 5.0, weight_value=w[0], weight_unit=w[1])])
    return flatten_menu_items([menu])[0]


def test_photographed_dish_gets_a_range_and_never_a_calories_value():
    item = _flat("Non-végétarien", "Chipolatas rôties, jus réduit")
    assert item["calories"] is None  # the calorie filter and Smart Lunch still see "unknown"
    assert item["nutrition"]["basis"] == "dish" and item["nutrition"]["serving_amount"] == 150
    assert (item["calories_typical_low"], item["calories_typical_high"]) == (340, 520)


def test_weighted_pastry_keeps_its_density_calories_but_shows_the_dish_range():
    item = _flat("02. Viennoiseries", "Croissant 50 g")
    assert item["calories"] is not None
    assert item["nutrition"]["basis"] == "dish" and item["calories_typical_low"] == 180
