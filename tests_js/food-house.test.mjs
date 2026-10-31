import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");

test("the Belval tab is the vote only until a Belval restaurant exists", () => {
  assert.match(app, /if \(campus === "belval" && here\.length === 0\) return belvalComingContent\(\)/);
  assert.match(app, /const here = state\.restaurants\.filter\(\(r\) => campusOfRestaurant\(r\) === campus\)/);
});

test("the delivery list is split by the campus of each order's restaurant, own deliveries aside", () => {
  assert.match(app, /const inCampus = \(o\) => orderCampus\(o\) === state\.deliveryCampusFilter/);
  assert.match(app, /const \{ mine \} = data;/);
});

test("an order form offers only the buildings of the restaurant's campus", () => {
  assert.match(app, /BELVAL_BUILDING_CODES = new Set\(\[\n  "maison_du_savoir", "maison_sciences_humaines", "maison_innovation",\n  "maison_du_nombre", "maison_materiaux", "learning_centre", "biotech_1", "biotech_2", "maison_arts_etudiants", "incubator", "halles_essais", "uni_val_1", "uni_val_2",\n\]\)/);
  assert.match(app, /\$\{buildingsForCurrentRestaurant\(\)\.map/);
});
