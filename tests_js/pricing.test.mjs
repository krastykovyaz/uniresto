import { test } from "node:test";
import assert from "node:assert/strict";
import { MEAL_TIER_PRICES, SANDWICH_PRICE, computeFormulaTotal } from "../static/pricing.js";

const line = (category, quantity = 1) => ({ category, quantity });

test("main dish alone", () => {
  const r = computeFormulaTotal([line("Non-végétarien")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.total, 6.0);
  assert.equal(r.reason, null);
});

test("main plus starter", () => {
  const r = computeFormulaTotal([line("Végétarien"), line("Entrée")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.total, 7.0);
  assert.equal(r.reason, null);
});

test("main plus starter plus dessert", () => {
  const r = computeFormulaTotal([line("Végan"), line("Entrée"), line("Dessert")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.dessertCount, 1);
  assert.equal(r.total, 8.0);
  assert.equal(r.reason, null);
});

test("included sides (Féculents/Légumes) do not add to the total", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("Féculents"), line("Légumes")]);
  assert.equal(r.total, 6.0);
});

test("starter alone with no main cannot be priced", () => {
  // A starter only upgrades a main's tier -- with no main at all,
  // there's nothing to price (a starter isn't sold standalone).
  const r = computeFormulaTotal([line("Entrée")]);
  assert.equal(r.formulaCount, 1);
  assert.equal(r.mainCount, 0);
  assert.equal(r.starterCount, 1);
  assert.equal(r.total, null);
  assert.equal(r.reason, "no_main_dish");
});

test("dessert alone with no main cannot be priced", () => {
  const r = computeFormulaTotal([line("Dessert")]);
  assert.equal(r.total, null);
  assert.equal(r.reason, "no_main_dish");
});

test("empty selection is unpriced with no reason", () => {
  const r = computeFormulaTotal([]);
  assert.equal(r.total, null);
  assert.equal(r.reason, null);
});

test("main plus dessert without starter cannot be priced", () => {
  // A dessert only upgrades the tier when a starter is already present
  // -- skipping straight from main to dessert isn't a priced combination.
  const r = computeFormulaTotal([line("Non-végétarien"), line("Dessert")]);
  assert.equal(r.total, null);
  assert.equal(r.reason, "dessert_without_starter");
});

test("two full meals price each at the full tier", () => {
  const r = computeFormulaTotal([line("Non-végétarien", 2), line("Entrée", 2), line("Dessert", 2)]);
  assert.equal(r.formulaCount, 6);
  assert.equal(r.mainCount, 2);
  assert.equal(r.total, Math.round(8.0 * 2 * 100) / 100);
});

test("extra main with no starter of its own stays at the plain tier", () => {
  // 2 mains but only 1 starter -- pairing is greedy and one-for-one, so
  // only one main is upgraded; the other stays plain rather than both
  // being overcharged at the main+starter tier.
  const r = computeFormulaTotal([line("Non-végétarien", 2), line("Entrée", 1)]);
  assert.equal(r.formulaCount, 3);
  assert.equal(r.mainCount, 2);
  assert.equal(r.starterCount, 1);
  assert.equal(r.total, Math.round((7.0 + 6.0) * 100) / 100);
  assert.equal(r.reason, null);
});

test("multiple different main categories are summed", () => {
  const r = computeFormulaTotal([line("Non-végétarien", 1), line("Végétarien", 1)]);
  assert.equal(r.formulaCount, 2);
  assert.equal(r.mainCount, 2);
  assert.equal(r.total, Math.round(6.0 * 2 * 100) / 100);
});

test("meal tier and sandwich prices match the given values exactly", () => {
  assert.deepEqual(MEAL_TIER_PRICES, { main: 6.0, main_starter: 7.0, main_starter_dessert: 8.0 });
  assert.equal(SANDWICH_PRICE, 4.0);
});

test("sandwich is priced at 4 euro independent of the meal formula", () => {
  const r = computeFormulaTotal([line("01.1 Sandwiches végétariens")]);
  assert.equal(r.sandwichCount, 1);
  assert.equal(r.formulaCount, 1);
  assert.equal(r.total, 4.0);
  assert.equal(r.reason, null);
});

test("all four real sandwich categories are priced the same", () => {
  const r = computeFormulaTotal([
    line("01.1 Sandwiches végétariens"),
    line("01.2 Sandwiches végans"),
    line("01.3 Sandwiches non-végétariens"),
    line("01.4 Sandwiches sans gluten"),
  ]);
  assert.equal(r.sandwichCount, 4);
  assert.equal(r.total, Math.round(4.0 * 4 * 100) / 100);
});

test("sandwich adds on top of a main plus starter meal", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("Entrée"), line("01.3 Sandwiches non-végétariens")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.sandwichCount, 1);
  assert.equal(r.formulaCount, 3);
  assert.equal(r.total, Math.round((7.0 + 4.0) * 100) / 100);
});

test("other Constant Products besides sandwiches stay unpriced", () => {
  const r = computeFormulaTotal([line("02. Viennoiseries"), line("10.1 Boissons froides - Eau minérale et pétillante")]);
  assert.equal(r.formulaCount, 0);
  assert.equal(r.total, null);
});
