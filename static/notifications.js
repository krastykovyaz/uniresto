// What the Notifications screen (Profile > Notifications) is made of, kept free
// of the DOM so it can be unit-tested (tests_js/notifications.test.mjs): the list
// of notification kinds, the per-device switches, and which state the device is in.

// Grouped as the screen shows them. `key` is what's stored per device, and what the
// server will filter on when it starts sending pushes; titleKey/descKey are i18n keys.
export const NOTIFICATION_EVENTS = [
  {
    groupKey: "notifGroupOrders",
    items: [
      { key: "order", titleKey: "notifOrderStatus", descKey: "notifOrderStatusDesc" },
      { key: "courier", titleKey: "notifCourier", descKey: "notifCourierDesc" },
    ],
  },
  {
    groupKey: "notifGroupDelivering",
    items: [
      { key: "newDelivery", titleKey: "notifNewDelivery", descKey: "notifNewDeliveryDesc" },
      { key: "reminder", titleKey: "notifReminder", descKey: "notifReminderDesc" },
    ],
  },
  {
    groupKey: "notifGroupNews",
    items: [
      { key: "luni", titleKey: "notifLuni", descKey: "notifLuniDesc" },
      { key: "favorite", titleKey: "notifFavorite", descKey: "notifFavoriteDesc" },
    ],
  },
];

export const NOTIFICATION_PREFS_KEY = "uniresto.notifications.v1";

export function allNotificationKeys() {
  return NOTIFICATION_EVENTS.flatMap((g) => g.items.map((i) => i.key));
}

// Every kind is on until the person switches it off, so turning notifications on
// is one tap. Anything stored that isn't a known key, or isn't a boolean, is ignored.
export function loadNotificationPrefs(storage) {
  const prefs = Object.fromEntries(allNotificationKeys().map((k) => [k, true]));
  try {
    const stored = JSON.parse(storage.getItem(NOTIFICATION_PREFS_KEY) || "{}");
    for (const key of Object.keys(prefs)) {
      if (typeof stored[key] === "boolean") prefs[key] = stored[key];
    }
  } catch {
    /* unreadable or no storage -- the defaults stand */
  }
  return prefs;
}

export function saveNotificationPrefs(storage, prefs) {
  try {
    storage.setItem(NOTIFICATION_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* private mode / storage full -- the choice just won't be remembered */
  }
}

// Which of the five situations this device is in:
//   install      iPhone/iPad, opened in a Safari tab: only an app added to the Home
//                Screen can get push, so the person has to do that first
//   unsupported  no Notification / service worker / push API at all
//   denied       the person (or their browser) blocked it
//   granted      allowed -- the switches work
//   default      not asked yet -- show the "turn on" button
export function notificationState({ hasApi, permission, isIos, isStandalone }) {
  if (isIos && !isStandalone) return "install";
  if (!hasApi) return "unsupported";
  if (permission === "denied") return "denied";
  if (permission === "granted") return "granted";
  return "default";
}
