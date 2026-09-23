import datetime

import pytest

from restopolis.parser import (
    MenuParseError,
    SERVICE_NAME_CONSTANT,
    SERVICE_NAME_MENU,
    get_week_dates,
    parse_week_html,
)

ALTIUS_NAME = "UDL-CKB - Altius - Restaurant"
BRASSERIE_NAME = "UDL-CKB - Brasserie John's - Restaurant"
SOURCE_URL = "https://ssl.education.lu/eRestauration/CustomerServices/Menu"


# ---------------------------------------------------------------------------
# Real-fixture tests
# ---------------------------------------------------------------------------


def test_get_week_dates_returns_seven_consecutive_days(altius_html):
    dates = get_week_dates(altius_html)
    assert len(dates) == 7
    assert dates == [datetime.date(2026, 9, 21) + datetime.timedelta(days=i) for i in range(7)]


def test_parse_week_html_altius_produces_menu_and_constant_per_day(altius_html):
    menus = parse_week_html(altius_html, "UDL-CKB-ALTIUS", ALTIUS_NAME, SOURCE_URL)
    # 7 days x 2 services (Menu + Constant products)
    assert len(menus) == 14
    services = {m.service_name for m in menus}
    assert services == {SERVICE_NAME_MENU, SERVICE_NAME_CONSTANT}


def test_parse_week_html_brasserie_johns_apostrophe_name_matches(brasserie_johns_html):
    # Restopolis HTML-encodes the apostrophe as &#x27;; this must not break
    # the restaurant-name sanity check.
    menus = parse_week_html(
        brasserie_johns_html, "UDL-CKB-BRASSERIE-JOHNS", BRASSERIE_NAME, SOURCE_URL
    )
    assert len(menus) == 14


def test_category_names_are_preserved_in_french(altius_html):
    menus = parse_week_html(altius_html, "UDL-CKB-ALTIUS", ALTIUS_NAME, SOURCE_URL)
    wednesday = next(
        m for m in menus
        if m.menu_date == datetime.date(2026, 9, 23) and m.service_name == SERVICE_NAME_MENU
    )
    categories = [item.category for item in wednesday.items]
    for expected in ["Entrée", "Végétarien", "Végan", "Non-végétarien", "Féculents", "Légumes", "Dessert"]:
        assert expected in categories


def test_dish_extraction_known_item(altius_html):
    menus = parse_week_html(altius_html, "UDL-CKB-ALTIUS", ALTIUS_NAME, SOURCE_URL)
    wednesday = next(
        m for m in menus
        if m.menu_date == datetime.date(2026, 9, 23) and m.service_name == SERVICE_NAME_MENU
    )
    starter = next(item for item in wednesday.items if item.name == "Potage au potiron")
    assert starter.category == "Entrée"
    assert starter.price is None  # Restopolis never shows a price on this page
    assert wednesday.service_time == "11:00-14:30"


def test_allergen_extraction_with_and_without_detail(altius_html):
    menus = parse_week_html(altius_html, "UDL-CKB-ALTIUS", ALTIUS_NAME, SOURCE_URL)
    wednesday = next(
        m for m in menus
        if m.menu_date == datetime.date(2026, 9, 23) and m.service_name == SERVICE_NAME_MENU
    )
    vegetarian_dish = next(item for item in wednesday.items if item.category == "Végétarien")
    codes = {a["code"] for a in vegetarian_dish.allergens}
    assert 1 in codes  # gluten
    gluten_entry = next(a for a in vegetarian_dish.allergens if a["code"] == 1)
    assert gluten_entry["name"] == "Céréales contenant du gluten"
    assert gluten_entry["detail"] == "Blé"


def test_vegetarian_and_vegan_detection(altius_html):
    menus = parse_week_html(altius_html, "UDL-CKB-ALTIUS", ALTIUS_NAME, SOURCE_URL)
    wednesday = next(
        m for m in menus
        if m.menu_date == datetime.date(2026, 9, 23) and m.service_name == SERVICE_NAME_MENU
    )
    vegan_dish = next(item for item in wednesday.items if item.category == "Végan")
    assert vegan_dish.is_vegan is True
    assert vegan_dish.is_vegetarian is True

    meat_dish = next(item for item in wednesday.items if item.category == "Non-végétarien")
    assert meat_dish.is_vegan is False
    assert meat_dish.is_vegetarian is False
    assert "non_vegetarian" in meat_dish.dietary


def test_weekend_has_no_products_but_is_not_lost(altius_html):
    menus = parse_week_html(altius_html, "UDL-CKB-ALTIUS", ALTIUS_NAME, SOURCE_URL)
    saturday = next(
        m for m in menus
        if m.menu_date == datetime.date(2026, 9, 26) and m.service_name == SERVICE_NAME_MENU
    )
    assert saturday.is_no_products is True
    assert saturday.items == []


def test_constant_products_can_be_excluded(altius_html):
    menus = parse_week_html(
        altius_html, "UDL-CKB-ALTIUS", ALTIUS_NAME, SOURCE_URL, include_constant_products=False
    )
    assert len(menus) == 7
    assert all(m.service_name == SERVICE_NAME_MENU for m in menus)


def test_wrong_restaurant_name_raises(altius_html):
    with pytest.raises(MenuParseError):
        parse_week_html(altius_html, "SOMETHING-ELSE", "Not The Right Restaurant", SOURCE_URL)


# ---------------------------------------------------------------------------
# Synthetic / malformed HTML tests (don't depend on the live site)
# ---------------------------------------------------------------------------


def _make_week_html(restaurant_name: str, day_blocks: list[str]) -> str:
    date_links = "".join(
        f'<a class="day" data-date="{21 + i:02d}.09.2026">day{i}</a>' for i in range(len(day_blocks))
    )
    slides = "".join(f"<div>{block}</div>" for block in day_blocks)
    return f"""
    <html><body>
    <div class="restaurant-selector-value-inner"><span>{restaurant_name}</span></div>
    <div id="date-selector">{date_links}</div>
    <div class="menu-slider">{slides}</div>
    <div data-role="formula-products" data-service-id="1">Service 11:00 - 14:30</div>
    <div data-role="constant-products">Produits constants</div>
    </body></html>
    """


_EMPTY_DAY = '<div class="formulaeContainer no-products"></div><div class="constantProductContainer"></div>'


def test_product_without_preceding_category_defaults_to_unknown(caplog):
    day = (
        '<div class="formulaeContainer">'
        '<div class="product-name">Mystery Dish</div>'
        '<span class="product-allergens"></span>'
        '<div class="product-description"></div>'
        "</div>"
        '<div class="constantProductContainer"></div>'
    )
    html = _make_week_html("Test Restaurant", [day] + [_EMPTY_DAY] * 6)
    menus = parse_week_html(html, "TEST", "Test Restaurant", SOURCE_URL)
    monday_menu = next(m for m in menus if m.service_name == SERVICE_NAME_MENU and m.menu_date == datetime.date(2026, 9, 21))
    assert len(monday_menu.items) == 1
    assert monday_menu.items[0].category == "Unknown"
    assert monday_menu.items[0].name == "Mystery Dish"
    assert "no preceding category" in caplog.text


def test_missing_description_and_allergens_do_not_drop_item():
    day = (
        '<div class="formulaeContainer">'
        '<div class="course-name">Entrée</div>'
        '<div class="product-name">Bare Dish</div>'
        "</div>"
        '<div class="constantProductContainer"></div>'
    )
    html = _make_week_html("Test Restaurant", [day] + [_EMPTY_DAY] * 6)
    menus = parse_week_html(html, "TEST", "Test Restaurant", SOURCE_URL)
    monday_menu = next(m for m in menus if m.service_name == SERVICE_NAME_MENU and m.menu_date == datetime.date(2026, 9, 21))
    item = monday_menu.items[0]
    assert item.name == "Bare Dish"
    assert item.description is None
    assert item.allergens == []
    assert item.price is None


def test_day_count_mismatch_raises():
    # 7 date-selector links but only 6 menu-slider day divs: the parser must
    # refuse to guess the alignment rather than silently mis-map dates.
    date_links = "".join(
        f'<a class="day" data-date="{21 + i:02d}.09.2026">day{i}</a>' for i in range(7)
    )
    slides = "".join(f"<div>{_EMPTY_DAY}</div>" for _ in range(6))
    html = f"""
    <html><body>
    <div class="restaurant-selector-value-inner"><span>Test Restaurant</span></div>
    <div id="date-selector">{date_links}</div>
    <div class="menu-slider">{slides}</div>
    </body></html>
    """
    with pytest.raises(MenuParseError):
        parse_week_html(html, "TEST", "Test Restaurant", SOURCE_URL)


def test_missing_menu_slider_raises():
    html = """
    <html><body>
    <div class="restaurant-selector-value-inner"><span>Test Restaurant</span></div>
    <div id="date-selector">
        <a class="day" data-date="21.09.2026">day0</a>
    </div>
    </body></html>
    """
    with pytest.raises(MenuParseError):
        parse_week_html(html, "TEST", "Test Restaurant", SOURCE_URL)


def test_missing_date_selector_raises():
    html = """
    <html><body>
    <div class="restaurant-selector-value-inner"><span>Test Restaurant</span></div>
    <div class="menu-slider"><div></div></div>
    </body></html>
    """
    with pytest.raises(MenuParseError):
        parse_week_html(html, "TEST", "Test Restaurant", SOURCE_URL)
