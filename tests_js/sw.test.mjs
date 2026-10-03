import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SOURCE = readFileSync(new URL("../static/sw.js", import.meta.url), "utf8");
const ORIGIN = "https://resto.unilu.space";

// Runs static/sw.js against a stub `self` and returns the registered handlers plus what they did.
function loadWorker({ windows = [] } = {}) {
  const handlers = {};
  const calls = { shown: [], opened: [], skipWaiting: 0, claimed: 0 };
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type, fn) => (handlers[type] = fn),
    skipWaiting: () => void calls.skipWaiting++,
    clients: {
      claim: () => void calls.claimed++,
      matchAll: async () => windows,
      openWindow: async (url) => void calls.opened.push(url),
    },
    registration: { showNotification: async (title, options) => void calls.shown.push({ title, options }) },
  };
  new Function("self", SOURCE)(self);
  return { handlers, calls };
}

const run = async (handler, event) => {
  const waits = [];
  handler({ ...event, waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
};

const fakeWindow = (url, visible = true) => {
  const w = { url, visibilityState: visible ? "visible" : "hidden", focused: 0, navigatedTo: null };
  w.focus = async () => void w.focused++;
  w.navigate = async (u) => void ((w.navigatedTo = u), (w.url = u));
  return w;
};

const click = (url) => ({ notification: { close() {}, data: url === undefined ? undefined : { url } } });

test("a push shows a notification with the payload", async () => {
  const { handlers, calls } = loadWorker();
  await run(handlers.push, { data: { json: () => ({ title: "Hi", body: "There", url: "/x", tag: "t" }) } });
  assert.equal(calls.shown.length, 1);
  assert.equal(calls.shown[0].title, "Hi");
  assert.deepEqual(
    { body: calls.shown[0].options.body, tag: calls.shown[0].options.tag, url: calls.shown[0].options.data.url },
    { body: "There", tag: "t", url: "/x" }
  );
});

test("a push with no data still shows something, titled UniResto", async () => {
  const { handlers, calls } = loadWorker();
  await run(handlers.push, { data: null });
  assert.equal(calls.shown[0].title, "UniResto");
  assert.equal(calls.shown[0].options.data.url, "/");
});

test("a push whose data is not JSON falls back to its text", async () => {
  const { handlers, calls } = loadWorker();
  await run(handlers.push, { data: { json: () => { throw new Error("bad"); }, text: () => "plain words" } });
  assert.equal(calls.shown[0].options.body, "plain words");
});

test("install activates immediately and takes control", async () => {
  const { handlers, calls } = loadWorker();
  handlers.install();
  await run(handlers.activate, {});
  assert.equal(calls.skipWaiting, 1);
  assert.equal(calls.claimed, 1);
});

test("the worker never intercepts requests or caches anything", () => {
  const { handlers } = loadWorker();
  assert.deepEqual(Object.keys(handlers).sort(), ["activate", "install", "notificationclick", "push"]);
});

test("a tap takes the visible app window to the notification's page and focuses it", async () => {
  const win = fakeWindow(`${ORIGIN}/`);
  const { handlers, calls } = loadWorker({ windows: [win] });
  await run(handlers.notificationclick, click("/#order-5"));
  assert.equal(win.navigatedTo, `${ORIGIN}/#order-5`);
  assert.equal(win.focused, 1);
  assert.deepEqual(calls.opened, []);
});

test("a tap prefers the visible window over a hidden one", async () => {
  const hidden = fakeWindow(`${ORIGIN}/`, false);
  const visible = fakeWindow(`${ORIGIN}/?lang=fr`, true);
  const { handlers } = loadWorker({ windows: [hidden, visible] });
  await run(handlers.notificationclick, click("/"));
  assert.equal(visible.focused, 1);
  assert.equal(hidden.focused, 0);
});

test("a tap never takes over an /admin tab or another site's window", async () => {
  const admin = fakeWindow(`${ORIGIN}/admin/orders?token=x`);
  const other = fakeWindow("https://example.com/");
  const { handlers, calls } = loadWorker({ windows: [admin, other] });
  await run(handlers.notificationclick, click("/"));
  assert.equal(admin.focused + other.focused, 0);
  assert.deepEqual(calls.opened, [`${ORIGIN}/`]);
});

test("a tap with no open window opens one", async () => {
  const { handlers, calls } = loadWorker({ windows: [] });
  await run(handlers.notificationclick, click("/?dish=1"));
  assert.deepEqual(calls.opened, [`${ORIGIN}/?dish=1`]);
});

test("a notification pointing off-site opens the start page instead", async () => {
  for (const bad of ["https://evil.example/phish", "//evil.example/x", "javascript:alert(1)"]) {
    const { handlers, calls } = loadWorker({ windows: [] });
    await run(handlers.notificationclick, click(bad));
    assert.deepEqual(calls.opened, [`${ORIGIN}/`], bad);
  }
});

test("a notification without data opens the start page", async () => {
  const { handlers, calls } = loadWorker({ windows: [] });
  await run(handlers.notificationclick, click(undefined));
  assert.deepEqual(calls.opened, [`${ORIGIN}/`]);
});

test("a window that can't be navigated is still brought to the front", async () => {
  const win = fakeWindow(`${ORIGIN}/`);
  win.navigate = async () => { throw new Error("not controlled"); };
  const { handlers } = loadWorker({ windows: [win] });
  await run(handlers.notificationclick, click("/x"));
  assert.equal(win.focused, 1);
});
