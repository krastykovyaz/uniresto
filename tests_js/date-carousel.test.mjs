import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");

test("a restaurant on the list opens its next orderable days right under it", () => {
  assert.match(app, /available-dates\?count=\$\{ORDERABLE_DATES_SHOWN\}/);
  assert.match(app, /function fillDateSlot\(slot, restaurant\)/);
  assert.match(app, /card\.addEventListener\("click", toggle\)/);
});

test("tapping a day goes straight to the menu, and back returns to the list", () => {
  assert.match(app, /selectDate\(d, "restaurants"\)/);
  assert.match(app, /back: \(\) => goTo\(state\.menuBack \|\| "dates"\)/);
  assert.match(app, /async function selectDate\(dateInfo, back = "dates"\)/);
});

test("the full date screen stays reachable, and the picker and the carousel share one card", () => {
  assert.match(app, /all\.addEventListener\("click", \(\) => selectRestaurant\(restaurant\)\)/);
  assert.equal((app.match(/function dateCard\(/g) || []).length, 1);
  assert.match(app, /scroller\.append\(dateCard\(d, \(\) => selectDate\(d\)\)\)/);
});

test("the new texts exist in every language", () => {
  for (const key of ["seeAllDays", "noDaysToOrder"]) assert.equal((i18n.match(new RegExp(`${key}:`, "g")) || []).length, 11);
});
