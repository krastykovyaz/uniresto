import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const scan = app.slice(app.indexOf("async function scan(file)"), app.indexOf("function showResults("));
const add = app.slice(app.indexOf("async function addToBasket(found)"), app.indexOf('input.addEventListener("change"'));

test("a scan reads the menu fresh, not a copy cached earlier in the session", () => {
  assert.ok(scan.indexOf("menuCache.delete(menuCacheKey(slug, date))") > -1);
  assert.ok(scan.indexOf("menuCache.delete") < scan.indexOf("getMenu(slug, date)"));
});

test("scanned dishes go into the basket by (category, name), never by id", () => {
  assert.match(add, /byKey\.get\(cartItemKey\(item\)\)/);
  assert.doesNotMatch(add, /menuIds\.has\(item\.id\)/);
});

test("a basket for another menu is never replaced without asking, and one for the same menu is kept", () => {
  assert.match(add, /kept\.length > 0 && !sameDay && !window\.confirm\(tr\("trayScanReplaceBasket"\)\)\) return false/);
  assert.match(add, /if \(sameDay\) \{/);
});

test("the results stay open when nothing was added, and two add buttons never run at once", () => {
  assert.match(app, /const added = await addToBasket\(found\);/);
  assert.match(app, /if \(adding\) return;/);
});

test("the last order is looked up once per order id, and the screen redraws only when the card can show", () => {
  const fn = app.slice(app.indexOf("async function backfillLastOrder()"), app.indexOf("// For someone who has not ordered yet"));
  assert.match(fn, /readJson\(LAST_ORDER_BACKFILLED_KEY\) === newest\) return/);
  assert.match(fn, /state\.screen === "restaurants" && reorderAgainCard\(\)\) render\(\)/);
});
