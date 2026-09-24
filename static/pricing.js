// OUR OWN meal-formula pricing rule -- NOT Restopolis data. Mirrors
// orderability_engine/pricing.py exactly (same tier prices, same
// pairing logic), so the instant local preview the UI shows matches what
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
// The 4 real Restopolis "Constant products" sandwich categories -- every
// sandwich on the real menu falls into exactly one of these (see
// data/menus.json), never a separate "Sandwich" category of its own.
export const SANDWICH_CATEGORIES = new Set([
  "01.1 Sandwiches végétariens",
  "01.2 Sandwiches végans",
  "01.3 Sandwiches non-végétariens",
  "01.4 Sandwiches sans gluten",
]);

export const MEAL_TIER_PRICES = {
  main: 6.0,
  main_starter: 7.0,
  main_starter_dessert: 8.0,
};
export const SANDWICH_PRICE = 4.0;

/**
 * lines: [{ category, quantity }] -- category is Restopolis's raw string.
 * Returns { formulaCount, mainCount, starterCount, dessertCount,
 * sandwichCount, total, reason }, same shape (camelCase) and same
 * semantics as the backend's compute_formula_total(): a starter only
 * upgrades the tier when paired with a main, a dessert only upgrades
 * further when paired with a starter -- otherwise `total` is null and
 * `reason` is "no_main_dish" or "dessert_without_starter". Mains are
 * paired against starters/desserts greedily, one-for-one, so an extra
 * main with no starter of its own stays at the plain tier instead of
 * being overcharged.
 */
export function computeFormulaTotal(lines) {
  const mainQty = lines.filter((l) => MAIN_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const starterQty = lines.filter((l) => STARTER_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const dessertQty = lines.filter((l) => DESSERT_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const sandwichQty = lines.filter((l) => SANDWICH_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const formulaCount = mainQty + starterQty + dessertQty + sandwichQty;

  const base = {
    formulaCount,
    mainCount: mainQty,
    starterCount: starterQty,
    dessertCount: dessertQty,
    sandwichCount: sandwichQty,
    total: null,
    reason: null,
  };

  if (formulaCount === 0) {
    return base;
  }

  if (mainQty === 0 && (starterQty > 0 || dessertQty > 0)) {
    return { ...base, reason: "no_main_dish" };
  }

  if (dessertQty > 0 && starterQty === 0) {
    return { ...base, reason: "dessert_without_starter" };
  }

  const pairedStarter = Math.min(mainQty, starterQty);
  const pairedDessert = Math.min(pairedStarter, dessertQty);
  const mainsFull = pairedDessert;
  const mainsWithStarterOnly = pairedStarter - pairedDessert;
  const mainsPlain = mainQty - pairedStarter;

  const mealTotal =
    mainsFull * MEAL_TIER_PRICES.main_starter_dessert +
    mainsWithStarterOnly * MEAL_TIER_PRICES.main_starter +
    mainsPlain * MEAL_TIER_PRICES.main;
  const sandwichTotal = sandwichQty * SANDWICH_PRICE;

  return { ...base, total: Math.round((mealTotal + sandwichTotal) * 100) / 100 };
}
