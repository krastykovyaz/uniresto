import { test } from "node:test";
import assert from "node:assert/strict";
import { dishEmoji } from "../static/dish-emoji.js";

const e = (name, category = "") => dishEmoji({ name, category });

test("matches by keywords in the name, ignoring accents and case", () => {
  assert.equal(e("Velouté aux épinards"), "🍲");
  assert.equal(e("WRAP aux falafels"), "🌯");
  assert.equal(e("Croissant 50 g"), "🥐");
  assert.equal(e("Rumsteak grillé, sauce au poivre"), "🥩");
});

test("word fragments do not trigger the wrong emoji", () => {
  // "steak" contains "tea", "epeautre" contains "eau", "ciboulette" contains "boulette",
  // "laitue" starts with "lait", "the ultimate" contains the word "the".
  assert.equal(e("Rumsteak grillé"), "🥩");
  assert.equal(e("Penne à l'épeautre au beurre"), "🍝");
  assert.equal(e("Quinoa à la ciboulette"), "🍚");
  assert.equal(e("Laitue Mimosa"), "🥬");
  assert.equal(e("1/2 Levain The ultimate egg Sandwich"), "🥪");
  assert.equal(e("Thé \"commerce équitable\""), "🍵");
});

test("a sandwich filling does not turn the sandwich into the filling", () => {
  assert.equal(e("Petit pain blanc jambon cuit"), "🥪");
  assert.equal(e("Mini baguette sans gluten salami"), "🥪");
});

test("packaging is a bag, not the food it holds", () => {
  assert.equal(e("Sachet pour sandwiches"), "🥡");
  assert.equal(e("Barquette pour pâtes/salades à emporter"), "🥡");
  assert.equal(e("Consigne ECOBOX (500 ml)"), "🥡");
});

test("'non consigné' water is still water, not packaging", () => {
  assert.equal(e("Rosport mat Menthe 0,50 l non consigné"), "💧");
});

test("falls back to the category, then to a plate", () => {
  assert.equal(e("Plat inconnu", "Non-végétarien"), "🍖");
  assert.equal(e("Plat inconnu", "Végan"), "🌱");
  assert.equal(e("Plat inconnu", "Dessert"), "🍮");
  assert.equal(e("Plat inconnu", "Rien"), "🍽️");
});
