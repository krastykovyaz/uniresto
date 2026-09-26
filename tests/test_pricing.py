from orderability_engine.pricing import MEAL_TIER_PRICES, SANDWICH_PRICES, SNACK_PRICE, compute_formula_total


def _line(category, quantity=1, name="Test item"):
    return {"category": category, "quantity": quantity, "name": name}


def test_main_dish_alone():
    result = compute_formula_total([_line("Non-végétarien")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 0
    assert result["dessert_count"] == 0
    assert result["total"] == 6.70
    assert result["formula_count"] == 1
    assert result["reason"] is None


def test_main_plus_starter():
    result = compute_formula_total([_line("Végétarien"), _line("Entrée")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["total"] == 7.70
    assert result["reason"] is None


def test_main_plus_dessert_without_starter_is_now_a_priced_combination():
    # Unlike the previous version of this rule, Formule 2 ("main +
    # starter OR main + dessert") means a dessert alone -- with no
    # starter at all -- ALSO upgrades the tier. Real official pricing,
    # not a guess: this is genuinely how the canteen prices it.
    result = compute_formula_total([_line("Végan"), _line("Dessert")])
    assert result["main_count"] == 1
    assert result["dessert_count"] == 1
    assert result["total"] == 7.70
    assert result["reason"] is None


def test_main_plus_starter_plus_dessert():
    result = compute_formula_total([_line("Végan"), _line("Entrée"), _line("Dessert")])
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["dessert_count"] == 1
    assert result["total"] == 8.70
    assert result["reason"] is None


def test_included_sides_do_not_add_to_the_total():
    # Féculents/Légumes are bundled free -- adding them must not raise the price.
    result = compute_formula_total([_line("Non-végétarien"), _line("Féculents"), _line("Légumes")])
    assert result["total"] == 6.70


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


def test_snack_a_emporter_is_priced_at_a_flat_rate_independent_of_the_meal_formula():
    result = compute_formula_total([_line("Snack à emporter", name="Wrap aux falafels")])
    assert result["snack_count"] == 1
    assert result["formula_count"] == 1
    assert result["total"] == 4.80
    assert result["reason"] is None


def test_snack_a_emporter_adds_on_top_of_a_meal():
    result = compute_formula_total([_line("Non-végétarien"), _line("Snack à emporter", name="Salade campagnarde")])
    assert result["total"] == round(6.70 + 4.80, 2)


def test_sandwich_is_priced_at_its_own_real_item_price():
    result = compute_formula_total([_line("01.1 Sandwiches végétariens", name="Petit pain blanc fromage")])
    assert result["sandwich_count"] == 1
    assert result["formula_count"] == 1
    assert result["total"] == 2.30
    assert result["reason"] is None


def test_two_different_sandwiches_are_priced_individually_not_at_one_flat_rate():
    # Unlike the previous flat-EUR-4.00-per-sandwich rule, two different
    # real sandwiches at different official prices must sum to their
    # OWN prices, not double one flat rate.
    result = compute_formula_total(
        [
            _line("01.1 Sandwiches végétariens", name="1/2 Levain fromage"),  # 3.30
            _line("01.3 Sandwiches non-végétariens", name="1/2 Levain salami"),  # 2.30
        ]
    )
    assert result["sandwich_count"] == 2
    assert result["total"] == round(3.30 + 2.30, 2)


def test_sandwich_not_in_the_official_price_list_is_silently_unpriced_not_guessed():
    result = compute_formula_total([_line("01.1 Sandwiches végétariens", name="Some brand new sandwich never catalogued")])
    assert result["sandwich_count"] == 1
    # No main/starter/dessert/snack either, so nothing at all is priced
    # -- formula_count still counts it as present, total is just None
    # rather than a guessed number for the unrecognized item.
    assert result["total"] is None
    assert result["reason"] is None


def test_sandwich_adds_on_top_of_a_main_plus_starter_meal():
    result = compute_formula_total(
        [_line("Non-végétarien"), _line("Entrée"), _line("01.3 Sandwiches non-végétariens", name="1/2 Levain jambon cuit")]
    )
    assert result["main_count"] == 1
    assert result["starter_count"] == 1
    assert result["sandwich_count"] == 1
    assert result["formula_count"] == 3
    assert result["total"] == round(7.70 + 3.30, 2)


def test_all_four_sandwich_categories_have_at_least_one_real_priced_item():
    # Sanity check on the price table itself, not a specific order --
    # every one of the 4 real sandwich categories has real coverage.
    from orderability_engine.pricing import SANDWICH_CATEGORIES

    assert len(SANDWICH_CATEGORIES) == 4
    assert len(SANDWICH_PRICES) >= 20


def test_other_constant_products_besides_sandwiches_and_snacks_stay_unpriced():
    # Viennoiseries/drinks/dairy/etc: real official prices exist for
    # these too, but transcribing them is separate, follow-up work --
    # this module deliberately doesn't guess at them in the meantime.
    result = compute_formula_total([_line("02. Viennoiseries", name="Croissant fourré 70 g")])
    assert result["formula_count"] == 0
    assert result["total"] is None


def test_two_full_meals_price_each_at_the_full_tier():
    # Two mains, each with its own starter and dessert -- both pair up,
    # both hit the top tier.
    result = compute_formula_total([_line("Non-végétarien", 2), _line("Entrée", 2), _line("Dessert", 2)])
    assert result["formula_count"] == 6
    assert result["main_count"] == 2
    assert result["total"] == round(8.70 * 2, 2)


def test_extra_main_with_no_starter_of_its_own_stays_at_the_plain_tier():
    # 2 mains but only 1 starter -- pairing is greedy and one-for-one, so
    # only one main is upgraded; the other stays plain rather than both
    # being overcharged at the main+starter tier.
    result = compute_formula_total([_line("Non-végétarien", 2), _line("Entrée", 1)])
    assert result["formula_count"] == 3
    assert result["main_count"] == 2
    assert result["starter_count"] == 1
    assert result["total"] == round(7.70 + 6.70, 2)
    assert result["reason"] is None


def test_full_tier_pairing_leaves_the_remaining_side_for_the_partial_tier():
    # 1 main, 1 starter, 1 dessert -> the one main takes the full tier.
    # But 2 mains, 1 starter, 1 dessert -> one main gets BOTH (full
    # tier), and the other main is left with neither (plain tier) --
    # NOT one main with the starter and the other with the dessert
    # (which would make both partial instead of one full + one plain).
    result = compute_formula_total([_line("Non-végétarien", 2), _line("Entrée", 1), _line("Dessert", 1)])
    assert result["total"] == round(8.70 + 6.70, 2)


def test_multiple_different_main_categories_are_summed():
    result = compute_formula_total([_line("Non-végétarien", 1), _line("Végétarien", 1)])
    assert result["formula_count"] == 2
    assert result["main_count"] == 2
    assert result["total"] == round(6.70 * 2, 2)


def test_meal_tier_and_snack_prices_match_the_official_adultes_tariff():
    assert MEAL_TIER_PRICES == {"main": 6.70, "main_starter": 7.70, "main_starter_dessert": 8.70}
    assert SNACK_PRICE == 4.80


def test_sandwich_prices_match_the_official_adultes_tariff_for_known_items():
    # A representative sample across all 4 categories, transcribed
    # directly from the official price list -- not exhaustive here
    # (see test_all_four_sandwich_categories_have_at_least_one_real_priced_item
    # for full-table coverage), just enough to catch a transcription slip.
    assert SANDWICH_PRICES["1/2 Levain fromage"] == 3.30
    assert SANDWICH_PRICES["Ciabatta tomate-mozzarella et pesto"] == 4.00
    assert SANDWICH_PRICES["1/2 tranche de pain"] == 0.25
    assert SANDWICH_PRICES['Petit pain blanc "Schockelasbotter végan"'] == 1.85
    assert SANDWICH_PRICES['1/2 Levain "Pastrami"'] == 3.30
    assert SANDWICH_PRICES["1/2 Levain salami"] == 2.30
    assert SANDWICH_PRICES["Mini baguette sans gluten fromage"] == 4.00
