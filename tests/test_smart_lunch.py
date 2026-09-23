from orderability_engine.smart_lunch import find_smart_lunch, select_options


def _item(id, category, name, vegetarian=False, vegan=False, allergens=None, weight_value=None, weight_unit=None, calories=None):
    return {
        "id": id,
        "category": category,
        "name": name,
        "vegetarian": vegetarian,
        "vegan": vegan,
        "allergens": allergens or [],
        "weight_value": weight_value,
        "weight_unit": weight_unit,
        "calories": calories,
    }


def _basic_menu():
    return [
        _item(1, "Non-végétarien", "Rôti de porc", allergens=[{"code": 7, "name": "Lait"}]),
        _item(2, "Végétarien", "Aloo palak au tofu", vegetarian=True),
        _item(3, "Végan", "Curry de légumes", vegetarian=True, vegan=True),
        _item(4, "Entrée", "Salad'bar", vegetarian=True),
        _item(5, "Dessert", "Tarte aux pommes", vegetarian=True),
    ]


def test_no_constraints_gives_one_option_per_tier():
    result = find_smart_lunch(_basic_menu(), {})
    assert len(result["options"]) == 3
    assert [o["tier"] for o in result["options"]] == ["main", "main_starter", "main_starter_dessert"]
    assert result["options"][0]["total_price"] == 6.00
    assert result["options"][1]["total_price"] == 8.00
    assert result["options"][2]["total_price"] == 10.00
    assert result["matched_constraints"] == []
    assert result["unavailable_constraints"] == []


def test_vegan_preference_excludes_non_vegan_mains():
    result = find_smart_lunch(_basic_menu(), {"dietary_preferences": ["vegan"]})
    assert "dietary_preferences" in result["matched_constraints"]
    for option in result["options"]:
        main = option["items"][0]
        assert main["vegan"] is True


def test_excluded_allergen_removes_matching_main():
    result = find_smart_lunch(_basic_menu(), {"excluded_allergens": [7]})
    for option in result["options"]:
        main = option["items"][0]
        assert main["id"] != 1  # the pork dish (Lait allergen) must never appear


def test_no_main_dishes_left_after_hard_filters_gives_clear_reason():
    menu = [_item(1, "Non-végétarien", "Rôti de porc", allergens=[{"code": 7, "name": "Lait"}])]
    result = find_smart_lunch(menu, {"dietary_preferences": ["vegan"]})
    assert result["options"] == []
    assert result["unavailable_constraints"] == [
        {"constraint": "availability", "reason": "no_main_dishes_match_dietary_or_allergen_filters"}
    ]


def test_meal_preference_restricts_to_one_tier_and_varies_by_main():
    result = find_smart_lunch(_basic_menu(), {"meal_preference": "main_starter"})
    assert all(o["tier"] == "main_starter" for o in result["options"])
    assert all(o["total_price"] == 8.00 for o in result["options"])
    main_ids = [o["items"][0]["id"] for o in result["options"]]
    assert len(main_ids) == len(set(main_ids))  # every option uses a different main
    assert "meal_preference" in result["matched_constraints"]


def test_meal_preference_dropped_when_no_starter_available():
    menu = [_item(1, "Non-végétarien", "Rôti de porc")]  # no Entrée at all
    result = find_smart_lunch(menu, {"meal_preference": "main_starter"})
    assert result["options"]
    assert result["options"][0]["tier"] == "main"  # fell back once main_starter proved impossible
    assert {"constraint": "meal_preference", "reason": "no_combination_at_requested_tier"} in result["unavailable_constraints"]
    assert "meal_preference" not in result["matched_constraints"]


def test_max_price_filters_out_higher_tiers():
    result = find_smart_lunch(_basic_menu(), {"max_price": 7.00})
    assert all(o["total_price"] <= 7.00 for o in result["options"])
    assert all(o["tier"] == "main" for o in result["options"])
    assert "max_price" in result["matched_constraints"]


def test_min_weight_with_no_weight_data_anywhere_is_relaxed_not_faked():
    # Real Altius/Brasserie data: daily-formula items routinely have no
    # published weight at all -- this must never be silently treated as 0g
    # (which would make min_weight trivially fail) nor silently satisfied.
    result = find_smart_lunch(_basic_menu(), {"min_weight": 300})
    assert result["options"]  # still returns something, just relaxes the constraint
    assert "min_weight" not in result["matched_constraints"]
    assert {"constraint": "min_weight", "reason": "no_weight_data_available"} in result["unavailable_constraints"]


def test_min_weight_satisfied_only_by_fully_known_combo():
    menu = [
        _item(1, "Non-végétarien", "Plat lourd", weight_value=250, weight_unit="g"),
        _item(2, "Entrée", "Entrée légère", weight_value=100, weight_unit="g"),
    ]
    result = find_smart_lunch(menu, {"min_weight": 300})
    assert result["options"]
    assert "min_weight" in result["matched_constraints"]
    option = result["options"][0]
    assert option["weight_fully_known"] is True
    assert option["total_known_weight_g"] == 350


def test_min_weight_not_satisfied_when_combo_has_unknown_item_even_if_partial_sum_would_pass():
    # The main dish alone (50 g, fully known) is below min_weight, so
    # "main" tier fails on its own -- and the starter's weight is
    # entirely unknown, so "main_starter" can NOT be confirmed to reach
    # 100 g even though the known 50 g portion is close. Neither tier
    # gets to claim the constraint is satisfied; min_weight must be
    # relaxed rather than the combo being trusted on partial data.
    menu = [
        _item(1, "Non-végétarien", "Petit plat", weight_value=50, weight_unit="g"),
        _item(2, "Entrée", "Entrée non pesée"),  # no weight at all
    ]
    result = find_smart_lunch(menu, {"min_weight": 100})
    assert "min_weight" not in result["matched_constraints"]
    assert {"constraint": "min_weight", "reason": "no_combination_meets_minimum_weight"} in result["unavailable_constraints"]


def test_max_calories_with_no_data_is_relaxed_with_clear_reason():
    result = find_smart_lunch(_basic_menu(), {"max_calories": 500})
    assert result["options"]
    assert "max_calories" not in result["matched_constraints"]
    assert {"constraint": "max_calories", "reason": "no_calorie_data_available"} in result["unavailable_constraints"]


def test_max_calories_satisfied_by_fully_known_combo():
    menu = [
        _item(1, "Non-végétarien", "Plat léger", calories=300),
    ]
    result = find_smart_lunch(menu, {"max_calories": 400})
    assert result["options"]
    assert "max_calories" in result["matched_constraints"]
    assert result["options"][0]["calories_fully_known"] is True
    assert result["options"][0]["total_calories"] == 300


def test_soft_constraints_are_dropped_in_fixed_priority_order():
    # meal_preference is the lowest-priority soft constraint (dropped
    # first) -- with no starters at all, both meal_preference and
    # min_weight (no data) are individually unsatisfiable; only
    # meal_preference should be the one recorded as dropped once a main
    # tier alone already succeeds.
    menu = [_item(1, "Non-végétarien", "Plat")]
    result = find_smart_lunch(menu, {"meal_preference": "main_starter", "min_weight": 100})
    reasons = [u["constraint"] for u in result["unavailable_constraints"]]
    assert reasons[0] == "meal_preference"


def test_never_generates_dessert_without_starter():
    # Sanity check on the generator itself: every combo this module could
    # ever produce is one of the 3 real, priced tiers -- never a
    # main+dessert-with-no-starter combination pricing.py can't price.
    menu = [
        _item(1, "Non-végétarien", "Plat"),
        _item(2, "Dessert", "Tarte"),
    ]
    result = find_smart_lunch(menu, {})
    for option in result["options"]:
        categories = {it["category"] for it in option["items"]}
        assert not ("Dessert" in categories and "Entrée" not in categories)


def test_select_options_varies_by_tier_when_no_preference():
    combos = [
        {"tier": "main", "items": [{"id": 1}], "price": 6.00},
        {"tier": "main_starter", "items": [{"id": 1}], "price": 8.00},
        {"tier": "main_starter_dessert", "items": [{"id": 1}], "price": 10.00},
    ]
    selected = select_options(combos, meal_preference=None)
    assert [c["tier"] for c in selected] == ["main", "main_starter", "main_starter_dessert"]


def test_select_options_varies_by_main_when_preference_given():
    combos = [
        {"tier": "main", "items": [{"id": 1}], "price": 6.00},
        {"tier": "main", "items": [{"id": 1}], "price": 6.00},  # duplicate main -- must be skipped
        {"tier": "main", "items": [{"id": 2}], "price": 6.00},
    ]
    selected = select_options(combos, meal_preference="main")
    assert [c["items"][0]["id"] for c in selected] == [1, 2]
