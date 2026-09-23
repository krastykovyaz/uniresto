import { test } from "node:test";
import assert from "node:assert/strict";
import { CATEGORY_PRICES, computeFormulaTotal } from "../static/pricing.js";

const line = (category, quantity = 1) => ({ category, quantity });

test("main dish alone", () => {
  const r = computeFormulaTotal([line("Non-végétarien")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.total, 6.0);
});

test("main plus starter", () => {
  const r = computeFormulaTotal([line("Végétarien"), line("Entrée")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.total, 8.0);
});

test("main plus starter plus dessert", () => {
  const r = computeFormulaTotal([line("Végan"), line("Entrée"), line("Dessert")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.dessertCount, 1);
  assert.equal(r.total, 10.0);
});

test("included sides (Féculents/Légumes) do not add to the total", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("Féculents"), line("Légumes")]);
  assert.equal(r.total, 6.0);
});

test("starter alone is priced on its own", () => {
  // Flat per-item pricing (unlike the old bundle-tier rule) can price a
  // starter/dessert bought without a main dish at all.
  const r = computeFormulaTotal([line("Entrée")]);
  assert.equal(r.formulaCount, 1);
  assert.equal(r.mainCount, 0);
  assert.equal(r.starterCount, 1);
  assert.equal(r.total, 2.0);
  assert.equal(r.reason, null);
});

test("empty selection is unpriced with no reason", () => {
  const r = computeFormulaTotal([]);
  assert.equal(r.total, null);
  assert.equal(r.reason, null);
});

test("main plus dessert without starter is priced too", () => {
  // Every combination is priceable under flat per-item pricing -- there
  // is no "combination this data has no price for" case anymore.
  const r = computeFormulaTotal([line("Non-végétarien"), line("Dessert")]);
  assert.equal(r.total, 8.0);
  assert.equal(r.formulaCount, 2);
  assert.equal(r.reason, null);
});

test("quantity multiplies each course and the total", () => {
  const r = computeFormulaTotal([line("Non-végétarien", 2), line("Entrée", 1), line("Dessert", 1)]);
  assert.equal(r.formulaCount, 4);
  assert.equal(r.mainCount, 2);
  assert.equal(r.total, Math.round((6.0 * 2 + 2.0 + 2.0) * 100) / 100);
});

test("multiple different main categories are summed", () => {
  const r = computeFormulaTotal([line("Non-végétarien", 1), line("Végétarien", 1)]);
  assert.equal(r.formulaCount, 2);
  assert.equal(r.mainCount, 2);
  assert.equal(r.total, Math.round(6.0 * 2 * 100) / 100);
});

test("category prices match the given values exactly", () => {
  assert.deepEqual(CATEGORY_PRICES, { main: 6.0, starter: 2.0, dessert: 2.0, sandwich: 4.0 });
});

test("sandwich is priced at 4 euro", () => {
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

test("sandwich combines with a main and starter", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("Entrée"), line("01.3 Sandwiches non-végétariens")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.sandwichCount, 1);
  assert.equal(r.formulaCount, 3);
  assert.equal(r.total, Math.round((6.0 + 2.0 + 4.0) * 100) / 100);
});

test("other Constant Products besides sandwiches stay unpriced", () => {
  const r = computeFormulaTotal([line("02. Viennoiseries"), line("10.1 Boissons froides - Eau minérale et pétillante")]);
  assert.equal(r.formulaCount, 0);
  assert.equal(r.total, null);
});
