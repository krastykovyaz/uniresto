import { test } from "node:test";
import assert from "node:assert/strict";
import {
  defaultFilters,
  availableCategories,
  availableAllergens,
  itemMatchesFilters,
  filterItems,
  activeFilterCount,
} from "../static/filters.js";

const item = (overrides = {}) => ({
  id: 1,
  category: "Non-végétarien",
  name: "Test dish",
  vegetarian: false,
  vegan: false,
  allergens: [],
  weight_value: null,
  weight_unit: null,
  calories: null,
  ...overrides,
});

test("default filters match everything", () => {
  const filters = defaultFilters();
  assert.equal(itemMatchesFilters(item(), filters), true);
  assert.equal(itemMatchesFilters(item({ category: "Dessert", vegan: true }), filters), true);
});

test("category filter is OR-matched across selected categories", () => {
  const filters = { ...defaultFilters(), categories: ["Entrée", "Dessert"] };
  assert.equal(itemMatchesFilters(item({ category: "Entrée" }), filters), true);
  assert.equal(itemMatchesFilters(item({ category: "Dessert" }), filters), true);
  assert.equal(itemMatchesFilters(item({ category: "Végétarien" }), filters), false);
});

test("dietary vegan filter only matches vegan items", () => {
  const filters = { ...defaultFilters(), dietary: ["vegan"] };
  assert.equal(itemMatchesFilters(item({ vegan: true }), filters), true);
  assert.equal(itemMatchesFilters(item({ vegetarian: true, vegan: false }), filters), false);
});

test("dietary vegetarian filter also matches vegan items (vegan implies vegetarian-safe)", () => {
  const filters = { ...defaultFilters(), dietary: ["vegetarian"] };
  assert.equal(itemMatchesFilters(item({ vegetarian: true }), filters), true);
  assert.equal(itemMatchesFilters(item({ vegan: true }), filters), true);
  assert.equal(itemMatchesFilters(item(), filters), false);
});

test("excluded allergens hide any item containing at least one selected code", () => {
  const filters = { ...defaultFilters(), excludedAllergens: [7] }; // Lait/Milk
  assert.equal(itemMatchesFilters(item({ allergens: [{ code: 7, name: "Lait" }] }), filters), false);
  assert.equal(itemMatchesFilters(item({ allergens: [{ code: 1, name: "Céréales" }] }), filters), true);
  assert.equal(itemMatchesFilters(item({ allergens: [] }), filters), true);
});

test("weight bucket only matches gram-unit items with a known weight", () => {
  const filters = { ...defaultFilters(), weightBucket: "under100" };
  assert.equal(itemMatchesFilters(item({ weight_value: 50, weight_unit: "g" }), filters), true);
  assert.equal(itemMatchesFilters(item({ weight_value: 150, weight_unit: "g" }), filters), false);
  // Not comparable in grams -- excluded, never guessed into a bucket.
  assert.equal(itemMatchesFilters(item({ weight_value: 50, weight_unit: "ml" }), filters), false);
  assert.equal(itemMatchesFilters(item({ weight_value: null, weight_unit: null }), filters), false);
});

test("weight buckets cover their boundaries correctly", () => {
  const under = { ...defaultFilters(), weightBucket: "under100" };
  const mid = { ...defaultFilters(), weightBucket: "100to250" };
  const over = { ...defaultFilters(), weightBucket: "over250" };
  const at100 = item({ weight_value: 100, weight_unit: "g" });
  const at250 = item({ weight_value: 250, weight_unit: "g" });
  assert.equal(itemMatchesFilters(at100, under), false);
  assert.equal(itemMatchesFilters(at100, mid), true);
  assert.equal(itemMatchesFilters(at250, mid), true);
  assert.equal(itemMatchesFilters(at250, over), false);
});

test("calories bucket only matches items with a known estimate", () => {
  const filters = { ...defaultFilters(), caloriesBucket: "over400" };
  assert.equal(itemMatchesFilters(item({ calories: 500 }), filters), true);
  assert.equal(itemMatchesFilters(item({ calories: 300 }), filters), false);
  assert.equal(itemMatchesFilters(item({ calories: null }), filters), false);
});

test("filterItems returns only matching items, preserving order", () => {
  const items = [item({ id: 1, category: "Entrée" }), item({ id: 2, category: "Dessert" }), item({ id: 3, category: "Entrée" })];
  const result = filterItems(items, { ...defaultFilters(), categories: ["Entrée"] });
  assert.deepEqual(result.map((i) => i.id), [1, 3]);
});

test("availableCategories preserves first-seen order and dedupes", () => {
  const items = [item({ category: "Entrée" }), item({ category: "Dessert" }), item({ category: "Entrée" })];
  assert.deepEqual(availableCategories(items), ["Entrée", "Dessert"]);
});

test("availableAllergens dedupes by code and sorts by code", () => {
  const items = [
    item({ allergens: [{ code: 7, name: "Lait" }] }),
    item({ allergens: [{ code: 1, name: "Céréales" }, { code: 7, name: "Lait" }] }),
  ];
  assert.deepEqual(availableAllergens(items), [
    { code: 1, name: "Céréales" },
    { code: 7, name: "Lait" },
  ]);
});

test("activeFilterCount counts every active dimension", () => {
  assert.equal(activeFilterCount(defaultFilters()), 0);
  assert.equal(
    activeFilterCount({
      categories: ["Entrée"],
      dietary: ["vegan"],
      excludedAllergens: [1, 7],
      weightBucket: "under100",
      caloriesBucket: "any",
    }),
    5
  );
});
