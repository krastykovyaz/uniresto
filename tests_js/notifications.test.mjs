import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NOTIFICATION_EVENTS,
  NOTIFICATION_PREFS_KEY,
  allNotificationKeys,
  loadNotificationPrefs,
  notificationState,
  saveNotificationPrefs,
} from "../static/notifications.js";

const memoryStorage = (initial = {}) => {
  const data = { ...initial };
  return { getItem: (k) => (k in data ? data[k] : null), setItem: (k, v) => void (data[k] = v), data };
};

test("every kind has a unique key and its own texts", () => {
  const keys = allNotificationKeys();
  assert.equal(new Set(keys).size, keys.length);
  assert.deepEqual(keys, ["order", "courier", "newDelivery", "reminder", "luni", "favorite"]);
  for (const group of NOTIFICATION_EVENTS) for (const i of group.items) assert.ok(i.titleKey && i.descKey);
});

test("everything is on by default", () => {
  assert.deepEqual(loadNotificationPrefs(memoryStorage()), {
    order: true, courier: true, newDelivery: true, reminder: true, luni: true, favorite: true,
  });
});

test("saved choices round-trip", () => {
  const storage = memoryStorage();
  const prefs = loadNotificationPrefs(storage);
  prefs.luni = false;
  saveNotificationPrefs(storage, prefs);
  assert.equal(loadNotificationPrefs(storage).luni, false);
  assert.equal(loadNotificationPrefs(storage).order, true);
});

test("junk in storage is ignored", () => {
  const junk = memoryStorage({ [NOTIFICATION_PREFS_KEY]: JSON.stringify({ order: "no", unknown: false, luni: false }) });
  const prefs = loadNotificationPrefs(junk);
  assert.equal(prefs.order, true); // not a boolean -> default
  assert.equal(prefs.luni, false);
  assert.equal("unknown" in prefs, false);
  assert.equal(loadNotificationPrefs(memoryStorage({ [NOTIFICATION_PREFS_KEY]: "{not json" })).order, true);
});

test("storage that throws never breaks the screen", () => {
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } };
  assert.equal(loadNotificationPrefs(broken).order, true);
  assert.doesNotThrow(() => saveNotificationPrefs(broken, { order: false }));
});

test("device states", () => {
  const base = { hasApi: true, permission: "default", isIos: false, isStandalone: false };
  assert.equal(notificationState(base), "default");
  assert.equal(notificationState({ ...base, permission: "granted" }), "granted");
  assert.equal(notificationState({ ...base, permission: "denied" }), "denied");
  assert.equal(notificationState({ ...base, hasApi: false }), "unsupported");
  // iPhone Safari tab has no push API at all -- it must say "install", not "unsupported"
  assert.equal(notificationState({ ...base, hasApi: false, isIos: true }), "install");
  assert.equal(notificationState({ ...base, isIos: true, isStandalone: true, permission: "granted" }), "granted");
});
