from orderability_engine.dish_name_labels import DISH_NAME_LABELS, dish_name_label


def test_translates_a_known_dish_name():
    assert dish_name_label("Salade campagnarde", "en") == "Country salad"
    assert dish_name_label("Soupe de pommes de terre", "ru") == "Картофельный суп"


def test_falls_back_to_the_raw_name_for_an_unmapped_dish():
    assert dish_name_label("Some Future Dish Restopolis Adds", "en") == "Some Future Dish Restopolis Adds"


def test_french_returns_the_name_unchanged():
    for name in DISH_NAME_LABELS:
        assert dish_name_label(name, "fr") == name


def test_falls_back_to_english_for_an_unknown_language_code():
    assert dish_name_label("Salade campagnarde", "xx") == "Country salad"
