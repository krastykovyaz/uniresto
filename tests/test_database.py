import datetime

import pytest

from restopolis.database import RestopolisDatabase
from restopolis.models import DailyMenu, MenuItem, RestaurantConfig


@pytest.fixture
def db(tmp_path):
    database = RestopolisDatabase(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def restaurant_cfg():
    return RestaurantConfig(
        code="UDL-CKB-ALTIUS",
        name="UDL-CKB - Altius - Restaurant",
        restaurant_id=164,
        service_id=1183,
    )


def _menu(date, items):
    return DailyMenu(
        restaurant_code="UDL-CKB-ALTIUS",
        restaurant_name="UDL-CKB - Altius - Restaurant",
        menu_date=date,
        service_name="Menu",
        service_time="11:00-14:30",
        source_url="https://example.test/Menu",
        items=items,
    )


def _item(name, category="Entrée", sort_order=0):
    return MenuItem(category=category, name=name, description=None, price=None, sort_order=sort_order)


def test_upsert_restaurant_is_idempotent(db, restaurant_cfg):
    id1 = db.upsert_restaurant(restaurant_cfg)
    id2 = db.upsert_restaurant(restaurant_cfg)
    assert id1 == id2
    count = db._conn.execute("SELECT COUNT(*) FROM restaurants").fetchone()[0]
    assert count == 1


def test_upsert_daily_menu_stores_items(db, restaurant_cfg):
    rid = db.upsert_restaurant(restaurant_cfg)
    menu = _menu(datetime.date(2026, 9, 24), [_item("Soup"), _item("Salad", sort_order=1)])
    menu_id = db.upsert_daily_menu(rid, menu)
    assert db.count_menu_items(menu_id) == 2


def test_running_scrape_twice_does_not_duplicate(db, restaurant_cfg):
    rid = db.upsert_restaurant(restaurant_cfg)
    menu = _menu(datetime.date(2026, 9, 24), [_item("Soup"), _item("Salad", sort_order=1)])

    menu_id_1 = db.upsert_daily_menu(rid, menu)
    menu_id_2 = db.upsert_daily_menu(rid, menu)

    assert menu_id_1 == menu_id_2
    assert db.count_menu_items(menu_id_1) == 2

    menus_count = db._conn.execute("SELECT COUNT(*) FROM menus").fetchone()[0]
    assert menus_count == 1


def test_item_list_changes_are_reflected_not_appended(db, restaurant_cfg):
    rid = db.upsert_restaurant(restaurant_cfg)
    day = datetime.date(2026, 9, 24)

    menu_id = db.upsert_daily_menu(rid, _menu(day, [_item("Soup"), _item("Salad", sort_order=1)]))
    assert db.count_menu_items(menu_id) == 2

    # Restopolis changed the menu: one dish removed, one added.
    menu_id_2 = db.upsert_daily_menu(rid, _menu(day, [_item("Soup"), _item("Fish", sort_order=1)]))
    assert menu_id_2 == menu_id
    names = {
        row[0]
        for row in db._conn.execute(
            "SELECT name FROM menu_items WHERE menu_id = ?", (menu_id,)
        ).fetchall()
    }
    assert names == {"Soup", "Fish"}


def test_different_dates_and_services_are_kept_separate(db, restaurant_cfg):
    rid = db.upsert_restaurant(restaurant_cfg)
    db.upsert_daily_menu(rid, _menu(datetime.date(2026, 9, 24), [_item("Soup")]))
    db.upsert_daily_menu(rid, _menu(datetime.date(2026, 9, 25), [_item("Soup")]))

    menu = _menu(datetime.date(2026, 9, 24), [_item("Sandwich")])
    menu.service_name = "Constant products"
    menu.service_time = None
    db.upsert_daily_menu(rid, menu)

    menus_count = db._conn.execute("SELECT COUNT(*) FROM menus").fetchone()[0]
    assert menus_count == 3


def test_fetch_menus_round_trips_allergens_and_dietary(db, restaurant_cfg):
    rid = db.upsert_restaurant(restaurant_cfg)
    item = MenuItem(
        category="Entrée",
        name="Minestrone",
        description=None,
        price=None,
        allergens=[{"code": 7, "name": "Lait", "detail": None}],
        dietary=["vegetarian", "gluten_free"],
        sort_order=0,
    )
    db.upsert_daily_menu(rid, _menu(datetime.date(2026, 9, 24), [item]))

    menus = db.fetch_menus(restaurant_code="UDL-CKB-ALTIUS")
    assert len(menus) == 1
    fetched_item = menus[0]["items"][0]
    assert fetched_item["allergens"] == [{"code": 7, "name": "Lait", "detail": None}]
    assert fetched_item["dietary"] == ["vegetarian", "gluten_free"]


def test_fetch_menus_filters_by_date_range(db, restaurant_cfg):
    rid = db.upsert_restaurant(restaurant_cfg)
    db.upsert_daily_menu(rid, _menu(datetime.date(2026, 9, 21), [_item("A")]))
    db.upsert_daily_menu(rid, _menu(datetime.date(2026, 9, 24), [_item("B")]))
    db.upsert_daily_menu(rid, _menu(datetime.date(2026, 9, 28), [_item("C")]))

    menus = db.fetch_menus(
        restaurant_code="UDL-CKB-ALTIUS",
        start_date=datetime.date(2026, 9, 22),
        end_date=datetime.date(2026, 9, 26),
    )
    assert [m["date"] for m in menus] == ["2026-09-24"]
