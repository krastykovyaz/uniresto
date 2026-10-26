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
    assert n["basis"] == "mineral"  # no label exists for mineral water; the card must not claim one
    assert n["serving"]["kcal"] == 0 and n["serving"]["protein"] == 0
    blue = _lookup("10.1 Boissons froides - Eau minérale et pétillante", "Rosport Blue 0,50 l non consigné")
    assert blue["per100"]["salt"] == 0.0135 and "Classic" not in blue["source"]
    assert _lookup("10.1 Boissons froides - Eau minérale et pétillante", "Lodyss plate 0,25 l btl")["per100"]["salt"] is None


def test_bottle_size_without_unit_letter():
    # "0,33 btl" has no "l": the weight parser gives nothing, the table reads the size itself.
    assert parse_weight("Lët'z kola 0,33 btl") == (None, None)
    n = _lookup("10.3 Boissons froides - Sodas", "Lët'z kola 0,33 btl")
    assert n["serving_amount"] == 330 and n["serving"]["kcal"] == 89.1


def test_unknown_or_ambiguous_products_are_left_out_not_guessed():
    assert _lookup("11. Boissons chaudes", "Cappuccino") is None


def test_category_must_match():
    assert _lookup("12.1 Emballages et articles réutilisables", "Viva 0,25 l btl") is None


def test_label_values_feed_calories_in_the_menu():
    menu = DailyMenu("x", "X", date(2026, 10, 27), "Lunch", None, "", items=[
        MenuItem("10.3 Boissons froides - Sodas", "Coca Cola 0,20 l btl", None, 2.0, weight_value=0.2, weight_unit="l"),
        MenuItem("11. Boissons chaudes", "Cappuccino", None, 2.0),
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


def test_plain_hot_drinks_and_fruit_are_typical_values_with_a_usual_amount():
    espresso = _lookup("11. Boissons chaudes", "Espresso double")
    assert espresso["basis"] == "typical" and espresso["serving_amount"] == 60 and espresso["unit"] == "ml"
    assert _lookup("11. Boissons chaudes", "Espresso")["serving_amount"] == 30  # not mistaken for the double
    tea = _lookup("11. Boissons chaudes", 'Thé "commerce équitable"')
    assert tea["serving"]["kcal"] == 2.0
    banana = _lookup("06. Fruits", 'Banane "commerce équitable"')
    assert banana["serving_amount"] == 120 and banana["serving"]["kcal"] == 106.8
    # a named package size always wins over the usual amount
    assert _lookup("11. Boissons chaudes", "Thermo Café 1,50 l")["serving_amount"] == 1500


def test_milk_and_chocolate_drinks_stay_unknown():
    assert _lookup("11. Boissons chaudes", "Cappuccino") is None
    assert _lookup("11. Boissons chaudes", 'Chocolat chaud "Commerce équitable"') is None


def test_auchan_values_for_the_lets_limos_and_ramborn():
    orange = _lookup("10.3 Boissons froides - Sodas", "Lët'z limo orange 0,33 btl")
    lime = _lookup("10.3 Boissons froides - Sodas", "Lët'z limo lemon & lime 0,33 btl")
    assert orange["per100"]["kcal"] == 37 and orange["serving"]["kcal"] == 122.1 and orange["per100"]["fat"] is None
    assert lime["per100"]["sugars"] == 9.5
    # Auchan's "Jus de pomme 70cl" is 65% juice + 35% water + CO2: it describes the soda, NOT the pure juices
    soda = _lookup("10.2 Boissons froides - Jus", "Ramborn Apple Soda 0,33 l btl")
    assert soda["basis"] == "similar" and soda["per100"]["kcal"] == 25
    for juice in ("Ramborn Apple Juice 0,33 btl", "Ramborn Pear Apple Juice 0,33 l btl"):
        assert _lookup("10.2 Boissons froides - Jus", juice)["per100"]["kcal"] == 46
    quince = _lookup("10.2 Boissons froides - Jus", "Ramborn Apple & Quince Juice 0,33 l btl")
    assert quince["per100"]["kcal"] == 45 and quince["per100"]["sugars"] == 9.5 and quince["basis"] == "typical"


def test_ice_cream_is_weighed_not_measured_in_millilitres():
    # sold as "130 ml" / "200 ml", but the label values are per 100 g and ice cream weighs about 0.6 g/ml
    cone = _lookup("07. Glaces", "Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille, Praliné, Mocca-vanille)")
    assert cone["unit"] == "g" and cone["serving_amount"] == 78 and cone["basis"] == "similar"
    assert 220 <= cone["serving"]["kcal"] <= 250
    dame = _lookup("07. Glaces", "Dame Blanche Luxlait 200 ml")
    assert dame["serving_amount"] == 120 and dame["serving"]["kcal"] == 198.0


def test_trace_salt_per_bottle_is_not_rounded_to_zero():
    viva = _lookup("10.1 Boissons froides - Eau minérale et pétillante", "Viva 0,50 l btl")
    assert viva["per100"]["salt"] == 0.0086 and viva["serving"]["salt"] == 0.043
    assert viva["serving"]["kcal"] == 0  # a real zero stays zero
    assert _lookup("10.3 Boissons froides - Sodas", "Coca Cola 0,50 l non consigné")["serving"]["kcal"] == 210.0
