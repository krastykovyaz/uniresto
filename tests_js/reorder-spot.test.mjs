import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");

test("the building and room are remembered per campus and filled in on the next order", () => {
  assert.match(app, /const DELIVERY_SPOT_STORAGE_KEY = "uniresto\.deliverySpot\.v1"/);
  assert.match(app, /spots\[currentCampus\(\)\] = \{ building: state\.deliveryBuilding, text: state\.deliveryLocationText\.trim\(\) \}/);
  assert.match(app, /async function renderReview\(\) \{\s*applyRememberedSpot\(\);/);
  // saved when edited and when the order is placed
  assert.equal((app.match(/saveDeliverySpot\(\);/g) || []).length, 3);
});

test("a spot from the other campus is never offered", () => {
  assert.match(app, /buildingsForCurrentRestaurant\(\)\.some\(\(b\) => b\.label === spot\.building\)/);
});

test("the last order is remembered and offered on the home screen; older devices read it back once", () => {
  assert.match(app, /rememberLastOrder\(order\);/);
  assert.match(app, /function reorderAgainCard\(\)/);
  assert.match(app, /card\.addEventListener\("click", \(\) => reorderPastOrder\(last\)\)/);
  assert.match(app, /async function backfillLastOrder\(\)/);
});

test("newcomers see why to try it: Luni, delivery to the building, and which buildings", () => {
  assert.match(app, /function tryReasonCard\(\)/);
  assert.match(app, /else if \(loadOrderHistoryIds\(\)\.length === 0\) app\.append\(tryReasonCard\(\)\)/);
  for (const key of ["reorderAgainTitle", "reorderAgainCta", "tryReasonTitle", "tryReasonLuni", "tryReasonDelivery", "tryReasonBuildings"]) {
    assert.equal((i18n.match(new RegExp(`${key}:`, "g")) || []).length, 11, key);
  }
});
