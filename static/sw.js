// UniResto's service worker: it only shows push notifications and opens the app
// when one is tapped. No caching and no offline mode -- the app itself is
// unchanged by it. Registered from the Notifications screen (static/app.js),
// served at /sw.js so it can control the whole site (see app.py).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "UniResto", {
      body: data.body || "",
      icon: "/static/favicon-512.png",
      badge: "/static/favicon-32.png",
      tag: data.tag,
      data: { url: data.url || "/" },
    })
  );
});

// A tap opens the notification's page in the app's own window: a visible one if there is one, taking it
// to the page; otherwise a new window. Only UniResto's own origin (never /admin, never another site) --
// anything else falls back to the start page.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const origin = self.location.origin;
  let target = origin + "/";
  try {
    const wanted = new URL((event.notification.data && event.notification.data.url) || "/", origin);
    if (wanted.origin === origin) target = wanted.href;
  } catch {
    /* unparseable url -- the start page */
  }
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (windows) => {
      const ours = windows.filter((w) => {
        try {
          const u = new URL(w.url);
          return u.origin === origin && !u.pathname.startsWith("/admin");
        } catch {
          return false;
        }
      });
      const win = ours.find((w) => w.visibilityState === "visible") || ours[0];
      if (!win) return self.clients.openWindow(target);
      try {
        if (win.url !== target && "navigate" in win) await win.navigate(target);
      } catch {
        /* a window we don't control can't be navigated -- just bring it to the front */
      }
      return win.focus();
    })
  );
});
