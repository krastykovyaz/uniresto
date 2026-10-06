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
  priceForItem,
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

test("ice cream uses the 2025/26 prices", () => {
  const expected = {
    "Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille, Praliné, Mocca-vanille)": 1.9,
    "Dame Blanche Luxlait 200 ml": 2.25,
    "Glace miniature Luxlait 100 ml (Framboise, Praliné, Vanille)": 2.25,
  };
  for (const [name, price] of Object.entries(expected)) {
    assert.equal(priceForItem({ category: "07. Glaces", name }), price, name);
    assert.equal(computeFormulaTotal([line("07. Glaces", 1, name)]).total, price, name);
  }
});

test("ice cream price survives a changed flavour list, and only for ice cream", () => {
  for (const name of ["Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)", "Cornet Luxlait 130 ml (Pistache)", "Cornet Luxlait 130 ml"]) {
    assert.equal(priceForItem({ category: "07. Glaces", name }), 1.9, name);
  }
  assert.equal(priceForItem({ category: "07. Glaces", name: "Sorbet citron 100 ml (Citron)" }), null);
  assert.equal(priceForItem({ category: "11. Boissons chaudes", name: "Espresso (décaféiné)" }), null);
});

test("dairy is priced at the official adultes tariff", () => {
  const expected = {
    "Mini fromage frais avec coulis de fruits de saison 150 g": 3.5,
    "Mini muesli maison 150 g": 3.5,
    "Lait chocolaté Luxlait 0,25 l Tétra Pack": 1.1,
    "Lait Luxlait BIO 0,25 l Tétra Pack": 0.95,
    "Yaourt aux fruits Luxlait 125 g": 1.35,
    "Yaourt nature Luxlait 125 g": 1.15,
  };
  for (const [name, price] of Object.entries(expected)) {
    assert.equal(priceForItem({ category: "05. Laitages", name }), price, name);
    assert.equal(computeFormulaTotal([line("05. Laitages", 1, name)]).total, price, name);
  }
});

test("the free school milk costs the same as the regular one above the school programme", () => {
  const free = priceForItem({ category: "05. Laitages", name: "Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)" });
  const regular = priceForItem({ category: "05. Laitages", name: "Lait Luxlait BIO 0,25 l Tétra Pack" });
  assert.equal(free, 0.95);
  assert.equal(free, regular);
});

test("a seasonal name in quotes still matches the official dairy line", () => {
  const seasonal = 'Mini muesli maison "Douceur d\'automne" 150 g';
  assert.equal(priceForItem({ category: "05. Laitages", name: seasonal }), 3.5);
  assert.equal(computeFormulaTotal([line("05. Laitages", 2, seasonal)]).total, 7);
});

test("names that really contain quotes still match exactly", () => {
  assert.equal(priceForItem({ category: "06. Fruits", name: 'Banane "commerce équitable"' }), 1.4);
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

test("priceForItem shows the Formule 3 main-alone price for any main dish", () => {
  assert.equal(priceForItem({ category: "Non-végétarien", name: "Rôti de porc Orloff" }), MEAL_TIER_PRICES.main);
  assert.equal(priceForItem({ category: "Végétarien", name: "Anything" }), MEAL_TIER_PRICES.main);
  assert.equal(priceForItem({ category: "Végan", name: "Anything" }), MEAL_TIER_PRICES.main);
});

test("priceForItem still has no standalone price for a starter or dessert", () => {
  // Formule 2/1 only exist as an upgrade on top of a main -- neither
  // category is ever priced alone.
  assert.equal(priceForItem({ category: "Entrée", name: "Anything" }), null);
  assert.equal(priceForItem({ category: "Dessert", name: "Anything" }), null);
});

// ---------------------------------------------------------------------------
// applyPriceTables(): the server's active tier (real adult price, or the mean) replaces the tables
// ---------------------------------------------------------------------------
import * as PR from "../static/pricing.js";
const { ACTIVE_PRICE_TIER: _unused, applyPriceTables } = PR;

const TABLE_NAMES = ["SANDWICH_PRICES", "VIENNOISERIE_PRICES", "HOMEMADE_CAKE_PRICES", "TAKEAWAY_VITAMIN_PRICES", "FRUIT_PRICES", "LAITAGES_PRICES",
  "GLACES_PRICES", "PASTRY_PRICES", "COLD_DRINK_PRICES", "HOT_DRINK_PRICES", "REUSABLE_PACKAGING_PRICES", "SINGLE_USE_PACKAGING_PRICES"];

function adultPayload() {
  return {
    tier: "adulte",
    meal_tier_prices: { ...PR.MEAL_TIER_PRICES },
    snack_price: PR.SNACK_PRICE,
    name_prices: Object.fromEntries(TABLE_NAMES.map((n) => [n, { ...PR[n] }])),
  };
}

test("applyPriceTables: the mean replaces every price, and applying the adult payload again restores the real ones", () => {
  const real = adultPayload();
  const main = [{ category: "Végétarien", name: "x", quantity: 1 }];
  const mealStarterDessert = [...main, { category: "Entrée", name: "s", quantity: 1 }, { category: "Dessert", name: "d", quantity: 1 }];
  const sandwichName = Object.keys(real.name_prices.SANDWICH_PRICES)[0];
  const sandwich = [{ category: "01.3 Sandwiches non-végétariens", name: sandwichName, quantity: 1 }];
  assert.equal(computeFormulaTotal(main).total, 6.7);

  const mean = adultPayload();
  mean.tier = "mean";
  mean.meal_tier_prices = { main: 5.2, main_starter: 5.95, main_starter_dessert: 6.7 };
  mean.snack_price = 4.15;
  mean.name_prices.SANDWICH_PRICES = Object.fromEntries(Object.entries(real.name_prices.SANDWICH_PRICES).map(([k, v]) => [k, v - 1]));
  try {
    assert.equal(applyPriceTables(mean), true);
    assert.equal(PR.ACTIVE_PRICE_TIER, "mean");
    assert.equal(computeFormulaTotal(main).total, 5.2);
    assert.equal(computeFormulaTotal(mealStarterDessert).total, 6.7);
    assert.equal(priceForItem({ category: "Snack à emporter", name: "x" }), 4.15);
    assert.equal(priceForItem({ category: "Végétarien", name: "x" }), 5.2);
    assert.equal(computeFormulaTotal(sandwich).total, Math.round((real.name_prices.SANDWICH_PRICES[sandwichName] - 1) * 100) / 100);
  } finally {
    assert.equal(applyPriceTables(real), true); // back to the real adult price
  }
  assert.equal(PR.ACTIVE_PRICE_TIER, "adulte");
  assert.equal(computeFormulaTotal(main).total, 6.7);
  assert.equal(computeFormulaTotal(sandwich).total, real.name_prices.SANDWICH_PRICES[sandwichName]);
});

test("applyPriceTables: a payload that is not exactly what the server sends changes nothing", () => {
  const before = JSON.stringify(adultPayload());
  const bad = [null, "x", {}, { ...adultPayload(), meal_tier_prices: { main: 1 } }, { ...adultPayload(), snack_price: "4" },
    { ...adultPayload(), name_prices: { SANDWICH_PRICES: { a: 1 } } }, { ...adultPayload(), meal_tier_prices: { main: 5, main_starter: "x", main_starter_dessert: 7 } }];
  for (const payload of bad) assert.equal(applyPriceTables(payload), false);
  assert.equal(JSON.stringify(adultPayload()), before);
});

test("the app reads the prices built into the page first, and only then asks the server", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  const start = app.indexOf("async function loadPriceTables()");
  const fn = app.slice(start, app.indexOf("async function init()", start));
  assert.ok(fn.indexOf('getElementById("price-tables")') > 0 && fn.indexOf('getElementById("price-tables")') < fn.indexOf('fetch("/api/pricing"'));
  assert.match(fn, /setTimeout\(\(\) => controller\.abort\(\), 8000\)/);
  assert.match(app, /await Promise\.all\(\[loadRestaurants\(\), loadPriceTables\(\)\]\)/);
});

test("app.js imports every pricing.js function it calls (a missing import is swallowed by the fallback)", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  const imported = app.match(/import \{([^}]*)\} from "\.\/pricing\.js";/)[1];
  for (const name of ["applyPriceTables", "computeFormulaTotal", "priceForItem"]) {
    assert.match(imported, new RegExp(`\\b${name}\\b`), `${name} is used in app.js but not imported from pricing.js`);
  }
});

test("discountOffer: nothing while the real adult price is charged; the live numbers while the mean is", () => {
  const real = adultPayload();
  assert.equal(PR.discountOffer(), null);
  const mean = { ...adultPayload(), tier: "mean", meal_tier_prices: { main: 5.2, main_starter: 5.95, main_starter_dessert: 6.7 }, snack_price: 4.15, list_prices: { main: 6.7, main_starter: 7.7, main_starter_dessert: 8.7, snack: 4.8 } };
  try {
    assert.equal(PR.applyPriceTables(mean), true);
    assert.deepEqual(PR.discountOffer(), { main: { price: 5.2, was: 6.7 }, full: { price: 6.7, was: 8.7 } });
    // a "mean" that is not actually cheaper is never advertised as a discount
    assert.equal(PR.applyPriceTables({ ...mean, meal_tier_prices: { main: 6.7, main_starter: 7.7, main_starter_dessert: 8.7 } }), true);
    assert.equal(PR.discountOffer(), null);
  } finally {
    assert.equal(PR.applyPriceTables(real), true);
  }
  assert.equal(PR.discountOffer(), null);
});

test("the first screen shows the discount banner above the role cards, and closing it is remembered per price", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  const role = app.slice(app.indexOf("function renderRole() {"), app.indexOf("const grid = el(", app.indexOf("function renderRole() {")));
  assert.match(role, /const discount = discountBanner\(\);\n\s+if \(discount\) app\.append\(discount\);/);
  assert.match(app, /const offer = discountOffer\(\);\n\s+if \(!offer\) return null;/);
  assert.match(app, /localStorage\.setItem\(DISCOUNT_BANNER_DISMISSED_KEY, signature\)/);
  assert.match(app, /signature = `\$\{offer\.main\.price\}\/\$\{offer\.main\.was\}\/\$\{offer\.full\.price\}\/\$\{offer\.full\.was\}`/);
  assert.match(app.match(/import \{([^}]*)\} from "\.\/pricing\.js";/)[1], /\bdiscountOffer\b/);
});

for (const key of ["discountBannerTitle", "discountBannerBody", "discountBannerClose"]) {
  test(`${key} exists in all 11 languages, and the body keeps its four placeholders`, async () => {
    const { readFileSync } = await import("node:fs");
    const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
    const lines = i18n.match(new RegExp(`^\\s+${key}: ".*",$`, "gm")) || [];
    assert.equal(lines.length, 11);
    if (key === "discountBannerBody") for (const l of lines) for (const ph of ["{price}", "{was}", "{fullPrice}", "{fullWas}"]) assert.ok(l.includes(ph), `${ph} missing in ${l}`);
  });
}
