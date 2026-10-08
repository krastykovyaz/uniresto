// Demo mode: sample orders for showing the Delivery screen, with NOTHING behind them.
//
// Opened as  https://resto.unilu.space/?demo=1  the Delivery screen lists a few made-up orders and
// lets you tap through the courier steps. It is purely visual: every order lives in the page's own
// memory, no request about orders is ever sent, nothing is stored (not even in the browser), nobody
// is emailed or messaged, and a reload starts over. Ordinary visitors never see it: it only exists
// behind the explicit ?demo=1 address.
//
// Pure functions, no DOM and no network, unit-tested under Node (tests_js/demo.test.mjs).

export function isDemoMode(search) {
  try {
    return new URLSearchParams(search).get("demo") === "1";
  } catch {
    return false;
  }
}

const ALTIUS = "UDL-CKB - Altius - Restaurant";
const JOHNS = "UDL-CKB - Brasserie John's - Restaurant";

function minutesAgo(now, minutes) {
  return new Date(now.getTime() - minutes * 60000).toISOString();
}

function order(id, restaurant, items, building, now, fields) {
  return {
    id,
    restaurant_name: restaurant,
    delivery_location: building,
    status: "pending",
    items: items.map(([category, name]) => ({ category, name, quantity: 1, requires_early_order: false })),
    claimed_at: null,
    picked_up_at: null,
    handed_over_at: null,
    delivered_at: null,
    mine_courier: false,
    mine_customer: false,
    expired: false,
    ...fields,
  };
}

/**
 * Three sample orders for `today` (YYYY-MM-DD): one open (take it and walk through the steps), one
 * already taken by someone else (greyed, Reserved) and one delivered earlier today (greyed,
 * Delivered). The open one keeps its room in `_full_location`, shown only once it is "yours".
 */
export function createDemoOrders(today, now = new Date()) {
  return [
    order(9001, ALTIUS, [["Végétarien", "Tikka Masala au tofu"], ["Entrée", "Soupe de carottes au gingembre"]], "Building A (Central building)", now, {
      order_date: today, created_at: minutesAgo(now, 25), _full_location: "Building A (Central building) — 2.05",
    }),
    order(9002, ALTIUS, [["Non-végétarien", "Poulet, sauce aux cacahuètes"], ["Dessert", "Strudel aux poires, pommes, raisins secs et amandes, chantilly"]], "Building G", now, {
      order_date: today, created_at: minutesAgo(now, 40), claimed_at: minutesAgo(now, 12),
    }),
    order(9003, JOHNS, [["Non-végétarien", "Rumsteak grillé, beurre à l'ail"], ["Féculents", "Gratin dauphinois"]], "Building G", now, {
      order_date: today, created_at: minutesAgo(now, 95), claimed_at: minutesAgo(now, 70), picked_up_at: minutesAgo(now, 62),
      handed_over_at: minutesAgo(now, 48), delivered_at: minutesAgo(now, 45),
    }),
  ];
}

/** Applies one courier/customer step to a demo order, in place. Returns the order. */
export function applyDemoStep(order, step, now = new Date()) {
  const stamp = now.toISOString();
  if (step === "claim") {
    order.claimed_at = stamp;
    order.mine_courier = true;
    if (order._full_location) order.delivery_location = order._full_location;
  } else if (step === "picked-up") {
    order.picked_up_at = stamp;
  } else if (step === "handed-over") {
    order.handed_over_at = stamp;
  } else if (step === "mark-delivered") {
    order.delivered_at = stamp;
    // like a real delivered order: nothing left to find, so just the building
    if (order._full_location) order.delivery_location = order._full_location.split(" — ")[0];
  } else if (step === "unclaim") {
    order.claimed_at = null;
    order.mine_courier = false;
    if (order._full_location) order.delivery_location = order._full_location.split(" — ")[0];
  } else if (step === "cancel") {
    order.status = "cancelled";
  } else {
    throw new Error(`unknown demo step ${step}`);
  }
  return order;
}

// How long the made-up customer takes to confirm the delivery, so a demo reaches its end on its own.
export const DEMO_CUSTOMER_CONFIRM_MS = 6000;
