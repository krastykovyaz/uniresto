from orderability_engine.pricing import MEAL_TIER_PRICES, SANDWICH_PRICE, compute_formula_total


def _line(category, quantity=1):
    return {"category": category, "quantity": quantity}


def test_main_dish_alone():
    result = compute_formula_total([_line("Non-végétarien")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 0
    assert result["dessert_count"] == 0
    assert result["total"] == 6.00
    assert result["formula_count"] == 1
    assert result["reason"] is None


def test_main_plus_starter():
    result = compute_formula_total([_line("Végétarien"), _line("Entrée")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["total"] == 7.00
    assert result["reason"] is None


def test_main_plus_starter_plus_dessert():
    result = compute_formula_total([_line("Végan"), _line("Entrée"), _line("Dessert")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["dessert_count"] == 1
    assert result["total"] == 8.00
    assert result["reason"] is None


def test_included_sides_do_not_add_to_the_total():
    # Féculents/Légumes are bundled free -- adding them must not raise the price.
    result = compute_formula_total([_line("Non-végétarien"), _line("Féculents"), _line("Légumes")])
    assert result["total"] == 6.00


def test_starter_alone_with_no_main_cannot_be_priced():
    # A starter only upgrades a main's tier -- with no main at all,
    # there's nothing to price (a starter isn't sold standalone).
    result = compute_formula_total([_line("Entrée")])
    assert result["formula_count"] == 1
    assert result["main_count"] == 0
    assert result["starter_count"] == 1
    assert result["total"] is None
    assert result["reason"] == "no_main_dish"


def test_dessert_alone_with_no_main_cannot_be_priced():
    result = compute_formula_total([_line("Dessert")])
    assert result["total"] is None
    assert result["reason"] == "no_main_dish"


def test_no_selection_at_all_is_unpriced_with_no_reason():
    result = compute_formula_total([])
    assert result["formula_count"] == 0
    assert result["total"] is None
    assert result["reason"] is None


def test_main_plus_dessert_without_starter_cannot_be_priced():
    # A dessert only upgrades the tier when a starter is already present
    # -- skipping straight from main to dessert isn't a priced combination.
    result = compute_formula_total([_line("Non-végétarien"), _line("Dessert")])
    assert result["total"] is None
    assert result["reason"] == "dessert_without_starter"


def test_snack_and_constant_products_are_not_part_of_the_pricing():
    result = compute_formula_total([_line("Snack à emporter")])
    assert result["formula_count"] == 0
    assert result["total"] is None


def test_sandwich_is_priced_at_4_euro_independent_of_the_meal_formula():
    result = compute_formula_total([_line("01.1 Sandwiches végétariens")])
    assert result["sandwich_count"] == 1
    assert result["formula_count"] == 1
    assert result["total"] == 4.00
    assert result["reason"] is None


def test_all_four_real_sandwich_categories_are_priced_the_same():
    result = compute_formula_total(
        [
            _line("01.1 Sandwiches végétariens"),
            _line("01.2 Sandwiches végans"),
            _line("01.3 Sandwiches non-végétariens"),
            _line("01.4 Sandwiches sans gluten"),
        ]
    )
    assert result["sandwich_count"] == 4
    assert result["total"] == round(4.00 * 4, 2)


def test_sandwich_adds_on_top_of_a_main_plus_starter_meal():
    result = compute_formula_total([_line("Non-végétarien"), _line("Entrée"), _line("01.3 Sandwiches non-végétariens")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["sandwich_count"] == 1
    assert result["formula_count"] == 3
    assert result["total"] == round(7.00 + 4.00, 2)


def test_other_constant_products_besides_sandwiches_stay_unpriced():
    # Drinks/pastries/etc (Part 18's original "not part of this pricing"
    # note) are unaffected -- only the 4 real sandwich categories changed.
    result = compute_formula_total([_line("02. Viennoiseries"), _line("10.1 Boissons froides - Eau minérale et pétillante")])
    assert result["formula_count"] == 0
    assert result["total"] is None


def test_two_full_meals_price_each_at_the_full_tier():
    # Two mains, each with its own starter and dessert -- both pair up,
    # both hit the top tier.
    result = compute_formula_total([_line("Non-végétarien", 2), _line("Entrée", 2), _line("Dessert", 2)])
    assert result["formula_count"] == 6
    assert result["main_count"] == 2
    assert result["total"] == round(8.00 * 2, 2)


def test_extra_main_with_no_starter_of_its_own_stays_at_the_plain_tier():
    # 2 mains but only 1 starter -- pairing is greedy and one-for-one, so
    # only one main is upgraded; the other stays plain rather than both
    # being overcharged at the main+starter tier.
    result = compute_formula_total([_line("Non-végétarien", 2), _line("Entrée", 1)])
    assert result["formula_count"] == 3
    assert result["main_count"] == 2
    assert result["starter_count"] == 1
    assert result["total"] == round(7.00 + 6.00, 2)
    assert result["reason"] is None


def test_multiple_different_main_categories_are_summed():
    result = compute_formula_total([_line("Non-végétarien", 1), _line("Végétarien", 1)])
    assert result["formula_count"] == 2
    assert result["main_count"] == 2
    assert result["total"] == round(6.00 * 2, 2)


def test_meal_tier_and_sandwich_prices_match_the_given_values_exactly():
    assert MEAL_TIER_PRICES == {"main": 6.00, "main_starter": 7.00, "main_starter_dessert": 8.00}
    assert SANDWICH_PRICE == 4.00
