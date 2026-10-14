import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");

test("menu share link carries restaurant and day", () => {
  assert.match(app, /function menuShareUrl\(slug, date\)/);
  assert.match(app, /searchParams\.set\("r", slug\)/);
  assert.match(app, /searchParams\.set\("date", date\)/);
});

test("the shared menu is opened on load, after the dish link", () => {
  assert.ok(app.indexOf("await openSharedDish()") < app.indexOf("await openSharedMenu()"));
});

test("every language has the unavailable note", () => {
  assert.equal((i18n.match(/sharedMenuUnavailable:/g) || []).length, (i18n.match(/sharedDishUnavailable:/g) || []).length);
});

test("delivery orders can be shared and opened pinned", () => {
  assert.match(app, /function orderShareUrl\(order\)/);
  assert.match(app, /async function openSharedOrder\(\)/);
  assert.ok(app.indexOf("await openSharedMenu()") < app.indexOf("await openSharedOrder()"));
  assert.equal((i18n.match(/shareDeliveryTitle:/g) || []).length, 11);
  assert.equal((i18n.match(/sharedOrderUnavailable:/g) || []).length, 11);
});
