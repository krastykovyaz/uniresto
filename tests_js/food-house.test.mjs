import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { translations, LANGUAGES } from "../static/i18n.js";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");

test("the Belval tab is the vote only until a Belval restaurant exists", () => {
  assert.match(app, /if \(campus === "belval" && here\.length === 0\) return belvalComingContent\(\)/);
  assert.match(app, /const here = state\.restaurants\.filter\(\(r\) => campusOfRestaurant\(r\) === campus\)/);
});

test("the delivery list is split by the campus of each order's restaurant, own deliveries included", () => {
  assert.match(app, /const inCampus = \(o\) => orderCampus\(o\) === state\.deliveryCampusFilter/);
  assert.match(app, /const mine = data\.mine\.filter\(inCampus\);/);
});

test("an order form offers only the buildings of the restaurant's campus", () => {
  assert.match(app, /BELVAL_BUILDING_CODES = new Set\(\[\n  "maison_du_savoir", "maison_sciences_humaines", "maison_innovation",\n  "maison_du_nombre", "maison_materiaux", "learning_centre", "biotech_1", "biotech_2", "maison_arts_etudiants", "incubator", "halles_essais", "uni_val_1", "uni_val_2",\n\]\)/);
  assert.match(app, /\$\{buildingsForCurrentRestaurant\(\)\.map/);
});

test("an unreadable day before the restaurant's next menu shows Closed, not Can't check", () => {
  assert.match(app, /info\.status === "unknown" && \(await nextMenuDate\(r\.slug, date\)\)/);
  assert.match(app, /closedBeforeMenu \? \{ \.\.\.info, status: "closed" \} : info/);
});

test("the menu screen of such a day says Closed and when the restaurant reopens, in every language", () => {
  assert.match(app, /state\.menuError = \{ status: "closed", reason: err\.message, reopens \}/);
  assert.match(app, /tr\("restaurantReopensBody", \{ date: fmtLong\(state\.menuError\.reopens\) \}\)/);
  for (const lang of LANGUAGES) assert.match(translations[lang.code].restaurantReopensBody, /\{date\}/, lang.code);
});

test("a registered courier changes the alert choice from Profile, in the New-order emails sheet", () => {
  assert.match(app, /if \(!DEMO && loadDeliveryRegisteredEmail\(\) && belvalListed\(\)\) \{/);
  assert.match(app, /courierRow\.addEventListener\("click", \(\) => openDeliveryRegisterSheet\(true\)\);/);
  assert.match(app, /if \(\(registered && !manage\) \|\| document\.querySelector\("\.delivery-register-sheet"\)\) return;/);
  assert.match(app, /sheet\.append\(deliveryRegisterCard\(\)\);/);
});

test("Delivery opens on the campus of a linked order, else of a delivery in hand the open tab would hide", () => {
  assert.match(app, /if \(linked\) state\.deliveryCampusFilter = orderCampus\(linked\);/);
  assert.match(app, /else if \(carried\.length > 0 && !carried\.some\(\(o\) => orderCampus\(o\) === state\.deliveryCampusFilter\)\) state\.deliveryCampusFilter = orderCampus\(carried\[0\]\);/);
});

test("the self-reload waits while a basket has items, a sheet is open or the screen can't be restored", () => {
  assert.match(app, /if \(state\.selection\.length > 0 \|\| !RESTORABLE_SCREENS\.has\(state\.screen\) \|\| document\.querySelector\("\.sheet-overlay, \.dish-detail-overlay"\)\) return;/);
});

test("the app reloads itself when it comes back to the front and its script changed on the server", () => {
  assert.match(app, /fetch\(import\.meta\.url, \{ method: "HEAD", cache: "no-store" \}\)/);
  assert.match(app, /document\.visibilityState !== "visible" \|\| !loaded/);
  assert.match(app, /if \(now && now !== loaded\) location\.reload\(\);/);
});
