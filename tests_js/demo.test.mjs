import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DEMO_CUSTOMER_CONFIRM_MS, applyDemoStep, createDemoOrders, isDemoMode } from "../static/demo.js";

const demoSrc = readFileSync(new URL("../static/demo.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
const NOW = new Date("2026-10-08T10:00:00Z");

test("demo mode only exists behind the explicit ?demo=1 address", () => {
  assert.equal(isDemoMode("?demo=1"), true);
  assert.equal(isDemoMode("?lang=en&demo=1"), true);
  for (const s of ["", "?lang=en", "?demo=0", "?demo=true", "?demo=", "?Demo=1", "?src=demo"]) assert.equal(isDemoMode(s), false, s);
});

test("three sample orders for today: one open, one taken by someone else, one already delivered", () => {
  const [open, taken, done] = createDemoOrders("2026-10-08", NOW);
  assert.ok([open, taken, done].every((o) => o.order_date === "2026-10-08" && o.id >= 9000 && o.items.length === 2));
  assert.deepEqual([open.claimed_at, open.delivered_at], [null, null]);
  assert.ok(taken.claimed_at && !taken.delivered_at && !taken.mine_courier && !taken.mine_customer);
  assert.ok(done.claimed_at && done.picked_up_at && done.handed_over_at && done.delivered_at);
  // strangers see only the building; the room stays hidden until the order is yours
  assert.equal(open.delivery_location, "Building A (Central building)");
  assert.equal(open._full_location, "Building A (Central building) — 2.05");
});

test("walking an open order through every step, and giving it back", () => {
  const [open] = createDemoOrders("2026-10-08", NOW);
  applyDemoStep(open, "claim", NOW);
  assert.equal(open.mine_courier, true);
  assert.equal(open.delivery_location, "Building A (Central building) — 2.05");
  applyDemoStep(open, "unclaim", NOW);
  assert.equal(open.mine_courier, false);
  assert.equal(open.claimed_at, null);
  assert.equal(open.delivery_location, "Building A (Central building)");
  for (const step of ["claim", "picked-up", "handed-over"]) applyDemoStep(open, step, NOW);
  assert.ok(open.picked_up_at && open.handed_over_at && !open.delivered_at);
  applyDemoStep(open, "mark-delivered", NOW);
  assert.equal(open.delivered_at, NOW.toISOString());
  assert.equal(open.delivery_location, "Building A (Central building)"); // delivered: building only, as for a real order
  applyDemoStep(open, "cancel", NOW);
  assert.equal(open.status, "cancelled");
  assert.throws(() => applyDemoStep(open, "launch-rocket"));
});

test("the made-up customer confirms a few seconds after the courier hands over", () => {
  assert.ok(DEMO_CUSTOMER_CONFIRM_MS >= 3000 && DEMO_CUSTOMER_CONFIRM_MS <= 10000);
});

test("demo.js is purely visual: no network, no storage, no email", () => {
  for (const banned of [/\bfetch\s*\(/, /\bapi\s*\(/, /XMLHttpRequest/, /sendBeacon/, /localStorage/, /sessionStorage/, /indexedDB/, /document\./, /window\./]) {
    assert.doesNotMatch(demoSrc.replace(/\/\/.*$/gm, ""), banned);
  }
});

test("app.js: every demo branch is local -- the order calls are skipped, not reached", () => {
  assert.match(app, /const DEMO = isDemoMode\(window\.location\.search\);/);
  assert.match(app, /const result = DEMO\n\s+\? demoCall\(order, path, render\)\n\s+: await api\(`\/api\/orders\/\$\{order\.id\}\/\$\{path\}`/);
  assert.match(app, /if \(DEMO\) demoCall\(order, "unclaim", render\);\n\s+else await api\(/);
  assert.match(app, /if \(DEMO\) demoCall\(order, "cancel", render\);\n\s+else await api\(/);
  assert.match(app, /async function loadDeliveryData\(\) \{\n\s+if \(DEMO\) \{[\s\S]*?createDemoOrders\(localDateString\(\)\)[\s\S]*?return \{ orders: demoOrders, mine: [^}]*\};\n\s+\}\n\s+const \[orders, mine\]/);
  assert.match(app, /if \(DEMO\) return "demo@uni\.lu";/); // no email sheet, no code
  assert.match(app, /const askForEmail = \(\) => \{\n\s+if \(DEMO\) return;/);
  assert.match(app, /if \(!DEMO\) api\("\/api\/visit\/home"/); // a demo visit is not counted as a real one
  assert.match(app, /if \(DEMO\) app\.append\(el\(`<p class="demo-ribbon" role="note">/);
});

test("demoNotice exists in all 11 languages", () => {
  assert.equal((i18n.match(/^\s+demoNotice: ".+",$/gm) || []).length, 11);
});
