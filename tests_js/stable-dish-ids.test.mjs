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
