import { test } from "node:test";
import assert from "node:assert/strict";
import {
  clampQuantity,
  computeOrderTotals,
  formatPriceSummary,
  formatWeightSummary,
  formatWeightValue,
  lineTotal,
  lineWeight,
} from "../static/order-math.js";

// ---------------------------------------------------------------------------
// clampQuantity
// ---------------------------------------------------------------------------

test("clampQuantity defaults to 1 for invalid input", () => {
  assert.equal(clampQuantity(NaN), 1);
  assert.equal(clampQuantity(undefined), 1);
  assert.equal(clampQuantity("not a number"), 1);
});

test("clampQuantity never goes below 1 (no negative quantities)", () => {
  assert.equal(clampQuantity(0), 1);
  assert.equal(clampQuantity(-5), 1);
});

test("clampQuantity caps at maxQuantity (default 10)", () => {
  assert.equal(clampQuantity(11), 10);
  assert.equal(clampQuantity(999), 10);
  assert.equal(clampQuantity(7, 5), 5);
});

test("clampQuantity truncates fractional input", () => {
  assert.equal(clampQuantity(2.9), 2);
});

// ---------------------------------------------------------------------------
// lineWeight / lineTotal
// ---------------------------------------------------------------------------

test("lineWeight multiplies weight by quantity (250g x 2 = 500g)", () => {
  assert.equal(lineWeight(250, 2), 500);
});

test("lineWeight is null when weight is unknown, never silently 0", () => {
  assert.equal(lineWeight(null, 3), null);
});

test("lineTotal multiplies price by quantity", () => {
  assert.equal(lineTotal(8.5, 2), 17);
});

test("lineTotal is null when price is unknown", () => {
  assert.equal(lineTotal(null, 2), null);
});

// ---------------------------------------------------------------------------
// computeOrderTotals
// ---------------------------------------------------------------------------

const MENU = {
  1: { name: "Rôti de porc Orloff", category: "Non-végétarien", price: null, weight_value: 250, weight_unit: "g" },
  2: { name: "Pommes de terre", category: "Féculents", price: null, weight_value: 150, weight_unit: "g" },
  3: { name: "Coca Cola 0,20 l", category: "Snack à emporter", price: null, weight_value: 0.2, weight_unit: "l" },
  4: { name: "Entrée sans poids", category: "Entrée", price: null, weight_value: null, weight_unit: null },
  5: { name: "Dish with price", category: "Dessert", price: 2.5, weight_value: 120, weight_unit: "g" },
};

test("total weight sums quantities correctly (250g x1 + 150g x1 = 400g)", () => {
  const totals = computeOrderTotals(
    [
      { menuItemId: 1, quantity: 1 },
      { menuItemId: 2, quantity: 1 },
    ],
    MENU
  );
  assert.equal(totals.weightByUnit.g, 400);
  assert.equal(totals.itemCount, 2);
  assert.equal(totals.totalQuantity, 2);
});

test("total weight respects quantity multiplier, not just item count", () => {
  // 250 g x 2 = 500 g, per the task's explicit example.
  const totals = computeOrderTotals([{ menuItemId: 1, quantity: 2 }], MENU);
  assert.equal(totals.weightByUnit.g, 500);
  assert.equal(totals.totalQuantity, 2);
  assert.equal(totals.itemCount, 1); // one distinct dish, two portions
});

test("mixed units are never summed into one number", () => {
  const totals = computeOrderTotals(
    [
      { menuItemId: 1, quantity: 1 }, // 250 g
      { menuItemId: 3, quantity: 1 }, // 0.2 l
    ],
    MENU
  );
  assert.equal(totals.weightByUnit.g, 250);
  assert.equal(totals.weightByUnit.l, 0.2);
  assert.equal(Object.keys(totals.weightByUnit).length, 2);
});

test("unknown weight is tracked separately, never treated as zero", () => {
  const totals = computeOrderTotals(
    [
      { menuItemId: 1, quantity: 1 }, // known: 250 g
      { menuItemId: 4, quantity: 1 }, // unknown
    ],
    MENU
  );
  assert.equal(totals.weightByUnit.g, 250);
  assert.equal(totals.unknownWeightPortions, 1);
  assert.equal(totals.weightFullyKnown, false);
});

test("unknown weight portions respect quantity too", () => {
  const totals = computeOrderTotals([{ menuItemId: 4, quantity: 3 }], MENU);
  assert.equal(totals.unknownWeightPortions, 3);
  assert.deepEqual(totals.weightByUnit, {});
});

test("price totals: mostly-null real data reports unpriced portions honestly", () => {
  const totals = computeOrderTotals(
    [
      { menuItemId: 1, quantity: 1 }, // price null
      { menuItemId: 5, quantity: 2 }, // price 2.50 x 2 = 5.00
    ],
    MENU
  );
  assert.equal(totals.totalPriceKnown, 5.0);
  assert.equal(totals.unknownPricePortions, 1);
  assert.equal(totals.priceFullyKnown, false);
});

test("stale selection referencing a removed menu item is excluded, not crashing", () => {
  const totals = computeOrderTotals([{ menuItemId: 999, quantity: 1 }], MENU);
  assert.equal(totals.itemCount, 0);
});

test("quantity is clamped within computeOrderTotals too (defense in depth)", () => {
  const totals = computeOrderTotals([{ menuItemId: 1, quantity: 50 }], MENU);
  assert.equal(totals.totalQuantity, 10);
});

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

test("formatWeightValue for known weight", () => {
  assert.equal(formatWeightValue(250, "g"), "250 g");
  assert.equal(formatWeightValue(0.2, "l"), "0.2 l");
  assert.equal(formatWeightValue(1, "piece"), "1 pc");
});

test("formatWeightValue for unknown weight uses the exact required copy", () => {
  assert.equal(formatWeightValue(null, null), "Portion size not specified");
});

test("formatWeightSummary combines known totals across units plus unknown count", () => {
  const totals = computeOrderTotals(
    [
      { menuItemId: 1, quantity: 1 }, // 250 g
      { menuItemId: 3, quantity: 1 }, // 0.2 l
      { menuItemId: 4, quantity: 1 }, // unknown
    ],
    MENU
  );
  const summary = formatWeightSummary(totals);
  assert.match(summary, /250 g/);
  assert.match(summary, /0\.2 l/);
  assert.match(summary, /1 unknown/);
});

test("formatPriceSummary reports unpriced portions rather than a fake €0.00", () => {
  const totals = computeOrderTotals([{ menuItemId: 1, quantity: 1 }], MENU); // price is null
  assert.equal(formatPriceSummary(totals), "1 unpriced");
});

test("formatPriceSummary with no selection", () => {
  const totals = computeOrderTotals([], MENU);
  assert.equal(formatPriceSummary(totals), "No items selected");
});

test("formatWeightSummary with no selection", () => {
  const totals = computeOrderTotals([], MENU);
  assert.equal(formatWeightSummary(totals), "No items selected");
});
