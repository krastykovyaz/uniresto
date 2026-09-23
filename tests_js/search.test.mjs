import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeText, itemMatchesQuery, searchItems } from "../static/search.js";

const item = (overrides = {}) => ({
  id: 1,
  category: "Entrée",
  name: "Salad'bar",
  description: null,
  ...overrides,
});

test("normalizeText lowercases and strips accents", () => {
  assert.equal(normalizeText("Crème Brûlée"), "creme brulee");
  assert.equal(normalizeText("PÊCHE"), "peche");
});

test("normalizeText handles null/undefined safely", () => {
  assert.equal(normalizeText(null), "");
  assert.equal(normalizeText(undefined), "");
});

test("empty query matches everything", () => {
  assert.equal(itemMatchesQuery(item(), "", null), true);
  assert.equal(itemMatchesQuery(item(), "   ", null), true);
});

test("matches dish name, case and accent insensitive", () => {
  const dish = item({ name: "Rôti de porc Orloff" });
  assert.equal(itemMatchesQuery(dish, "roti", null), true);
  assert.equal(itemMatchesQuery(dish, "ROTI", null), true);
  assert.equal(itemMatchesQuery(dish, "rôti", null), true);
  assert.equal(itemMatchesQuery(dish, "pizza", null), false);
});

test("matches description", () => {
  const dish = item({ name: "Plat du jour", description: "Servi avec une sauce au poivre" });
  assert.equal(itemMatchesQuery(dish, "poivre", null), true);
  assert.equal(itemMatchesQuery(dish, "citron", null), false);
});

test("matches the raw category string", () => {
  const dish = item({ category: "Végétarien" });
  assert.equal(itemMatchesQuery(dish, "vegetarien", null), true);
});

test("matches the translated category label when provided", () => {
  const dish = item({ category: "Entrée" });
  // Searching the English word "starter" should find an "Entrée" item
  // via its translated label -- dish names stay untranslated, but
  // categories have a known, translated vocabulary (README Part 5).
  assert.equal(itemMatchesQuery(dish, "starter", "Starter"), true);
  assert.equal(itemMatchesQuery(dish, "starter", null), false);
});

test("searchItems filters and preserves order", () => {
  const items = [
    item({ id: 1, name: "Salad'bar" }),
    item({ id: 2, name: "Soupe de légumes" }),
    item({ id: 3, name: "Salade César" }),
  ];
  const result = searchItems(items, "sala");
  assert.deepEqual(result.map((i) => i.id), [1, 3]);
});

test("searchItems with empty query returns all items unchanged", () => {
  const items = [item({ id: 1 }), item({ id: 2 })];
  assert.deepEqual(searchItems(items, ""), items);
});

test("searchItems uses getTranslatedCategory when given", () => {
  const items = [item({ id: 1, category: "Entrée", name: "Salad'bar" })];
  const translate = (cat) => (cat === "Entrée" ? "Starter" : cat);
  assert.deepEqual(searchItems(items, "starter", translate).map((i) => i.id), [1]);
  assert.deepEqual(searchItems(items, "starter").map((i) => i.id), []);
});

test("matches the raw allergen name", () => {
  const dish = item({ allergens: [{ code: 7, name: "Lait" }] });
  assert.equal(itemMatchesQuery(dish, "lait", null), true);
  assert.equal(itemMatchesQuery(dish, "gluten", null), false);
});

test("matches the translated allergen label when provided", () => {
  const dish = item({ allergens: [{ code: 7, name: "Lait" }] });
  assert.equal(itemMatchesQuery(dish, "milk", null, ["Milk"]), true);
  assert.equal(itemMatchesQuery(dish, "milk", null, null), false);
});

test("searchItems uses getTranslatedAllergen when given, over ALL items' allergens", () => {
  const items = [
    item({ id: 1, name: "Rôti de porc", allergens: [{ code: 7, name: "Lait" }] }),
    item({ id: 2, name: "Salade César", allergens: [{ code: 1, name: "Gluten" }] }),
  ];
  const translate = (a) => (a.name === "Lait" ? "Milk" : a.name);
  assert.deepEqual(searchItems(items, "milk", null, translate).map((i) => i.id), [1]);
  // Also findable by the raw French allergen name, without any translator.
  assert.deepEqual(searchItems(items, "lait").map((i) => i.id), [1]);
});
