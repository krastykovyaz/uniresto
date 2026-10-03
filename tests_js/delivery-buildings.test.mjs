import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { translations } from "../static/i18n.js";

// The building list is plain data in static/app.js (which can't be imported without a DOM), so read it as text.
const js = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const block = js.match(/const DELIVERY_BUILDINGS = \[([\s\S]*?)\n\];/)[1];
const buildings = [...block.matchAll(/\{ code: "([^"]+)", key: "([^"]+)", suffixKey: (null|"[^"]+"), label: "([^"]+)" \}/g)].map((m) => ({
  code: m[1], key: m[2], suffixKey: m[3] === "null" ? null : m[3].slice(1, -1), label: m[4],
}));

test("the delivery form offers the campus buildings and the lycée annex", () => {
  assert.deepEqual(buildings.map((b) => b.code), [
    "building_a", "building_b", "building_c", "building_d", "building_g", "jfk_building", "weicker_building", "ltc_annex",
  ]);
  assert.equal(buildings.at(-1).label, "Lycée Technique du Centre (Kirchberg annex)");
});

test("codes and stored labels are unique, and no label is a prefix of another", () => {
  assert.equal(new Set(buildings.map((b) => b.code)).size, buildings.length);
  assert.equal(new Set(buildings.map((b) => b.label)).size, buildings.length);
  // splitDeliveryLocation() matches "<label> — <text>" by prefix, so a label that starts another would split wrongly
  for (const a of buildings) for (const b of buildings) if (a !== b) assert.ok(!b.label.startsWith(a.label + " — ") && !b.label.startsWith(a.label + " "), `${a.label} / ${b.label}`);
});

test("every building's name and suffix exist in every language", () => {
  for (const [lang, dict] of Object.entries(translations)) {
    for (const b of buildings) {
      assert.ok(dict[b.key], `${lang}: ${b.key}`);
      if (b.suffixKey) assert.ok(dict[b.suffixKey], `${lang}: ${b.suffixKey}`);
    }
  }
});
