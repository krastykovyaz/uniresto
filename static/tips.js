// Floating tips: a short hint pointing at one control, shown once per person.
// The seen-list and the placement maths live here (testable without a page); app.js draws them.

export const TIP_STORAGE_KEY = "uniresto.tipsSeen.v1";

// id -> which control it points at and its text key (i18n.js).
export const TIPS = {
  // Above the card: below it the bubble would cover the Delivery card, which is tappable.
  "home-eat": { selector: ".restaurant-grid .restaurant-card", textKey: "tipHomeEat", prefer: "above" },
  "menu-share": { selector: ".menu-share-button", textKey: "tipMenuShare" },
  "delivery-online": { selector: ".courier-online-slot", textKey: "tipDeliveryOnline" },
};

export function loadSeenTips(storage) {
  try {
    const raw = JSON.parse(storage.getItem(TIP_STORAGE_KEY) || "[]");
    return new Set(Array.isArray(raw) ? raw.filter((id) => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

export function markTipSeen(storage, id) {
  try {
    const seen = loadSeenTips(storage);
    seen.add(id);
    storage.setItem(TIP_STORAGE_KEY, JSON.stringify([...seen]));
  } catch {
    /* storage unavailable: the tip simply may come back next visit */
  }
}

// Where the bubble goes, in the container's own coordinates: centred under the control (above
// it when there's no room below), kept inside the container with a margin, and the arrow's x
// still pointing at the control's centre.
export function placeTip({ anchor, container, tip, gap = 10, margin = 12, prefer = "below" }) {
  const anchorCenter = anchor.left - container.left + anchor.width / 2;
  let left = anchorCenter - tip.width / 2;
  left = Math.max(margin, Math.min(left, container.width - tip.width - margin));
  const below = anchor.bottom - container.top + gap;
  const above = anchor.top - container.top - gap - tip.height;
  const fitsBelow = below + tip.height <= container.height - margin && !(prefer === "above" && above >= margin);
  const top = fitsBelow ? below : above;
  const arrowLeft = Math.max(16, Math.min(anchorCenter - left, tip.width - 16));
  return { top, left, arrowLeft, above: !fitsBelow };
}
