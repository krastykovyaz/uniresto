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
  assert.ok(card.indexOf("const stepButton") > returned, "buttons are built before the reserved check");
});

test("one button at a time: take it, then picked up (its courier), then delivered (its customer)", () => {
  // The three steps, each in its own exclusive branch.
  assert.match(card, /if \(!order\.claimed_at\) \{[\s\S]*?"delivery-claim-btn", "deliveryClaimJob", "claim"/);
  assert.match(card, /else if \(order\.mine_courier && !order\.picked_up_at\) \{[\s\S]*?"delivery-pickup-btn", "deliveryConfirmPickup", "picked-up"/);
  assert.match(card, /else if \(order\.mine_customer && order\.picked_up_at\) \{[\s\S]*?"delivery-mark-delivered", "deliveryMarkDelivered", "mark-delivered"/);
});

test("the courier never gets a Mark as delivered button", () => {
  const courierBranches = card.slice(card.indexOf("else if (order.mine_courier && !order.picked_up_at)"), card.indexOf("else if (order.mine_customer && order.picked_up_at)"));
  assert.doesNotMatch(courierBranches, /mark-delivered/);
  assert.match(card, /deliveryAwaitingCustomer/); // instead they are told the customer confirms
});

test("releasing a taken order is a quiet link, not a second button", () => {
  assert.match(card, /class="delivery-release-link"/);
  assert.doesNotMatch(card, /secondary-button delivery-release-btn/);
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

for (const key of ["deliveryReserved", "deliveryAwaitingCustomer", "deliveryClaimJob"]) {
  test(`${key} exists in all 11 languages`, () => {
    assert.equal((i18n.match(new RegExp(`^\\s+${key}: "[^"]+",$`, "gm")) || []).length, 11);
  });
}
