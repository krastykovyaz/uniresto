from restopolis.weight import format_weight, parse_weight


def test_parses_grams():
    assert parse_weight("Bretzel salé 80 g") == (80.0, "g")


def test_parses_french_decimal_liters():
    assert parse_weight("Coca Cola 0,20 l btl") == (0.2, "l")


def test_parses_kg():
    assert parse_weight("Sac de riz 2 kg") == (2.0, "kg")


def test_converts_cl_to_ml():
    assert parse_weight("Verre 25 cl") == (250.0, "ml")


def test_picks_rightmost_match_when_multiple_present():
    # "130 ml" is the real portion size; the parenthetical flavor list
    # after it must not confuse extraction.
    assert parse_weight("Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)") == (130.0, "ml")


def test_no_weight_returns_none_none():
    assert parse_weight("Rôti de porc Orloff, jus lié") == (None, None)


def test_fraction_like_1_2_is_not_mistaken_for_weight():
    assert parse_weight('1/2 Levain fromage') == (None, None)


def test_missing_explicit_unit_is_not_guessed():
    # Real Restopolis data: "Lët'z kola 0,33 btl" -- 0.33 is almost
    # certainly liters, but the text doesn't say so, so we don't guess.
    assert parse_weight("Lët'z kola 0,33 btl") == (None, None)


def test_parses_piece_unit():
    assert parse_weight("Tarte 1 pièce") == (1.0, "piece")
    assert parse_weight("Muffins 2 pieces") == (2.0, "piece")


def test_format_weight_known():
    assert format_weight(80.0, "g") == "80 g"
    assert format_weight(0.2, "l") == "0.2 l"
    assert format_weight(1.0, "piece") == "1 pc"
    assert format_weight(3.0, "piece") == "3 pc"


def test_format_weight_unknown():
    assert format_weight(None, None) == "Portion size not specified"
