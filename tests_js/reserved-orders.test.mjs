import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// static/app.js can't be imported without a DOM, so read the rules as text.
const js = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../static/app.css", import.meta.url), "utf8");

const cardStart = js.indexOf("function deliveryOrderCard(");
const card = js.slice(cardStart, js.indexOf("\nfunction deliverySection(", cardStart));

test("a taken order is reserved unless it is the caller's own (as customer or courier)", () => {
  assert.match(card, /const isReserved = Boolean\(order\.claimed_at\) && !order\.mine_courier && !order\.mine_customer;/);
});

test("a reserved card is returned before any action button is built", () => {
  const returned = card.indexOf("if (isReserved) return card;");
  assert.ok(returned > 0, "reserved cards must return early");
  for (const cls of ["delivery-claim-btn", "delivery-pickup-btn", "delivery-release-btn", "delivery-mark-delivered"]) {
    assert.ok(card.indexOf(`"secondary-button ${cls}"`) > returned, `${cls} is built before the reserved check`);
  }
});

test("pick-up and release are only offered to the courier who took the order", () => {
  assert.match(card, /else if \(!order\.picked_up_at && order\.mine_courier\)/);
});

test("the list shows taken orders (reserved) instead of a contradictory empty state", () => {
  const list = js.slice(js.indexOf("function deliveryOrderListContent("), js.indexOf("async function loadDeliveryData("));
  assert.match(list, /const taken = buckets\.pending\.filter\(\(o\) => o\.claimed_at && !o\.mine_courier\)/);
  assert.match(list, /offers\.length === 0 && active\.length === 0 && taken\.length === 0/);
  assert.match(list, /delivery-no-offers/);
});

test("the fog style removes pointer events", () => {
  const rule = css.match(/\.delivery-order-card\.is-reserved\s*\{[^}]*\}/);
  assert.ok(rule, "missing .is-reserved rule");
  assert.match(rule[0], /pointer-events:\s*none/);
  assert.match(rule[0], /opacity/);
});

test("deliveryReserved exists in all 11 languages", () => {
  assert.equal((i18n.match(/^\s+deliveryReserved: "[^"]+",$/gm) || []).length, 11);
});
