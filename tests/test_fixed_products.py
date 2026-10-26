from datetime import date

from orderability_engine.fixed_products import fixed_product_nutrition
from orderability_engine.menu_service import flatten_menu_items
from restopolis.models import DailyMenu, MenuItem
from restopolis.weight import parse_weight


def _lookup(category, name):
    return fixed_product_nutrition(category, name, *parse_weight(name))


def test_cola_per_package():
    n = _lookup("10.3 Boissons froides - Sodas", "Coca Cola 0,50 l non consigné")
    assert n["basis"] == "label" and n["unit"] == "ml"
    assert n["per100"]["sugars"] == 10.6 and n["serving"]["kcal"] == 210.0 and n["serving_amount"] == 500


def test_water_is_a_real_zero_not_unknown():
    n = _lookup("10.1 Boissons froides - Eau minérale et pétillante", "Viva 0,25 l btl")
    assert n["serving"]["kcal"] == 0 and n["serving"]["protein"] == 0


def test_bottle_size_without_unit_letter():
    # "0,33 btl" has no "l": the weight parser gives nothing, the table reads the size itself.
    assert parse_weight("Lët'z kola 0,33 btl") == (None, None)
    n = _lookup("10.3 Boissons froides - Sodas", "Lët'z kola 0,33 btl")
    assert n["serving_amount"] == 330 and n["serving"]["kcal"] == 89.1


def test_unknown_or_ambiguous_products_are_left_out_not_guessed():
    assert _lookup("10.3 Boissons froides - Sodas", "Lët'z limo orange 0,33 btl") is None


def test_category_must_match():
    assert _lookup("12.1 Emballages et articles réutilisables", "Viva 0,25 l btl") is None


def test_label_values_feed_calories_in_the_menu():
    menu = DailyMenu("x", "X", date(2026, 10, 27), "Lunch", None, "", items=[
        MenuItem("10.3 Boissons froides - Sodas", "Coca Cola 0,20 l btl", None, 2.0, weight_value=0.2, weight_unit="l"),
        MenuItem("10.3 Boissons froides - Sodas", "Lët'z limo orange 0,33 btl", None, 2.0),
    ])
    cola, wave = flatten_menu_items([menu])
    assert cola["calories"] == 84.0 and cola["nutrition"]["per100"]["kcal"] == 42
    assert wave["nutrition"] is None


def test_organic_milk_and_plain_yoghurt_are_the_whole_versions():
    milk = _lookup("05. Laitages", "Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)")
    assert milk["per100"]["fat"] == 3.6 and milk["serving"]["kcal"] == 162.5
    yoghurt = _lookup("05. Laitages", "Yaourt nature Luxlait 125 g")
    assert yoghurt["per100"]["fat"] == 3.5 and yoghurt["serving"]["kcal"] == 81.2


def test_rosport_tables_from_the_makers_site():
    mat = _lookup("10.1 Boissons froides - Eau minérale et pétillante", "Rosport mat Menthe 0,50 l non consigné")
    assert mat["basis"] == "label" and mat["serving"]["kcal"] == 0
    wave = _lookup("10.3 Boissons froides - Sodas", "Rosport Wave 0,50 l non-consigné")
    assert wave["per100"]["kcal"] == 16 and wave["serving"]["kcal"] == 80.0 and wave["per100"]["saturates"] is None
    peach = _lookup("10.2 Boissons froides - Jus", "Rosport Sunny Pêche 0,50 l non consigné")
    lemon = _lookup("10.2 Boissons froides - Jus", "Rosport Sunny Citron-Citron vert 0,50 l non consigné")
    assert peach["per100"]["sugars"] == 4.4 and lemon["per100"]["sugars"] == 4.3
    assert _lookup("10.3 Boissons froides - Sodas", "Rosport Pom's 0,50 l non consigné")["per100"]["kcal"] == 30
