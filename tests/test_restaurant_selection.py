"""The "did Restopolis really load the restaurant we asked for?" guard.

Every Menu page embeds the full restaurant picker, so every restaurant's
name appears on every page -- a plain "name in page" check can never fail.
These tests pin the replacement: read the picker's selected-restaurant
header and the active service tab's ids, and refuse anything else.
"""

import pytest

from restopolis.client import RestaurantSelectionError, RestopolisClient, WeekOutOfRangeError
from restopolis.config import load_restaurants
from restopolis.parser import MenuParseError, parse_week_html, selected_restaurant_mismatch

SOURCE_URL = "https://example.invalid/Menu"


@pytest.fixture
def configs():
    return load_restaurants()


@pytest.fixture
def pages(altius_html, brasserie_johns_html, ltck_html):
    return {
        "UDL-CKB-ALTIUS": altius_html,
        "UDL-CKB-BRASSERIE-JOHNS": brasserie_johns_html,
        "LTC-K": ltck_html,
    }


def test_the_old_name_search_could_never_fail(pages, configs):
    # Why the guard had to change: every page names every restaurant.
    for page in pages.values():
        for cfg in configs.values():
            assert cfg.name in page.replace("&#x27;", "'")


@pytest.mark.parametrize("code", ["UDL-CKB-ALTIUS", "UDL-CKB-BRASSERIE-JOHNS", "LTC-K"])
def test_each_restaurants_own_page_is_accepted(pages, configs, code):
    cfg = configs[code]
    assert selected_restaurant_mismatch(pages[code], cfg.name, cfg.restaurant_id, cfg.service_id) is None


@pytest.mark.parametrize("page_code", ["UDL-CKB-ALTIUS", "UDL-CKB-BRASSERIE-JOHNS", "LTC-K"])
@pytest.mark.parametrize("cfg_code", ["UDL-CKB-ALTIUS", "UDL-CKB-BRASSERIE-JOHNS", "LTC-K"])
def test_another_restaurants_page_is_refused(pages, configs, page_code, cfg_code):
    if page_code == cfg_code:
        pytest.skip("same restaurant")
    cfg = configs[cfg_code]
    reason = selected_restaurant_mismatch(pages[page_code], cfg.name, cfg.restaurant_id, cfg.service_id)
    assert reason and "shows restaurant" in reason


def test_a_wrong_restaurant_id_on_the_active_tab_is_refused(ltck_html, configs):
    cfg = configs["LTC-K"]
    page = ltck_html.replace("pRestaurantSelection=36&amp;pServiceSelection=62", "pRestaurantSelection=99&amp;pServiceSelection=62")
    reason = selected_restaurant_mismatch(page, cfg.name, cfg.restaurant_id, cfg.service_id)
    assert reason and "restaurant id 99" in reason


def test_a_wrong_service_on_the_active_tab_is_refused(ltck_html, configs):
    cfg = configs["LTC-K"]
    page = ltck_html.replace('data-service-id="62" class="active"', 'data-service-id="63" class="active"')
    reason = selected_restaurant_mismatch(page, cfg.name, cfg.restaurant_id, cfg.service_id)
    assert reason and "service is id 63" in reason


def test_a_page_without_the_selected_restaurant_header_is_refused(ltck_html, configs):
    cfg = configs["LTC-K"]
    page = ltck_html.replace("restaurant-selector-value-inner", "something-else")
    reason = selected_restaurant_mismatch(page, cfg.name, cfg.restaurant_id, cfg.service_id)
    assert reason and "layout" in reason


def test_the_parser_refuses_to_file_one_restaurants_menu_under_another(altius_html, configs):
    # The exact failure the old guard let through: Altius's page parsed as LTC-K.
    with pytest.raises(MenuParseError, match="shows restaurant"):
        parse_week_html(altius_html, "LTC-K", configs["LTC-K"].name, SOURCE_URL)


def test_the_parser_still_reads_the_right_page(ltck_html, configs):
    assert parse_week_html(ltck_html, "LTC-K", configs["LTC-K"].name, SOURCE_URL)


class _Resp:
    def __init__(self, text):
        self.text = text


def _client_serving(monkeypatch, page):
    client = RestopolisClient()
    monkeypatch.setattr(client, "_new_session", lambda: object())
    monkeypatch.setattr(client, "_get", lambda session, path, params=None: _Resp(page))
    return client


def test_the_client_raises_when_restopolis_shows_another_restaurant(monkeypatch, altius_html, configs):
    client = _client_serving(monkeypatch, altius_html)
    with pytest.raises(RestaurantSelectionError, match="shows restaurant"):
        client.fetch_week_html(configs["LTC-K"], weeks_ahead=0)


def test_the_client_accepts_the_right_restaurant(monkeypatch, ltck_html, configs):
    # Past the restaurant check, the only other guard is the week check,
    # which depends on today's date versus the fixture's capture week.
    client = _client_serving(monkeypatch, ltck_html)
    try:
        assert client.fetch_week_html(configs["LTC-K"], weeks_ahead=0) == ltck_html
    except WeekOutOfRangeError:
        pass  # the restaurant check passed; only the fixture's week is stale
