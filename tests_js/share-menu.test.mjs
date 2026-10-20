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

test("a menu link without a day opens the next orderable day", () => {
  assert.match(app, /params\.get\("date"\) \|\| "next"/);
  assert.match(app, /available-dates\?count=1/);
});

test("visits from shared links are counted under their own source", () => {
  assert.match(app, /function trafficSource\(params\)/);
  for (const label of ["share-order", "share-dish", "share-menu"]) assert.ok(app.includes(`"${label}"`));
  assert.match(app, /const urlSource = trafficSource\(/);
});

test("the confirmation screen offers push once, in every language", () => {
  assert.match(app, /const pushPrompt = orderPushPrompt\(\)/);
  assert.equal((i18n.match(/orderPushTitle:/g) || []).length, 11);
  assert.equal((i18n.match(/orderPushBody:/g) || []).length, 11);
});

test("the dish photo list is refreshed after a few minutes, not kept for the whole visit", () => {
  assert.match(app, /DISH_PHOTOS_TTL_MS = 5 \* 60 \* 1000/);
  assert.match(app, /if \(dishPhotosFresh\(slug\)\) return dishPhotosCache\.get\(slug\)/);
});
