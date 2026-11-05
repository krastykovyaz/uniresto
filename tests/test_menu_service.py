from orderability_engine.menu_service import requires_early_order


def test_grill_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Mixed grill de saucisses, sauce moutarde") is True


def test_grilled_steak_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Faux-filet de boeuf grillé sauce Béarnaise") is True


def test_salmon_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Pavé de saumon, sauce citron") is True
    assert requires_early_order("Végétarien", "Salmon teriyaki bowl") is True


def test_bbq_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Poulet BBQ maison") is True


def test_grilled_starter_does_not_require_early_order():
    # Real menu item (Entrée, not a main) -- "grillé" here just describes
    # the butternut, not a grill-station dish needing pre-order.
    assert requires_early_order("Entrée", "Salade de quinoa au butternut grillé") is False


def test_grilled_sandwich_does_not_require_early_order():
    # Real menu item -- a cold sandwich, not a grill-station dish, even
    # though its name mentions grilled vegetables.
    assert requires_early_order("01.2 Sandwiches végans", "1/2 Levain Humi (houmous aux légumes locaux grillés)") is False


def test_ordinary_main_dish_does_not_require_early_order():
    assert requires_early_order("Non-végétarien", "Rôti de porc Orloff") is False


def test_case_insensitive_matching():
    assert requires_early_order("Non-végétarien", "GRILL MIXTE") is True


def test_typical_range_only_where_no_weight_and_never_in_calories():
    from datetime import date
    from orderability_engine.menu_service import flatten_menu_items
    from restopolis.models import DailyMenu, MenuItem

    menu = DailyMenu(
        restaurant_code="x", restaurant_name="X", menu_date=date(2026, 10, 27), service_name="Lunch",
        service_time=None, source_url="",
        items=[
            MenuItem("Non-végétarien", "Chipolatas rôties, jus réduit", None, 7.0),
            MenuItem("Féculents", "Riz", None, 2.0, weight_value=200, weight_unit="g"),
            MenuItem("10.3 Boissons froides - Sodas", "Coca Cola 0,20 l btl", None, 2.0),
        ],
    )
    sausage, rice, soda = flatten_menu_items([menu])
    assert sausage["calories"] is None  # filters and Smart Lunch keep seeing "unknown"
    assert sausage["calories_typical_low"] < sausage["calories_typical_high"]
    assert rice["calories"] is not None and rice["calories_typical_low"] is None
    assert soda["calories_typical_low"] is None


def test_a_week_page_is_parsed_once_until_its_text_changes(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from orderability_engine import menu_service
    from restopolis.models import DailyMenu

    calls = []

    def fake_parse(html, code, name, url, include_constant_products=False):
        calls.append((html, include_constant_products))
        return [DailyMenu(code, name, date(2026, 9, 24), "Menu", None, url), DailyMenu(code, name, date(2026, 9, 25), "Menu", None, url)]

    monkeypatch.setattr(menu_service, "parse_week_html", fake_parse)
    monkeypatch.setattr(menu_service, "_PARSED_WEEKS", {})
    restaurant = SimpleNamespace(code="X", name="X - Restaurant")
    page = {"html": "<html>week one</html>"}
    service = SimpleNamespace(get_week_html=lambda r, d: (page["html"], 0))

    first = menu_service.get_menu_for_date(service, restaurant, date(2026, 9, 24), include_constant_products=True)
    second = menu_service.get_menu_for_date(service, restaurant, date(2026, 9, 25), include_constant_products=True)
    assert [m.menu_date for m in first] == [date(2026, 9, 24)] and [m.menu_date for m in second] == [date(2026, 9, 25)]
    assert len(calls) == 1  # the other day of the same week reuses the parse

    menu_service.get_menu_for_date(service, restaurant, date(2026, 9, 24), include_constant_products=False)
    assert len(calls) == 2  # with and without constant products are different parses

    page["html"] = "<html>week one, refreshed</html>"
    menu_service.get_menu_for_date(service, restaurant, date(2026, 9, 24), include_constant_products=True)
    assert len(calls) == 3 and calls[-1][0] == "<html>week one, refreshed</html>"  # a refreshed page is parsed afresh
