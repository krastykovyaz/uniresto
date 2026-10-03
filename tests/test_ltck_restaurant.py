"""The Lycée Technique du Centre - Annexe Kirchberg restaurant ("LTC-K - Restaurant"), the third restaurant.

Its page is the same Restopolis structure as the two campus restaurants -- a daily "Menu" service plus the shared
"Constant products" -- with one extra daily category, "Pasta". The fixture is the real page, saved 2026-10-03.
"""

import datetime

from restopolis.config import load_restaurants
from restopolis.parser import SERVICE_NAME_CONSTANT, SERVICE_NAME_MENU, get_week_dates, parse_week_html
from scraper import slug_for

NAME = "LTC-K - Restaurant"
SOURCE_URL = "https://ssl.education.lu/eRestauration/CustomerServices/Menu"


def test_it_is_configured_with_the_ids_read_from_the_live_site():
    cfg = load_restaurants()["LTC-K"]
    assert (cfg.restaurant_id, cfg.service_id, cfg.site_id) == (36, 62, 64)
    assert cfg.name == NAME
    assert cfg.site_name == "Lycée technique du Centre - Annexe Kirchberg"
    assert (cfg.display_name, cfg.kind, cfg.building) == ("Lycée Technique du Centre", "school", "Annexe Kirchberg")


def test_the_campus_restaurants_keep_their_slugs_and_have_no_display_name_or_kind():
    restaurants = load_restaurants()
    assert slug_for("LTC-K") == "ltc-k"
    assert slug_for("UDL-CKB-ALTIUS") == "altius"
    assert restaurants["UDL-CKB-ALTIUS"].display_name is None and restaurants["UDL-CKB-ALTIUS"].kind is None
    assert len({slug_for(code) for code in restaurants}) == len(restaurants)  # no two share a slug


def test_the_week_page_parses_into_a_menu_and_the_shared_constant_products_per_day(ltck_html):
    assert get_week_dates(ltck_html) == [datetime.date(2026, 9, 28) + datetime.timedelta(days=i) for i in range(7)]
    menus = parse_week_html(ltck_html, "LTC-K", NAME, SOURCE_URL)
    assert len(menus) == 14
    by_service = {SERVICE_NAME_MENU: [], SERVICE_NAME_CONSTANT: []}
    for menu in menus:
        by_service[menu.service_name].append(menu)
    assert len(by_service[SERVICE_NAME_MENU]) == len(by_service[SERVICE_NAME_CONSTANT]) == 7
    assert {m.service_time for m in by_service[SERVICE_NAME_MENU]} == {"11:00-15:00"}
    assert all(len(m.items) == 102 for m in by_service[SERVICE_NAME_CONSTANT])


def test_weekdays_have_a_daily_menu_with_pasta_and_the_weekend_has_none(ltck_html):
    menus = [m for m in parse_week_html(ltck_html, "LTC-K", NAME, SOURCE_URL) if m.service_name == SERVICE_NAME_MENU]
    by_date = {m.menu_date: m for m in menus}
    for offset in range(5):  # Mon 28 Sep .. Fri 2 Oct
        day = datetime.date(2026, 9, 28) + datetime.timedelta(days=offset)
        items = by_date[day].items
        assert items, day
        assert "Pasta" in {i.category for i in items}, day
    assert not by_date[datetime.date(2026, 10, 3)].items and not by_date[datetime.date(2026, 10, 4)].items


def test_pasta_counts_as_a_main_course_in_both_the_server_and_the_app():
    from orderability_engine.pricing import MAIN_CATEGORIES

    assert "Pasta" in MAIN_CATEGORIES
    js = open("static/pricing.js", encoding="utf-8").read()
    assert 'new Set(["Non-végétarien", "Végétarien", "Végan", "Pasta"])' in js  # the two lists must stay identical
