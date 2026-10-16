import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { TIPS, loadSeenTips, markTipSeen, placeTip } from "../static/tips.js";

const memory = () => {
  const data = {};
  return { getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; } };
};

test("a tip is remembered once seen, and a broken store never throws", () => {
  const s = memory();
  assert.equal(loadSeenTips(s).has("menu-share"), false);
  markTipSeen(s, "menu-share");
  assert.equal(loadSeenTips(s).has("menu-share"), true);
  assert.equal(loadSeenTips({ getItem: () => "not json", setItem: () => {} }).size, 0);
  assert.doesNotThrow(() => markTipSeen({ getItem: () => { throw new Error("x"); }, setItem: () => { throw new Error("x"); } }, "a"));
});

test("the bubble sits under the control, inside the screen, arrow on the control", () => {
  const spot = placeTip({
    anchor: { left: 340, top: 20, bottom: 60, width: 44 },
    container: { left: 0, top: 0, width: 430, height: 900 },
    tip: { width: 260, height: 50 },
  });
  assert.equal(spot.above, false);
  assert.equal(spot.top, 70);
  assert.ok(spot.left + 260 <= 430 - 12);
  assert.ok(Math.abs(spot.left + spot.arrowLeft - 362) <= 1);
});

test("with no room below, the bubble goes above", () => {
  const spot = placeTip({
    anchor: { left: 10, top: 860, bottom: 890, width: 40 },
    container: { left: 0, top: 0, width: 430, height: 900 },
    tip: { width: 200, height: 50 },
  });
  assert.equal(spot.above, true);
  assert.ok(spot.top < 860);
});

test("every tip has its text in every language", () => {
  const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
  for (const tip of Object.values(TIPS)) assert.equal((i18n.match(new RegExp(`${tip.textKey}:`, "g")) || []).length, 11);
});
