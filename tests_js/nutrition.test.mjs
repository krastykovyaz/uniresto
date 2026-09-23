import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyFoodType, estimateCalories } from "../static/nutrition.js";

test("no weight gives no estimate", () => {
  const r = estimateCalories("Poulet rôti", null, null);
  assert.deepEqual(r, { calories: null, foodType: null, isEstimated: false });
});

test("piece unit gives no estimate", () => {
  const r = estimateCalories("Croissant", 1, "piece");
  assert.equal(r.calories, null);
  assert.equal(r.isEstimated, false);
});

test("unmatched name gives no estimate", () => {
  const r = estimateCalories("Plat mystère du jour", 200, "g");
  assert.deepEqual(r, { calories: null, foodType: null, isEstimated: false });
});

test("known weight and matched keyword gives an estimate", () => {
  const r = estimateCalories("Rôti de porc Orloff", 200, "g");
  assert.equal(r.calories, 440.0);
  assert.equal(r.foodType, "red_meat");
  assert.equal(r.isEstimated, true);
});

test("liters are converted to grams equivalent", () => {
  const r = estimateCalories("Coca-Cola", 0.5, "l");
  assert.equal(r.calories, 210.0);
  assert.equal(r.foodType, "soda");
});

test("water is zero calories but still an estimate", () => {
  const r = estimateCalories("Eau plate", 500, "ml");
  assert.equal(r.calories, 0.0);
  assert.equal(r.isEstimated, true);
});

// -- Regression tests mirroring tests/test_nutrition.py --

test("luxlait brand name does not falsely match milk", () => {
  const [foodType] = classifyFoodType("Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)");
  assert.equal(foodType, "ice_cream");
});

test("standalone lait still matches milk", () => {
  const [foodType] = classifyFoodType("Lait demi-écrémé Luxlait 25 cl");
  assert.equal(foodType, "milk");
});

test("menthe does not falsely match tea", () => {
  const result = classifyFoodType("Rosport mat Menthe 0,50 l non consigné");
  assert.ok(result === null || result[0] !== "hot_beverage_tea");
});

test("fromage frais is not classified as dense hard cheese", () => {
  const [foodType, kcal] = classifyFoodType("Mini fromage frais avec coulis de fruits de saison");
  assert.equal(foodType, "fresh_cheese");
  assert.equal(kcal, 90);
});

test("poche aux pommes is pastry not raw fruit", () => {
  const [foodType, kcal] = classifyFoodType("Poche aux pommes");
  assert.equal(foodType, "pastry_sweet");
  assert.equal(kcal, 260);
});

test("longest matching keyword wins over shorter ones", () => {
  const [foodType] = classifyFoodType("Yaourt aux fruits Luxlait 125 g");
  assert.equal(foodType, "dairy");
});

test("iced tea is not classified as the flavor fruit", () => {
  const [foodType] = classifyFoodType("Fuze Tea - Black Tea Pêche/Hibiscus 0,20 l btl");
  assert.equal(foodType, "iced_tea");
});
