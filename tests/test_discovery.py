from restopolis.discovery import find_by_name, parse_restaurant_list


def test_parse_restaurant_list_finds_target_restaurants(altius_html):
    restaurants = parse_restaurant_list(altius_html)
    assert len(restaurants) > 100  # Restopolis lists hundreds of restaurants site-wide

    altius = find_by_name(restaurants, "UDL-CKB - Altius - Restaurant")
    assert altius is not None
    assert altius.restaurant_id == 164
    assert altius.site_name == "Université de Luxembourg Campus Kirchberg"

    brasserie = find_by_name(restaurants, "UDL-CKB - Brasserie John's - Restaurant")
    assert brasserie is not None
    assert brasserie.restaurant_id == 160


def test_find_by_name_returns_none_for_unknown_restaurant(altius_html):
    restaurants = parse_restaurant_list(altius_html)
    assert find_by_name(restaurants, "Does Not Exist - Restaurant") is None
