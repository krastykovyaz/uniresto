"""The "mean" price tier (halfway between adult and learner) and the setting that chooses it.

The real adult and learner tables are recorded in tests/fixtures/price_lists_2026_27.json; the mean is
derived from them, and PRICE_TIER picks which one the app charges. Going back to the real adult price is
a settings change (unset PRICE_TIER), so these tests also pin that the real tables never move."""

import json
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from orderability_engine import pricing as P

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = json.loads((ROOT / "tests" / "fixtures" / "price_lists_2026_27.json").read_text(encoding="utf-8"))


def _half_up(a, b):
    return float(((Decimal(str(a)) + Decimal(str(b))) / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _live(tier):
    meal, snack, groups = P._tier_tables(tier)
    return {"meal": meal, "snack": snack, "named": {label: prices for label, _c, prices in groups}}


# --- the real prices are remembered, and never touched ----------------------------------------


@pytest.mark.parametrize("tier", ["adulte", "apprenant"])
def test_the_real_price_lists_match_the_recorded_2026_27_snapshot(tier):
    assert _live(tier) == SNAPSHOT[tier]


def test_the_real_main_dish_prices(monkeypatch):
    monkeypatch.delenv("PRICE_TIER", raising=False)
    line = [{"category": "Non-végétarien", "name": "x", "quantity": 1}]
    assert P.compute_formula_total(line)["total"] == 6.70
    assert P.compute_formula_total(line, tier="apprenant")["total"] == 3.70


# --- the mean ---------------------------------------------------------------------------------


def test_the_four_headline_means():
    assert P.MEAL_TIER_PRICES_MEAN == {"main": 5.20, "main_starter": 5.95, "main_starter_dessert": 6.70}
    assert P.SNACK_PRICE_MEAN == 4.15


def test_every_named_item_is_the_half_up_average_of_its_two_prices():
    adult, learner = SNAPSHOT["adulte"]["named"], SNAPSHOT["apprenant"]["named"]
    mean = _live("mean")["named"]
    assert set(mean) == set(adult)
    changed = 0
    for label, table in adult.items():
        assert set(mean[label]) == set(table), label
        for name, price in table.items():
            expected = _half_up(price, learner[label][name]) if name in learner[label] else price
            assert mean[label][name] == expected, (label, name)
            changed += mean[label][name] != price
    assert changed == 67  # the 67 items whose two tiers differ; the other 40 are identical or adult-only


def test_an_item_with_only_an_adult_price_keeps_it():
    adult, learner = SNAPSHOT["adulte"]["named"]["dairy"], SNAPSHOT["apprenant"]["named"]["dairy"]
    adult_only = set(adult) - set(learner)
    assert len(adult_only) == 2
    for name in adult_only:
        assert P.NAME_PRICED_GROUPS_MEAN[[g[0] for g in P.NAME_PRICED_GROUPS_MEAN].index("dairy")][2][name] == adult[name]


def test_a_mean_price_always_sits_between_the_two_real_ones():
    adult, learner = SNAPSHOT["adulte"]["named"], SNAPSHOT["apprenant"]["named"]
    for label, table in _live("mean")["named"].items():
        for name, price in table.items():
            low, high = sorted([adult[label][name], learner[label].get(name, adult[label][name])])
            assert low <= price <= high, (label, name)


# --- the setting ------------------------------------------------------------------------------


@pytest.mark.parametrize("value, expected", [(None, "adulte"), ("", "adulte"), ("adulte", "adulte"), ("ADULT", "adulte"), ("mean", "mean"), (" Mean ", "mean")])
def test_price_tier_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("PRICE_TIER", raising=False)
    else:
        monkeypatch.setenv("PRICE_TIER", value)
    assert P.active_price_tier() == expected


def test_an_unknown_setting_falls_back_to_the_real_adult_price(monkeypatch, caplog):
    monkeypatch.setenv("PRICE_TIER", "cheap")
    assert P.active_price_tier() == "adulte"
    assert "using the adult price" in caplog.text


@pytest.mark.parametrize("tier_env, main, formule2, formule1, snack", [("adulte", 6.70, 7.70, 8.70, 4.80), ("mean", 5.20, 5.95, 6.70, 4.15)])
def test_the_formula_total_follows_the_setting(monkeypatch, tier_env, main, formule2, formule1, snack):
    monkeypatch.setenv("PRICE_TIER", tier_env)
    m, s, d = ({"category": c, "name": "x", "quantity": 1} for c in ("Végétarien", "Entrée", "Dessert"))
    assert P.compute_formula_total([m])["total"] == main
    assert P.compute_formula_total([m, s])["total"] == formule2
    assert P.compute_formula_total([m, d])["total"] == formule2
    assert P.compute_formula_total([m, s, d])["total"] == formule1
    assert P.compute_formula_total([{"category": "Snack à emporter", "name": "x", "quantity": 1}])["total"] == snack


def test_an_explicit_tier_beats_the_setting(monkeypatch):
    monkeypatch.setenv("PRICE_TIER", "mean")
    line = [{"category": "Végétarien", "name": "x", "quantity": 1}]
    assert P.compute_formula_total(line, tier="adulte")["total"] == 6.70
    assert P.compute_formula_total(line, tier="apprenant")["total"] == 3.70


def test_the_named_item_prices_follow_the_setting(monkeypatch):
    sandwich = next(iter(P.SANDWICH_PRICES))
    cat = sorted(P.SANDWICH_CATEGORIES)[0]
    line = [{"category": cat, "name": sandwich, "quantity": 1}]
    monkeypatch.setenv("PRICE_TIER", "adulte")
    adult = P.compute_formula_total(line)["total"]
    monkeypatch.setenv("PRICE_TIER", "mean")
    mean = P.compute_formula_total(line)["total"]
    assert adult == P.SANDWICH_PRICES[sandwich]
    assert mean == _half_up(P.SANDWICH_PRICES[sandwich], P.SANDWICH_PRICES_APPRENANT[sandwich]) < adult


def test_the_two_tier_email_breakdown_never_follows_the_setting(monkeypatch):
    # The courier/admin email shows BOTH real prices side by side; it must not change with PRICE_TIER.
    items = [{"category": "Végétarien", "name": "x", "quantity": 1}]
    monkeypatch.setenv("PRICE_TIER", "adulte")
    before = P.category_breakdown(items)
    monkeypatch.setenv("PRICE_TIER", "mean")
    assert P.category_breakdown(items) == before == [{"category": "Meal formula", "adulte_total": 6.7, "apprenant_total": 3.7}]


def test_an_orders_estimate_follows_the_setting(tmp_path, monkeypatch):
    import datetime

    from orderability_engine.orders import OrderStore

    store = OrderStore(tmp_path / "orders.db")
    order_id = store.create_order("A", "A", datetime.date(2026, 9, 24), [{"category": "Végétarien", "name": "x", "price": None, "quantity": 1}])
    monkeypatch.setenv("PRICE_TIER", "adulte")
    assert store.get_order(order_id)["totals"]["formula"]["total"] == 6.70
    monkeypatch.setenv("PRICE_TIER", "mean")
    assert store.get_order(order_id)["totals"]["formula"]["total"] == 5.20


# --- the browser's copy of the tables ------------------------------------------------------------


def test_the_browsers_built_in_tables_equal_the_real_adult_prices():
    """static/pricing.js carries its own copy of the real adult tables (used until/unless the server answers).
    It must equal the recorded adult prices exactly."""
    script = (
        "import * as p from './static/pricing.js';"
        "const names = %s;"
        "const out = {meal: p.MEAL_TIER_PRICES, snack: p.SNACK_PRICE, named: Object.fromEntries(names.map((n) => [n, p[n]]))};"
        "console.log(JSON.stringify(out));" % json.dumps(sorted(P.JS_TABLE_NAMES.values()))
    )
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    js = json.loads(out)
    adult = SNAPSHOT["adulte"]
    assert js["meal"] == adult["meal"] and js["snack"] == adult["snack"]
    for label, js_name in P.JS_TABLE_NAMES.items():
        assert js["named"][js_name] == adult["named"][label], js_name


def test_the_payload_always_carries_the_real_adult_prices_for_a_discount_banner(monkeypatch):
    for tier in ("adulte", "mean"):
        monkeypatch.setenv("PRICE_TIER", tier)
        assert P.price_tables_payload()["list_prices"] == {"main": 6.70, "main_starter": 7.70, "main_starter_dessert": 8.70, "snack": 4.80}
