// Pure calculation functions for the mobile order UI. No DOM access here
// on purpose: this module is unit-tested directly under Node
// (tests_js/order-math.test.mjs) without a browser.
//
// These mirror orderability_engine/orders.py's aggregate_totals() /
// recalculate_order() semantics exactly, so the instant local preview
// the UI shows while the user is still selecting matches what the
// backend will confirm at "Confirm order" time (the backend recomputes
// independently from its own live menu fetch -- this module never
// substitutes for that, see README.md Part 3 "Never trust the browser").

export const MIN_QUANTITY = 1;
export const DEFAULT_MAX_QUANTITY = 10;

export function clampQuantity(quantity, maxQuantity = DEFAULT_MAX_QUANTITY) {
  const n = Math.trunc(Number(quantity));
  if (!Number.isFinite(n)) return MIN_QUANTITY;
  return Math.min(maxQuantity, Math.max(MIN_QUANTITY, n));
}

export function lineWeight(weightValue, quantity) {
  return weightValue == null ? null : weightValue * quantity;
}

export function lineTotal(price, quantity) {
  return price == null ? null : Math.round(price * quantity * 100) / 100;
}

/**
 * selectedItems: [{ menuItemId, quantity, portionId }]
 * menuItemsById: Map or plain object of id -> menu item (from the API's
 *   /menu response: has price, weight_value, weight_unit, name, category)
 *
 * Returns the same shape as the backend's aggregate_totals(), plus the
 * per-line breakdown, so the UI can render both the summary bar and the
 * review screen from one call.
 */
export function computeOrderTotals(selectedItems, menuItemsById) {
  const lines = selectedItems
    .map((sel) => {
      const item = menuItemsById instanceof Map ? menuItemsById.get(sel.menuItemId) : menuItemsById[sel.menuItemId];
      if (!item) return null; // stale selection (item no longer on the menu) -- silently excluded from totals, UI should also drop it
      const quantity = clampQuantity(sel.quantity, item.maxQuantity ?? DEFAULT_MAX_QUANTITY);
      return {
        menuItemId: sel.menuItemId,
        name: item.name,
        category: item.category,
        quantity,
        price: item.price,
        weightValue: item.weight_value,
        weightUnit: item.weight_unit,
        lineWeight: lineWeight(item.weight_value, quantity),
        lineTotal: lineTotal(item.price, quantity),
      };
    })
    .filter(Boolean);

  const itemCount = lines.length;
  const totalQuantity = lines.reduce((sum, l) => sum + l.quantity, 0);

  // Summed PER UNIT, never into one flat number: g (food), ml (drinks)
  // and piece can all appear in the same order, and adding e.g.
  // 250 g + 200 ml into a single "450" would be meaningless.
  const weightByUnit = {};
  for (const l of lines) {
    if (l.lineWeight != null) {
      weightByUnit[l.weightUnit] = round((weightByUnit[l.weightUnit] || 0) + l.lineWeight, 3);
    }
  }
  const unknownWeightPortions = lines
    .filter((l) => l.lineWeight == null)
    .reduce((sum, l) => sum + l.quantity, 0);

  const knownPriceLines = lines.filter((l) => l.lineTotal != null);
  const totalPriceKnown = knownPriceLines.reduce((sum, l) => sum + l.lineTotal, 0);
  const unknownPricePortions = lines
    .filter((l) => l.lineTotal == null)
    .reduce((sum, l) => sum + l.quantity, 0);

  return {
    lines,
    itemCount,
    totalQuantity,
    weightByUnit,
    weightFullyKnown: unknownWeightPortions === 0,
    unknownWeightPortions,
    totalPriceKnown: round(totalPriceKnown, 2),
    priceFullyKnown: unknownPricePortions === 0,
    unknownPricePortions,
  };
}

function round(n, decimals) {
  const factor = 10 ** decimals;
  return Math.round(n * factor) / factor;
}

export function formatWeightValue(value, unit) {
  if (value == null || unit == null) return "Portion size not specified";
  if (unit === "piece") return `${value} pc`;
  return `${value} ${unit}`;
}

/** e.g. "650 g", "600 g + 500 ml", "650 g + 2 unknown", "3 unknown" */
export function formatWeightSummary(totals) {
  if (totals.itemCount === 0) return "No items selected";
  const parts = Object.entries(totals.weightByUnit)
    .filter(([, value]) => value > 0)
    .map(([unit, value]) => `${trimTrailingZero(value)} ${unit}`);
  if (totals.unknownWeightPortions > 0) {
    parts.push(totals.unknownWeightPortions === 1 ? "1 unknown" : `${totals.unknownWeightPortions} unknown`);
  }
  return parts.length ? parts.join(" + ") : "Portion size not specified";
}

/** e.g. "€21.50", "€21.50 + 1 unpriced", "Price not available" */
export function formatPriceSummary(totals) {
  if (totals.itemCount === 0) return "No items selected";
  const parts = [];
  if (totals.totalPriceKnown > 0) parts.push(`€${totals.totalPriceKnown.toFixed(2)}`);
  if (totals.unknownPricePortions > 0) {
    const label = totals.unknownPricePortions === 1 ? "1 unpriced" : `${totals.unknownPricePortions} unpriced`;
    parts.push(label);
  }
  return parts.length ? parts.join(" + ") : "Price not available";
}

function trimTrailingZero(n) {
  return Number.isInteger(n) ? n : n.toFixed(1).replace(/\.0$/, "");
}
