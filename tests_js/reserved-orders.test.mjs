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
  assert.match(card, /const isReserved = !isDelivered && Boolean\(order\.claimed_at\) && !order\.mine_courier && !order\.mine_customer;/);
});

test("a reserved card is returned before any action button is built", () => {
  const returned = card.indexOf("if (isFogged) return card;");
  assert.ok(returned > 0, "reserved and delivered cards must return early");
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

test("the customer gets a Cancel order link (instead of the courier's release link), until a courier has the food", () => {
  const link = card.slice(card.indexOf("deliveryCancelOrder") - 600, card.indexOf("deliveryCancelledToast") + 200);
  assert.match(card, /order\.mine_customer && !order\.mine_courier && !order\.picked_up_at && \["pending", "reviewing", "awaiting_confirmation"\]\.includes\(order\.status\)/);
  assert.match(link, /\/api\/orders\/\$\{order\.id\}\/cancel/);
  assert.match(link, /window\.confirm/); // a mis-tap must not cancel an order
  // the courier's release link is built only in the courier branch
  const courierBranch = card.slice(card.indexOf("else if (order.mine_courier && !order.picked_up_at)"), card.indexOf("else if (order.mine_customer && order.picked_up_at)"));
  assert.match(courierBranch, /deliveryReleaseClaim/);
  assert.doesNotMatch(courierBranch, /deliveryCancelOrder/);
});

for (const key of ["deliveryCancelOrder", "deliveryCancelledToast"]) {
  test(`${key} exists in all 11 languages`, () => {
    assert.equal((i18n.match(new RegExp(`^\\s+${key}: "[^"]+",$`, "gm")) || []).length, 11);
  });
}

test("a rejected saved email asks for the code again instead of a bare error, on every step", () => {
  assert.match(js, /function reverifyIfRejected\(err, retryBtn\) \{[\s\S]*?err\.status === 403[\s\S]*?email_not_verified[\s\S]*?clearRegisteredEmail\(\);[\s\S]*?openEmailSheet\(retryBtn/);
  assert.equal((card.match(/reverifyIfRejected\(err, (btn|release|cancel)\)/g) || []).length, 3);
});

test("after pick-up the courier gets 'I delivered'; the customer confirms with 'Mark as delivered'", () => {
  assert.match(card, /else if \(order\.mine_courier && order\.picked_up_at && !order\.handed_over_at && !order\.mine_customer\) \{[\s\S]*?"delivery-handover-btn", "deliveryHandedOver", "handed-over"/);
  assert.match(card, /else if \(order\.mine_customer && order\.picked_up_at\) \{[\s\S]*?"deliveryMarkDelivered", "mark-delivered"/);
});

for (const key of ["deliveryHandedOver", "deliveryHandedOverToast"]) {
  test(`${key} exists in all 11 languages`, () => {
    assert.equal((i18n.match(new RegExp(`^\\s+${key}: "[^"]+",$`, "gm")) || []).length, 11);
  });
}

test("a step button that follows another is held for a moment so a stray second tap can't skip a step", () => {
  assert.match(js, /const DELIVERY_STEP_SETTLE_MS = 2000;/);
  assert.match(card, /lastDeliveryStepAt = Date\.now\(\);/);
  assert.match(card, /if \(settle\) \{[\s\S]*?btn\.disabled = true;/);
  // every later step opts in; taking the order and cancelling do not
  for (const path of ["picked-up", "handed-over", "mark-delivered"]) {
    assert.match(card, new RegExp(`"${path}", [^\\n]*\\{ settle: true \\}`), `${path} is not held`);
  }
  assert.doesNotMatch(card, /"claim", [^\n]*settle: true/);
});

test("the courier's step bar: each step turns green when its button is tapped", () => {
  const start = js.indexOf("function courierStepsRow(order) {");
  const src = js.slice(start, js.indexOf("\nfunction courierActiveBlock(", start));
  assert.match(src, /const done = 1 \+ \(order\.picked_up_at \? 1 : 0\) \+ \(order\.handed_over_at \? 1 : 0\);/);
  // Run the real function against a stub DOM and read which steps/bars come out green.
  const hx = (k) => ({ stepAccepted: "Accepted", stepPickedUp: "Picked up", delivered: "Delivered" })[k];
  const el = (html) => html;
  const escapeHtml = (v) => v;
  const row = (order) => new Function("hx", "el", "escapeHtml", `${src}; return courierStepsRow;`)(hx, el, escapeHtml)(order);
  const greens = (html) => ({
    steps: [...html.matchAll(/<span class="courier-step (is-done|is-now)?"><i><\/i>([^<]+)<\/span>/g)].map((m) => `${m[2]}:${m[1] || "todo"}`),
    bars: [...html.matchAll(/courier-step-bar ([^"]*)"/g)].map((m) => m[1].trim() || "grey"),
  });
  assert.deepEqual(greens(row({})).steps, ["Accepted:is-done", "Picked up:is-now", "Delivered:todo"]);
  assert.deepEqual(greens(row({ picked_up_at: "x" })).steps, ["Accepted:is-done", "Picked up:is-done", "Delivered:is-now"]);
  assert.deepEqual(greens(row({ picked_up_at: "x", handed_over_at: "y" })).steps, ["Accepted:is-done", "Picked up:is-done", "Delivered:is-done"]);
  assert.deepEqual(greens(row({ picked_up_at: "x", handed_over_at: "y" })).bars, ["is-done", "is-done"]);
  assert.deepEqual(greens(row({})).bars, ["grey", "grey"]);
});

test("a delivered order stays on the list in the fog, tagged Delivered, with no buttons", () => {
  assert.match(card, /const isDelivered = Boolean\(order\.delivered_at\);/);
  assert.match(card, /const isReserved = !isDelivered && Boolean\(order\.claimed_at\)/);
  assert.match(card, /const isFogged = isReserved \|\| isDelivered;/);
  assert.match(card, /isDelivered \? hx\("delivered"\) : tr\("deliveryReserved"\)/);
  assert.ok(card.indexOf("if (isFogged) return card;") > 0, "fogged cards must return before any button is built");
  const list = js.slice(js.indexOf("function deliveryOrderListContent("), js.indexOf("async function loadDeliveryData("));
  assert.match(list, /buckets\.delivered\.filter\(\(o\) => o\.order_date >= today\)/);
  assert.match(list, /\[\.\.\.offers, \.\.\.taken, \.\.\.delivered\]/);
  assert.match(list, /delivered\.length === 0\) \{/); // the big empty state is only for a screen with nothing at all
});

test("a delivered card shows the date, not the admin-side status (Pending)", () => {
  assert.match(card, /fmtLong\(order\.order_date\)\)\}\$\{isDelivered \? "" : `/);
});

test("the discount banner lines up with the title and the cards: same side margins, same corner radius", async () => {
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("../static/app.css", import.meta.url), "utf8");
  const rule = (sel) => css.match(new RegExp(`${sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`))[1];
  const side = (decls) => decls.match(/margin:\s*[^;]*?\s+(var\(--space-\d\))\s+[^;]*?;/)[1];
  assert.equal(side(rule(".discount-banner")), side(rule(".large-title")));          // the title's own side margin
  assert.match(rule(".restaurant-grid"), new RegExp(`padding:[^;]*${side(rule(".large-title")).replace(/[()]/g, "\\$&")}`)); // the cards' side padding
  assert.match(rule(".discount-banner"), /border-radius:\s*var\(--radius-lg\)/);    // same corners as .restaurant-card
  assert.match(rule(".restaurant-card"), /border-radius:\s*var\(--radius-lg\)/);
});
