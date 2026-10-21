import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PULL_MAX_PX, PULL_TRIGGER_PX, isPullingDown, pullDistance, shouldRefresh } from "../static/pull-refresh.js";

test("the pull follows the finger with resistance and stops at the maximum", () => {
  assert.equal(pullDistance(-30), 0);
  assert.equal(pullDistance(0), 0);
  assert.equal(pullDistance(100), 50);
  assert.equal(pullDistance(1000), PULL_MAX_PX);
});

test("letting go refreshes only past the trigger distance", () => {
  assert.equal(shouldRefresh(PULL_TRIGGER_PX - 1), false);
  assert.equal(shouldRefresh(PULL_TRIGGER_PX), true);
  assert.equal(shouldRefresh(pullDistance(139)), false); // 69.5 px of travel is not enough
  assert.equal(shouldRefresh(pullDistance(142)), true);
});

test("only a downward pull from the very top counts; sideways swipes and scrolling do not", () => {
  assert.equal(isPullingDown({ atTop: true, dx: 2, dy: 30 }), true);
  assert.equal(isPullingDown({ atTop: false, dx: 0, dy: 60 }), false); // scrolled down a little: a normal scroll
  assert.equal(isPullingDown({ atTop: true, dx: 80, dy: 30 }), false); // the category row swiped sideways
  assert.equal(isPullingDown({ atTop: true, dx: 0, dy: -40 }), false); // scrolling down the page
  assert.equal(isPullingDown({ atTop: true, dx: 0, dy: 5 }), false); // a tap's wobble
});

test("the app refreshes the menu, status and photos, keeps the basket, and speaks every language", () => {
  const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
  assert.match(app, /menuCache\.delete\(menuCacheKey\(slug, date\)\)/);
  assert.match(app, /dishPhotosCache\.delete\(slug\)/);
  assert.match(app, /state\.selection = state\.selection\.filter\(\(s\) => ids\.has\(s\.menuItemId\)\)/);
  assert.match(app, /setupPullToRefresh\(\);/);
  assert.equal((i18n.match(/menuUpdated:/g) || []).length, 11);
  assert.equal((i18n.match(/menuUpdateFailed:/g) || []).length, 11);
});
