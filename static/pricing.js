// OUR OWN meal-formula pricing rule -- NOT Restopolis data. Mirrors
// orderability_engine/pricing.py exactly (same tier prices, same
// pairing logic, same per-sandwich price table), so the instant local
// preview the UI shows matches what the backend will confirm at
// "Confirm order" time. See that module's docstring for the full
// rationale -- these are the REAL, OFFICIAL Restopolis price lists
// (adultes/staff tier), not placeholders -- this file only re-states
// the constants/logic, not the reasoning, to avoid drifting out of sync.
//
// Pure, no DOM access -- unit-tested directly under Node
// (tests_js/pricing.test.mjs), same pattern as order-math.js.

export const MAIN_CATEGORIES = new Set(["Non-végétarien", "Végétarien", "Végan"]);
export const STARTER_CATEGORIES = new Set(["Entrée"]);
export const DESSERT_CATEGORIES = new Set(["Dessert"]);
export const SNACK_CATEGORIES = new Set(["Snack à emporter"]);
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
  main: 6.7,
  main_starter: 7.7,
  main_starter_dessert: 8.7,
};
export const SNACK_PRICE = 4.8;

// Transcribed directly from Restopolis's official "LISTE DE PRIX 26/27
// -- CAFÉTÉRIA" (adultes column) -- see pricing.py's own copy of this
// table for the full rationale (why these exact keys, why an unmapped
// sandwich is left unpriced rather than guessed).
export const SANDWICH_PRICES = {
  "1/2 Levain Cheesy Mushroom": 4.0,
  "1/2 Levain fromage": 3.3,
  "1/2 Levain Green Sandwich": 4.0,
  "1/2 Levain Parmigiana Sandwich": 4.0,
  "1/2 Levain The ultimate egg Sandwich": 4.0,
  "1/2 Levain Tortilla Olé": 4.0,
  "Ciabatta tomate-mozzarella et pesto": 4.0,
  "Petit pain blanc fromage": 2.3,
  "1/2 Levain Humi (houmous aux légumes locaux grillés)": 4.0,
  "1/2 tranche de pain": 0.25,
  "Petit pain blanc nature": 0.7,
  'Petit pain blanc "Schockelasbotter végan"': 1.85,
  "1/2 Flaguette Kebab de boeuf (sauce Tzatziki)": 4.0,
  '1/2 Levain "Great César"': 4.0,
  '1/2 Levain "Pastrami"': 3.3,
  "1/2 Levain jambon cuit": 3.3,
  "1/2 Levain salami": 2.3,
  "Petit pain blanc jambon cuit": 2.3,
  "Petit pain blanc salami": 2.3,
  'Mini baguette sans gluten "Schockelasbotter végan"': 4.0,
  "Mini baguette sans gluten fromage": 4.0,
  "Mini baguette sans gluten jambon cuit": 4.0,
  "Mini baguette sans gluten salami": 4.0,
};

/**
 * lines: [{ category, name, quantity }] -- category/name are
 * Restopolis's raw strings. Returns { formulaCount, mainCount,
 * starterCount, dessertCount, sandwichCount, snackCount, total, reason },
 * same shape (camelCase) and same semantics as the backend's
 * compute_formula_total(): a starter OR a dessert alone (either one)
 * upgrades a main to the middle tier, both together reach the top tier
 * -- otherwise `total` is null and `reason` is "no_main_dish". Mains
 * are paired against starters/desserts greedily (full-tier pairs
 * first, then partial-tier), so an extra main with no side of its own
 * stays at the plain tier instead of being overcharged. Snacks and
 * sandwiches price independently (never blocked by an unpriceable
 * meal formula); an unrecognized sandwich name is left unpriced,
 * never guessed at.
 */
export function computeFormulaTotal(lines) {
  const mainQty = lines.filter((l) => MAIN_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const starterQty = lines.filter((l) => STARTER_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const dessertQty = lines.filter((l) => DESSERT_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const sandwichQty = lines.filter((l) => SANDWICH_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const snackQty = lines.filter((l) => SNACK_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const formulaCount = mainQty + starterQty + dessertQty + sandwichQty + snackQty;

  const base = {
    formulaCount,
    mainCount: mainQty,
    starterCount: starterQty,
    dessertCount: dessertQty,
    sandwichCount: sandwichQty,
    snackCount: snackQty,
    total: null,
    reason: null,
  };

  if (formulaCount === 0) {
    return base;
  }

  if (mainQty === 0 && (starterQty > 0 || dessertQty > 0)) {
    return { ...base, reason: "no_main_dish" };
  }

  // Full tier first: pair each main with BOTH a starter AND a dessert,
  // as many times as all three allow. Then the partial tier: pair
  // whatever mains are left with EITHER a remaining starter OR a
  // remaining dessert (either alone upgrades the tier the same
  // amount). Whatever mains still have neither price as the plain tier.
  const fullQty = Math.min(mainQty, starterQty, dessertQty);
  let remainingMain = mainQty - fullQty;
  const remainingStarter = starterQty - fullQty;
  const remainingDessert = dessertQty - fullQty;

  const pairedWithStarter = Math.min(remainingMain, remainingStarter);
  remainingMain -= pairedWithStarter;
  const pairedWithDessert = Math.min(remainingMain, remainingDessert);
  remainingMain -= pairedWithDessert;
  const partialQty = pairedWithStarter + pairedWithDessert;
  const plainQty = remainingMain;

  const mealTotal =
    fullQty * MEAL_TIER_PRICES.main_starter_dessert + partialQty * MEAL_TIER_PRICES.main_starter + plainQty * MEAL_TIER_PRICES.main;
  const snackTotal = snackQty * SNACK_PRICE;
  const sandwichTotal = lines
    .filter((l) => SANDWICH_CATEGORIES.has(l.category) && SANDWICH_PRICES[l.name] !== undefined)
    .reduce((sum, l) => sum + SANDWICH_PRICES[l.name] * l.quantity, 0);

  const grandTotal = mealTotal + snackTotal + sandwichTotal;
  // Can genuinely be 0 despite formulaCount > 0: e.g. a cart containing
  // ONLY a sandwich whose exact name isn't in SANDWICH_PRICES (no main
  // dish either, so mealTotal is also 0) -- nothing was actually
  // priced, so total must read as "we don't have a price for this"
  // (null), not a misleading €0.00 implying the order is free.
  return { ...base, total: grandTotal > 0 ? Math.round(grandTotal * 100) / 100 : null };
}
