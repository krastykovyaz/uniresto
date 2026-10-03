import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { allNotificationKeys } from "../static/notifications.js";

// The kinds a device can switch on or off are listed twice, in JS (static/notifications.js) and in Python
// (orderability_engine/push_notify.py PUSH_KINDS). They must stay identical or a switch silently does nothing.
test("the notification kinds match the server's PUSH_KINDS exactly", () => {
  const py = readFileSync(new URL("../orderability_engine/push_notify.py", import.meta.url), "utf8");
  const match = py.match(/PUSH_KINDS\s*=\s*\(([^)]*)\)/);
  assert.ok(match, "PUSH_KINDS not found in push_notify.py");
  const serverKinds = [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(allNotificationKeys(), serverKinds);
});
