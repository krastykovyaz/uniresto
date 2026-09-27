from orderability_engine.menu_service import requires_early_order


def test_grill_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Mixed grill de saucisses, sauce moutarde") is True


def test_grilled_steak_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Faux-filet de boeuf grillé sauce Béarnaise") is True


def test_salmon_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Pavé de saumon, sauce citron") is True
    assert requires_early_order("Végétarien", "Salmon teriyaki bowl") is True


def test_bbq_main_dish_requires_early_order():
    assert requires_early_order("Non-végétarien", "Poulet BBQ maison") is True


def test_grilled_starter_does_not_require_early_order():
    # Real menu item (Entrée, not a main) -- "grillé" here just describes
    # the butternut, not a grill-station dish needing pre-order.
    assert requires_early_order("Entrée", "Salade de quinoa au butternut grillé") is False


def test_grilled_sandwich_does_not_require_early_order():
    # Real menu item -- a cold sandwich, not a grill-station dish, even
    # though its name mentions grilled vegetables.
    assert requires_early_order("01.2 Sandwiches végans", "1/2 Levain Humi (houmous aux légumes locaux grillés)") is False


def test_ordinary_main_dish_does_not_require_early_order():
    assert requires_early_order("Non-végétarien", "Rôti de porc Orloff") is False


def test_case_insensitive_matching():
    assert requires_early_order("Non-végétarien", "GRILL MIXTE") is True
