from orderability_engine.pricing import CATEGORY_PRICES, compute_formula_total


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
    assert result["total"] == 8.00


def test_main_plus_starter_plus_dessert():
    result = compute_formula_total([_line("Végan"), _line("Entrée"), _line("Dessert")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["dessert_count"] == 1
    assert result["total"] == 10.00


def test_included_sides_do_not_add_to_the_total():
    # Féculents/Légumes are bundled free -- adding them must not raise the price.
    result = compute_formula_total([_line("Non-végétarien"), _line("Féculents"), _line("Légumes")])
    assert result["total"] == 6.00


def test_starter_alone_is_priced_on_its_own():
    # Flat per-item pricing (unlike the old bundle-tier rule) can price a
    # starter/dessert bought without a main dish at all.
    result = compute_formula_total([_line("Entrée")])
    assert result["formula_count"] == 1
    assert result["main_count"] == 0
    assert result["starter_count"] == 1
    assert result["total"] == 2.00
    assert result["reason"] is None


def test_no_selection_at_all_is_unpriced_with_no_reason():
    result = compute_formula_total([])
    assert result["formula_count"] == 0
    assert result["total"] is None
    assert result["reason"] is None


def test_main_plus_dessert_without_starter_is_priced_too():
    # Every combination is priceable under flat per-item pricing -- there
    # is no "combination this data has no price for" case anymore.
    result = compute_formula_total([_line("Non-végétarien"), _line("Dessert")])
    assert result["total"] == 8.00
    assert result["formula_count"] == 2
    assert result["reason"] is None


def test_snack_and_constant_products_are_not_part_of_the_pricing():
    result = compute_formula_total([_line("Snack à emporter")])
    assert result["formula_count"] == 0
    assert result["total"] is None


def test_sandwich_is_priced_at_4_euro():
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


def test_sandwich_combines_with_a_main_and_starter():
    result = compute_formula_total([_line("Non-végétarien"), _line("Entrée"), _line("01.3 Sandwiches non-végétariens")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["sandwich_count"] == 1
    assert result["formula_count"] == 3
    assert result["total"] == round(6.00 + 2.00 + 4.00, 2)


def test_other_constant_products_besides_sandwiches_stay_unpriced():
    # Drinks/pastries/etc (Part 18's original "not part of this pricing"
    # note) are unaffected -- only the 4 real sandwich categories changed.
    result = compute_formula_total([_line("02. Viennoiseries"), _line("10.1 Boissons froides - Eau minérale et pétillante")])
    assert result["formula_count"] == 0
    assert result["total"] is None


def test_quantity_multiplies_each_course_and_the_total():
    # Two full main+starter+dessert meals.
    result = compute_formula_total([_line("Non-végétarien", 2), _line("Entrée", 1), _line("Dessert", 1)])
    assert result["formula_count"] == 4
    assert result["main_count"] == 2
    assert result["total"] == round(6.00 * 2 + 2.00 + 2.00, 2)


def test_multiple_different_main_categories_are_summed():
    result = compute_formula_total([_line("Non-végétarien", 1), _line("Végétarien", 1)])
    assert result["formula_count"] == 2
    assert result["main_count"] == 2
    assert result["total"] == round(6.00 * 2, 2)


def test_all_category_prices_match_the_given_values_exactly():
    assert CATEGORY_PRICES == {"main": 6.00, "starter": 2.00, "dessert": 2.00, "sandwich": 4.00}
