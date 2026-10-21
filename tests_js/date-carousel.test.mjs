import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");

test("one day carousel sits above all the restaurants of the chosen campus", () => {
  assert.match(app, /async function loadCampusDates\(restaurants\)/);
  assert.match(app, /const CAROUSEL_DAYS = 14/);
  assert.match(app, /Array\.from\(\{ length: DATE_PICKER_PAST_DAYS \+ CAROUSEL_DAYS \}, \(_, i\) => localDateString\(i - DATE_PICKER_PAST_DAYS\)\)/); // yesterday, then every calendar day, weekends and closed days too
  assert.match(app, /wrap\.append\(datesBox, grid\)/); // carousel first, full width, then the grid
  assert.match(app, /const dc = dateCard\(d, \(\) => chooseDay\(d\.date, scroller\)\)/);
});

test("each restaurant card says whether it is open on the chosen day", () => {
  assert.match(app, /function setCardDayStatus\(card, info\)/);
  assert.match(app, /setCardDayStatus\(cards\.get\(r\.slug\), info\)/);
});

test("the open/closed indicator is a coloured pill, translated, with the closing time", () => {
  for (const kind of ["open", "closed", "none", "unknown"]) assert.ok(app.includes(`kind = "${kind}"`));
  assert.match(app, /day-pill is-\$\{kind\}/);
  for (const key of ["dayOpenUntil", "dayOpen", "dayClosed", "dayNoMenu", "dayUnknown"]) assert.equal((i18n.match(new RegExp(`${key}:`, "g")) || []).length, 11);
});

test("tapping a restaurant opens its menu for the chosen day, and back returns to the list", () => {
  assert.match(app, /const info = await loadDayStatus\(r\.slug, state\.listDate\)/);
  assert.match(app, /selectDate\(info, "restaurants"\)/);
  assert.match(app, /back: \(\) => goTo\(state\.menuBack \|\| "dates"\)/);
  assert.match(app, /async function selectDate\(dateInfo, back = "dates"\)/);
  // days that never loaded fall back to the old day-by-day screen
  assert.match(app, /if \(!state\.listDate\) return selectRestaurant\(r\)/);
});

test("the picker and the carousel share one date card", () => {
  assert.equal((app.match(/function dateCard\(/g) || []).length, 1);
  assert.match(app, /scroller\.append\(dateCard\(d, \(\) => selectDate\(d\)\)\)/);
});

test("the new text exists in every language", () => {
  assert.equal((i18n.match(/noDaysToOrder:/g) || []).length, 11);
});
