import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COLD_DRINK_PRICES,
  HOT_DRINK_PRICES,
  MEAL_TIER_PRICES,
  REUSABLE_PACKAGING_PRICES,
  SANDWICH_CATEGORIES,
  SANDWICH_PRICES,
  SNACK_PRICE,
  VIENNOISERIE_PRICES,
  computeFormulaTotal,
} from "../static/pricing.js";

const line = (category, quantity = 1, name = "Test item") => ({ category, quantity, name });

test("main dish alone", () => {
  const r = computeFormulaTotal([line("Non-végétarien")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.total, 6.7);
  assert.equal(r.reason, null);
});

test("main plus starter", () => {
  const r = computeFormulaTotal([line("Végétarien"), line("Entrée")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.total, 7.7);
  assert.equal(r.reason, null);
});

test("main plus dessert without starter is now a priced combination", () => {
  // Unlike the previous version of this rule, Formule 2 ("main + starter
  // OR main + dessert") means a dessert alone -- with no starter at all
  // -- ALSO upgrades the tier. Real official pricing, not a guess.
  const r = computeFormulaTotal([line("Végan"), line("Dessert")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.dessertCount, 1);
  assert.equal(r.total, 7.7);
  assert.equal(r.reason, null);
});

test("main plus starter plus dessert", () => {
  const r = computeFormulaTotal([line("Végan"), line("Entrée"), line("Dessert")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.dessertCount, 1);
  assert.equal(r.total, 8.7);
  assert.equal(r.reason, null);
});

test("included sides (Féculents/Légumes) do not add to the total", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("Féculents"), line("Légumes")]);
  assert.equal(r.total, 6.7);
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
  assert.equal(r.formulaCount, 0);
  assert.equal(r.total, null);
  assert.equal(r.reason, null);
});

test("snack à emporter is priced at a flat rate independent of the meal formula", () => {
  const r = computeFormulaTotal([line("Snack à emporter", 1, "Wrap aux falafels")]);
  assert.equal(r.snackCount, 1);
  assert.equal(r.formulaCount, 1);
  assert.equal(r.total, 4.8);
  assert.equal(r.reason, null);
});

test("snack à emporter adds on top of a meal", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("Snack à emporter", 1, "Salade campagnarde")]);
  assert.equal(r.total, Math.round((6.7 + 4.8) * 100) / 100);
});

test("sandwich is priced at its own real item price", () => {
  const r = computeFormulaTotal([line("01.1 Sandwiches végétariens", 1, "Petit pain blanc fromage")]);
  assert.equal(r.sandwichCount, 1);
  assert.equal(r.formulaCount, 1);
  assert.equal(r.total, 2.3);
  assert.equal(r.reason, null);
});

test("two different sandwiches are priced individually, not at one flat rate", () => {
  const r = computeFormulaTotal([
    line("01.1 Sandwiches végétariens", 1, "1/2 Levain fromage"), // 3.30
    line("01.3 Sandwiches non-végétariens", 1, "1/2 Levain salami"), // 2.30
  ]);
  assert.equal(r.sandwichCount, 2);
  assert.equal(r.total, Math.round((3.3 + 2.3) * 100) / 100);
});

test("sandwich not in the official price list is silently unpriced, not guessed", () => {
  const r = computeFormulaTotal([line("01.1 Sandwiches végétariens", 1, "Some brand new sandwich never catalogued")]);
  assert.equal(r.sandwichCount, 1);
  assert.equal(r.total, null);
  assert.equal(r.reason, null);
});

test("sandwich adds on top of a main plus starter meal", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("Entrée"), line("01.3 Sandwiches non-végétariens", 1, "1/2 Levain jambon cuit")]);
  assert.equal(r.mainCount, 1);
  assert.equal(r.starterCount, 1);
  assert.equal(r.sandwichCount, 1);
  assert.equal(r.formulaCount, 3);
  assert.equal(r.total, Math.round((7.7 + 3.3) * 100) / 100);
});

test("all four sandwich categories have at least one real priced item", () => {
  assert.equal(SANDWICH_CATEGORIES.size, 4);
  assert.ok(Object.keys(SANDWICH_PRICES).length >= 20);
});

test("dairy and ice cream stay unpriced", () => {
  const r = computeFormulaTotal([line("05. Laitages", 1, "Yaourt nature Luxlait 125 g")]);
  assert.equal(r.formulaCount, 0);
  assert.equal(r.total, null);
});

test("two full meals price each at the full tier", () => {
  const r = computeFormulaTotal([line("Non-végétarien", 2), line("Entrée", 2), line("Dessert", 2)]);
  assert.equal(r.formulaCount, 6);
  assert.equal(r.mainCount, 2);
  assert.equal(r.total, Math.round(8.7 * 2 * 100) / 100);
});

test("extra main with no starter of its own stays at the plain tier", () => {
  // 2 mains but only 1 starter -- pairing is greedy and one-for-one, so
  // only one main is upgraded; the other stays plain rather than both
  // being overcharged at the main+starter tier.
  const r = computeFormulaTotal([line("Non-végétarien", 2), line("Entrée", 1)]);
  assert.equal(r.formulaCount, 3);
  assert.equal(r.mainCount, 2);
  assert.equal(r.starterCount, 1);
  assert.equal(r.total, Math.round((7.7 + 6.7) * 100) / 100);
  assert.equal(r.reason, null);
});

test("full tier pairing leaves the remaining side for the partial tier", () => {
  // 2 mains, 1 starter, 1 dessert -> one main takes BOTH (full tier),
  // and the other main is left with neither (plain tier) -- NOT one
  // main with the starter and the other with the dessert (which would
  // make both partial instead of one full + one plain).
  const r = computeFormulaTotal([line("Non-végétarien", 2), line("Entrée", 1), line("Dessert", 1)]);
  assert.equal(r.total, Math.round((8.7 + 6.7) * 100) / 100);
});

test("multiple different main categories are summed", () => {
  const r = computeFormulaTotal([line("Non-végétarien", 1), line("Végétarien", 1)]);
  assert.equal(r.formulaCount, 2);
  assert.equal(r.mainCount, 2);
  assert.equal(r.total, Math.round(6.7 * 2 * 100) / 100);
});

test("meal tier and snack prices match the official adultes tariff", () => {
  assert.deepEqual(MEAL_TIER_PRICES, { main: 6.7, main_starter: 7.7, main_starter_dessert: 8.7 });
  assert.equal(SNACK_PRICE, 4.8);
});

test("sandwich prices match the official adultes tariff for known items", () => {
  assert.equal(SANDWICH_PRICES["1/2 Levain fromage"], 3.3);
  assert.equal(SANDWICH_PRICES["Ciabatta tomate-mozzarella et pesto"], 4.0);
  assert.equal(SANDWICH_PRICES["1/2 tranche de pain"], 0.25);
  assert.equal(SANDWICH_PRICES['Petit pain blanc "Schockelasbotter végan"'], 1.85);
  assert.equal(SANDWICH_PRICES['1/2 Levain "Pastrami"'], 3.3);
  assert.equal(SANDWICH_PRICES["1/2 Levain salami"], 2.3);
  assert.equal(SANDWICH_PRICES["Mini baguette sans gluten fromage"], 4.0);
});

test("viennoiserie is priced and adds on top of a meal", () => {
  const r = computeFormulaTotal([line("Non-végétarien"), line("02. Viennoiseries", 1, "Croissant 50 g")]);
  assert.equal(r.otherItemsCount, 1);
  assert.equal(r.total, Math.round((6.7 + 1.58) * 100) / 100);
});

test("hot drink is priced independent of the meal formula", () => {
  const r = computeFormulaTotal([line("11. Boissons chaudes", 1, "Cappuccino")]);
  assert.equal(r.otherItemsCount, 1);
  assert.equal(r.formulaCount, 1);
  assert.equal(r.total, 2.25);
  assert.equal(r.reason, null);
});

test("cold drink across its three raw categories all price from the same table", () => {
  const r = computeFormulaTotal([
    line("10.1 Boissons froides - Eau minérale et pétillante", 1, "Rosport Blue 0,50 l btl"),
    line("10.2 Boissons froides - Jus", 1, "Ramborn Apple Juice 0,33 btl"),
    line("10.3 Boissons froides - Sodas", 1, "Coca Cola 0,20 l btl"),
  ]);
  assert.equal(r.otherItemsCount, 3);
  assert.equal(r.total, Math.round((1.45 + 1.8 + 1.8) * 100) / 100);
});

test("ecobox refund is a genuine negative line", () => {
  // A deposit charge followed by its own refund nets to 0 -- and since
  // nothing is left actually priced, total reads as null, not a
  // misleading €0.00.
  const r = computeFormulaTotal([
    line("12.1 Emballages et articles réutilisables", 1, "Consigne ECOBOX (500 ml)"),
    line("12.1 Emballages et articles réutilisables", 1, "Remboursement Consigne ECOBOX (500 ml)"),
  ]);
  assert.equal(r.otherItemsCount, 2);
  assert.equal(r.total, null);
});

test("packaging item adds a small amount on top of a sandwich", () => {
  const r = computeFormulaTotal([
    line("01.1 Sandwiches végétariens", 1, "Petit pain blanc fromage"),
    line("12.2 Emballages et articles à usage unique", 1, "Sachet pour sandwiches"),
  ]);
  assert.equal(r.total, Math.round((2.3 + 0.1) * 100) / 100);
});

test("unmapped item in a newly priced category is silently unpriced", () => {
  const r = computeFormulaTotal([line("06. Fruits", 1, "Some brand new fruit never catalogued")]);
  assert.equal(r.otherItemsCount, 1);
  assert.equal(r.total, null);
  assert.equal(r.reason, null);
});

test("new price tables match the official adultes tariff for known items", () => {
  assert.equal(VIENNOISERIE_PRICES["Croissant fourré 70 g"], 1.77);
  assert.equal(HOT_DRINK_PRICES["Espresso double"], 2.25);
  assert.equal(HOT_DRINK_PRICES["Thermo Café 1,50 l"], 7.5);
  assert.equal(COLD_DRINK_PRICES["Rosport Blue 1,00 l btl"], 3.1);
  assert.equal(REUSABLE_PACKAGING_PRICES["myCan"], 9.0);
  assert.equal(REUSABLE_PACKAGING_PRICES["Remboursement Consigne ECOBOX (1000 ml)"], -5.0);
});
