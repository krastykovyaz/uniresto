// OUR OWN per-item course pricing rule -- NOT Restopolis data. Mirrors
// orderability_engine/pricing.py exactly (same category prices, same
// arithmetic), so the instant local preview the UI shows matches what
// the backend will confirm at "Confirm order" time. See that module's
// docstring for the full rationale; this file only re-states the
// constants/logic, not the reasoning, to avoid drifting out of sync.
//
// Pure, no DOM access -- unit-tested directly under Node
// (tests_js/pricing.test.mjs), same pattern as order-math.js.

export const MAIN_CATEGORIES = new Set(["Non-végétarien", "Végétarien", "Végan"]);
export const STARTER_CATEGORIES = new Set(["Entrée"]);
export const DESSERT_CATEGORIES = new Set(["Dessert"]);
export const INCLUDED_SIDE_CATEGORIES = new Set(["Féculents", "Légumes"]);

export const CATEGORY_PRICES = {
  main: 6.0,
  starter: 2.0,
  dessert: 2.0,
};

/**
 * lines: [{ category, quantity }] -- category is Restopolis's raw string.
 * Returns { formulaCount, mainCount, starterCount, dessertCount, total,
 * reason }, same shape (camelCase) and same semantics as the backend's
 * compute_formula_total(). `reason` is always null -- kept in the shape
 * for compatibility with the earlier bundle-tier rule, which had
 * combinations it genuinely couldn't price; flat per-item pricing
 * doesn't.
 */
export function computeFormulaTotal(lines) {
  const mainQty = lines.filter((l) => MAIN_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const starterQty = lines.filter((l) => STARTER_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const dessertQty = lines.filter((l) => DESSERT_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const formulaCount = mainQty + starterQty + dessertQty;

  if (formulaCount === 0) {
    return { formulaCount: 0, mainCount: 0, starterCount: 0, dessertCount: 0, total: null, reason: null };
  }

  const total = mainQty * CATEGORY_PRICES.main + starterQty * CATEGORY_PRICES.starter + dessertQty * CATEGORY_PRICES.dessert;
  return {
    formulaCount,
    mainCount: mainQty,
    starterCount: starterQty,
    dessertCount: dessertQty,
    total: Math.round(total * 100) / 100,
    reason: null,
  };
}
