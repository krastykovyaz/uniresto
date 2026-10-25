import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");

test("every order and quote names each dish by category and name, not only by its position id", () => {
  assert.match(app, /function selectionPayload\(\)/);
  assert.match(app, /category: item\.category, name: item\.name/);
  assert.equal((app.match(/items: selectionPayload\(\)/g) || []).length, 2); // the quote and the order
  assert.ok(!/items: state\.selection\.map\(\(s\) => \(\{ id: s\.menuItemId/.test(app));
});

test("when the server says the menu changed, the basket is re-pinned and the customer is told", () => {
  assert.match(app, /err\.body\.error === "menu_changed"/);
  assert.match(app, /async function recoverFromMenuChange\(goneDishes\)/);
  assert.match(app, /tr\("menuChangedBasket", \{ dishes: names\.join\(", "\) \}\)/);
  assert.equal((i18n.match(/menuChangedBasket:/g) || []).length, 11);
});

test("the ordering funnel is counted anonymously: basket, review, confirm, what stopped them, why they left", () => {
  assert.match(app, /function trackFunnel\(event, label, \{ once = false \} = \{\}\)/);
  for (const step of ['trackFunnel("basket_add"', 'trackFunnel("review_open"', 'trackFunnel("confirm_press")', 'trackFunnel("review_leave"', 'trackFunnel("order_error"']) {
    assert.ok(app.includes(step), step);
  }
  for (const reason of ["no_building", "no_room", "no_email", "bad_email", "bad_phone", "no_uni_email"]) {
    assert.ok(app.includes(`trackFunnel("confirm_blocked", "${reason}")`), reason);
  }
  assert.match(app, /function reviewMissing\(\)/);
});
