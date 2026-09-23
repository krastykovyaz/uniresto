from restopolis.allergens import parse_allergens
from restopolis.flags import parse_flag


def test_parse_allergens_plain_codes():
    result = parse_allergens("6, 7, 9, 12")
    assert [a["code"] for a in result] == [6, 7, 9, 12]
    assert all(a["detail"] is None for a in result)
    assert result[0]["name"] == "Soja"


def test_parse_allergens_with_detail_containing_commas():
    result = parse_allergens("1 (Blé, Orge, Épeautre), 3, 7, 10, 12")
    assert result[0] == {"code": 1, "name": "Céréales contenant du gluten", "detail": "Blé, Orge, Épeautre"}
    assert [a["code"] for a in result[1:]] == [3, 7, 10, 12]


def test_parse_allergens_empty_string_returns_empty_list():
    assert parse_allergens("") == []
    assert parse_allergens(None) == []


def test_parse_allergens_unknown_code_keeps_code_with_no_name():
    result = parse_allergens("99")
    assert result == [{"code": 99, "name": None, "detail": None}]


def test_parse_flag_known_icons():
    assert parse_flag("/eRestauration/CustomerServices/images/vegetarian.png") == "vegetarian"
    assert parse_flag("/eRestauration/CustomerServices/images/vegan.png") == "vegan"
    assert parse_flag("/eRestauration/CustomerServices/images/not_vegetarian.png") == "non_vegetarian"
    assert parse_flag("/eRestauration/CustomerServices/images/gluten_free.jpg") == "gluten_free"
    assert parse_flag("/eRestauration/CustomerServices/images/bio.png") == "organic"


def test_parse_flag_unknown_icon_falls_back_to_filename():
    assert parse_flag("/eRestauration/CustomerServices/images/brand_new_icon.png") == "brand_new_icon.png"
