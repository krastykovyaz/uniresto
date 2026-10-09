import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../static/app.css", import.meta.url), "utf8");
const vote = app.slice(app.indexOf("function belvalComingContent() {"), app.indexOf("// The restaurant-grid content for whichever campus"));

test("the vote screen loads the live results and repaints after your own vote", () => {
  assert.match(vote, /api\("\/api\/coming-soon\/results"\)/);
  assert.match(vote, /\.finally\(loadResults\)/); // your vote shows up in the percentages
  assert.match(vote, /paint\(\);\n\s+loadResults\(\);/);
});

test("each card shows its share as a percentage and a bar", () => {
  assert.match(vote, /class="belval-share" hidden><span class="belval-bar"><i><\/i><\/span><span class="belval-percent"><\/span>/);
  assert.match(vote, /textContent = `\$\{percent\}%`/);
  assert.match(vote, /style\.width = `\$\{percent\}%`/);
});

test("the banner announces when voting ends and when the winner opens, and the closed state locks the cards", () => {
  assert.match(vote, /tr\("belvalVotingEnds", \{ date: fmtDayMonth\(results\.voting_ends\), opens \}\)/);
  assert.match(vote, /results\.winner\n\s+\? tr\("belvalVotingClosed", \{ name: results\.winner, opens \}\)\n\s+: tr\("belvalVotingClosedTie", \{ opens \}\)/);
  assert.match(vote, /card\.disabled = Boolean\(picked\) \|\| closed;/);
  // the date is formatted in the visitor's language (the same helper the menu's day names use)
  assert.match(app, /function fmtDayMonth\(iso\) \{[\s\S]*?Intl\.DateTimeFormat\(currentLocale\(\), \{ day: "numeric", month: "long" \}\)\.format\(parseISODate\(iso\)\)/);
});

for (const key of ["belvalVotingEnds", "belvalVotingClosed", "belvalVotingClosedTie", "belvalTotalVotes"]) {
  test(`${key} exists in all 11 languages`, () => {
    const lines = i18n.match(new RegExp(`^\\s+${key}: ".+",$`, "gm")) || [];
    assert.equal(lines.length, 11);
    const needs = { belvalVotingEnds: ["{date}", "{opens}"], belvalVotingClosed: ["{name}", "{opens}"], belvalVotingClosedTie: ["{opens}"], belvalTotalVotes: ["{n}"] }[key];
    for (const l of lines) for (const ph of needs) assert.ok(l.includes(ph), `${ph} missing in ${l}`);
  });
}

test("the share bar styles exist", () => {
  for (const sel of [".belval-share", ".belval-bar", ".belval-bar i", ".belval-percent", ".belval-banner-dates"]) assert.ok(css.includes(sel), sel);
});
