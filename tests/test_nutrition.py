from orderability_engine.nutrition import classify_food_type, estimate_calories


def test_no_weight_gives_no_estimate():
    result = estimate_calories("Poulet rôti", None, None)
    assert result == {"calories": None, "food_type": None, "is_estimated": False}


def test_piece_unit_gives_no_estimate():
    # No reliable typical mass for "1 piece" across arbitrary dishes --
    # would require guessing a weight, which this module never does.
    result = estimate_calories("Croissant", 1, "piece")
    assert result["calories"] is None
    assert result["is_estimated"] is False


def test_unmatched_name_gives_no_estimate():
    result = estimate_calories("Plat mystère du jour", 200, "g")
    assert result == {"calories": None, "food_type": None, "is_estimated": False}


def test_known_weight_and_matched_keyword_gives_an_estimate():
    result = estimate_calories("Rôti de porc Orloff", 200, "g")
    assert result["calories"] == 440.0
    assert result["food_type"] == "red_meat"
    assert result["is_estimated"] is True


def test_liters_are_converted_to_grams_equivalent():
    result = estimate_calories("Coca-Cola", 0.5, "l")
    assert result["calories"] == 210.0
    assert result["food_type"] == "soda"


def test_water_is_zero_calories_but_still_an_estimate():
    result = estimate_calories("Eau plate", 500, "ml")
    assert result["calories"] == 0.0
    assert result["is_estimated"] is True


# -- Regression tests for real classification bugs found via manual
# validation against tests/fixtures/altius_week0.html --


def test_luxlait_brand_name_does_not_falsely_match_milk():
    # "Luxlait" is a Luxembourg dairy BRAND that appears as a manufacturer
    # prefix on many unrelated constant products (ice cream, yogurt...).
    # Naive substring matching on "lait" previously misclassified anything
    # with "Luxlait" in the name as plain milk.
    assert classify_food_type("Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)") != ("milk", 60)
    food_type, _ = classify_food_type("Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)")
    assert food_type == "ice_cream"


def test_standalone_lait_still_matches_milk():
    # A genuine standalone "Lait" word must still match -- the fix is
    # word-boundary matching, not blanket exclusion of the keyword.
    food_type, _ = classify_food_type("Lait demi-écrémé Luxlait 25 cl")
    assert food_type == "milk"


def test_menthe_does_not_falsely_match_tea():
    # "Rosport mat Menthe" is mint-flavoured mineral water; naive
    # substring matching on "the" (tea) matched inside "Menthe".
    result = classify_food_type("Rosport mat Menthe 0,50 l non consigné")
    assert result is None or result[0] != "hot_beverage_tea"


def test_fromage_frais_is_not_classified_as_dense_hard_cheese():
    # "Fromage frais" (fresh cheese, ~90 kcal/100g) is much lower-calorie
    # than hard/aged cheese (~350 kcal/100g) -- the generic "fromage"
    # keyword must not shadow the more specific "fromage frais" phrase.
    food_type, kcal = classify_food_type("Mini fromage frais avec coulis de fruits de saison")
    assert food_type == "fresh_cheese"
    assert kcal == 90


def test_poche_aux_pommes_is_pastry_not_raw_fruit():
    # A baked apple turnover is far more caloric than raw apple -- the
    # multi-word pastry phrase must win over the generic "pomme" keyword.
    food_type, kcal = classify_food_type("Poche aux pommes")
    assert food_type == "pastry_sweet"
    assert kcal == 260


def test_longest_matching_keyword_wins_over_shorter_ones():
    # "Yaourt aux fruits" contains both "fruit" and "yaourt" as
    # substrings -- the longer, more specific keyword must win.
    food_type, _ = classify_food_type("Yaourt aux fruits Luxlait 125 g")
    assert food_type == "dairy"


def test_iced_tea_is_not_classified_as_the_flavor_fruit():
    # "Fuze Tea - Black Tea Pêche/Hibiscus" is an iced-tea drink; "Pêche"
    # (peach) is only the flavor descriptor, not the drink type.
    food_type, _ = classify_food_type("Fuze Tea - Black Tea Pêche/Hibiscus 0,20 l btl")
    assert food_type == "iced_tea"
