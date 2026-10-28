import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");

const KEYS = [
  "earnLuniTitle", "earnLuniBalance", "earnLuniVerify", "earnLuniOrder", "earnLuniDelivery", "earnLuniPhoto", "earnLuniShare",
  "earnLuniShareNote", "earnLuniPhotoHint", "earnLuniSharePickTitle", "shareEarnNote", "shareEarnVerify", "rewardRuleShare",
];

test("every Earn Luni text exists in all 11 languages", () => {
  for (const key of KEYS) assert.equal((i18n.match(new RegExp(`\\b${key}:`, "g")) || []).length, 11, key);
});

test("Home shows the Earn Luni block with the four ways to earn and their amounts", () => {
  const home = app.slice(app.indexOf("function renderRole()"), app.indexOf("// Groups orders under their canteen name"));
  assert.match(home, /app\.append\(earnLuniCard\(\)\)/);
  const rows = app.slice(app.indexOf("const EARN_LUNI_ROWS"), app.indexOf("// A small sheet to pick which restaurant"));
  for (const key of ["order", "delivery", "photo", "share"]) assert.match(rows, new RegExp(`key: "${key}"`));
  assert.match(rows, /key: "share"[^}]*badge: "\+0\.1"/);
  assert.equal((rows.match(/badge: "\+1"/g) || []).length, 3);
});

test("a shared menu link carries the sharer's code, never their email", () => {
  assert.match(app, /function menuShareUrl\(slug, date, ref = null\)/);
  assert.match(app, /if \(ref\) url\.searchParams\.set\("ref", ref\)/);
  const fn = app.slice(app.indexOf("async function shareRefCode()"), app.indexOf("function reportSharedLinkOpen()"));
  assert.match(fn, /\/api\/share\/ref/);
  assert.doesNotMatch(app.slice(app.indexOf("function menuShareUrl"), app.indexOf("const VISITOR_ID_KEY")), /registeredEmail/);
});

test("opening a shared menu link tells the server once, only for menu links with a code, and never in the demo", () => {
  const fn = app.slice(app.indexOf("function reportSharedLinkOpen()"), app.indexOf("// One open delivery:"));
  assert.match(fn, /if \(DEMO\) return/);
  assert.match(fn, /if \(!ref \|\| !url\.searchParams\.get\("r"\)\) return/);
  assert.match(fn, /\/api\/share\/open/);
  assert.match(app, /reportSharedLinkOpen\(\);\s*if \(await openSharedDish\(\)\) return;/);
});

test("the menu's share button and the Home picker both use the sharer's code and explain the reward", () => {
  assert.match(app, /menuShareUrl\(state\.slug, state\.targetDate, ref\)/);
  assert.match(app, /menuShareUrl\(restaurant\.slug, "next", ref\)/);
  assert.match(app, /"shareEarnNote"/);
  assert.match(app, /"shareEarnVerify"/);
});

test("the how-to-earn sheet lists the shared-link reward", () => {
  assert.match(app, /rewardRuleShare"\)\)\}<\/span><strong>\+0\.1<\/strong>/);
});

test("the Earn Luni block is folded to its title until tapped, and remembers the choice on the device", () => {
  const fn = app.slice(app.indexOf("function earnLuniCard()"), app.indexOf("function renderRole()"));
  assert.match(fn, /class="earn-head" aria-expanded="false"/);
  assert.match(fn, /<div class="earn-body" hidden>/);
  assert.match(fn, /localStorage\.getItem\(EARN_LUNI_OPEN_KEY\) === "1"/);
  assert.match(fn, /localStorage\.setItem\(EARN_LUNI_OPEN_KEY, open \? "1" : "0"\)/);
  assert.match(app, /const EARN_LUNI_OPEN_KEY = "uniresto\.earnLuniOpen\.v1"/);
});
