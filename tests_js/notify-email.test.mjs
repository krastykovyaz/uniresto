import { test } from "node:test";
import assert from "node:assert/strict";
import { hasTwoEmails, normalizeNotifyChoice, pickNotifyEmail } from "../static/notify-email.js";

const PRIVATE = "me@gmail.com";
const UNI = "me@uni.lu";

test("the default is the private address, not the university one", () => {
  assert.equal(pickNotifyEmail(undefined, PRIVATE, UNI), PRIVATE);
  assert.equal(pickNotifyEmail("private", PRIVATE, UNI), PRIVATE);
  assert.equal(pickNotifyEmail("garbage", PRIVATE, UNI), PRIVATE);
});

test("choosing the university address sends there", () => {
  assert.equal(pickNotifyEmail("university", PRIVATE, UNI), UNI);
});

test("with only one address, that one is used whatever the choice", () => {
  assert.equal(pickNotifyEmail("private", "", UNI), UNI);
  assert.equal(pickNotifyEmail("university", PRIVATE, ""), PRIVATE);
  assert.equal(pickNotifyEmail("university", "", ""), "");
});

test("the choice is only offered for two different addresses", () => {
  assert.equal(hasTwoEmails(PRIVATE, UNI), true);
  assert.equal(hasTwoEmails("", UNI), false);
  assert.equal(hasTwoEmails(UNI, "ME@uni.lu"), false);
  assert.equal(normalizeNotifyChoice("university"), "university");
  assert.equal(normalizeNotifyChoice(null), "private");
});

test("the courier claim sends the chosen address and the app wires the sheet", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  assert.match(app, /notify_email: courierNotifyEmail\(\)/);
  assert.match(app, /openNotifyEmailSheet/);
  const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
  assert.equal((i18n.match(/notifyEmailRow:/g) || []).length, 11);
  assert.equal((i18n.match(/notifyEmailHint:/g) || []).length, 11);
});
