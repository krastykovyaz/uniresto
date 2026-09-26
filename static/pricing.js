// OUR OWN meal-formula pricing rule -- NOT Restopolis data. Mirrors
// orderability_engine/pricing.py exactly (same tier prices, same
// pairing logic, same per-item price tables), so the instant local
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
export const VIENNOISERIE_CATEGORIES = new Set(["02. Viennoiseries"]);
export const HOMEMADE_CAKE_CATEGORIES = new Set(["03. Gâteaux et cookies maison"]);
export const TAKEAWAY_VITAMIN_CATEGORIES = new Set(["04. Vitamines à emporter"]);
export const FRUIT_CATEGORIES = new Set(["06. Fruits"]);
export const PASTRY_CATEGORIES = new Set(["08. Pâtisserie"]);
// The 3 real Restopolis "Boissons froides" (cold drinks) categories --
// water, juice and soda are split into separate raw categories, but all
// priced from the same combined official table below.
export const COLD_DRINK_CATEGORIES = new Set([
  "10.1 Boissons froides - Eau minérale et pétillante",
  "10.2 Boissons froides - Jus",
  "10.3 Boissons froides - Sodas",
]);
export const HOT_DRINK_CATEGORIES = new Set(["11. Boissons chaudes"]);
export const REUSABLE_PACKAGING_CATEGORIES = new Set(["12.1 Emballages et articles réutilisables"]);
export const SINGLE_USE_PACKAGING_CATEGORIES = new Set(["12.2 Emballages et articles à usage unique"]);

// Union of every category priced by exact item name (as opposed to the
// meal-formula tiers and the flat SNACK_PRICE) -- app.js excludes all of
// these from its "other/unpriced" bucket, same as SANDWICH_CATEGORIES
// and SNACK_CATEGORIES, since computeFormulaTotal() already prices them.
export const OTHER_NAME_PRICED_CATEGORIES = new Set([
  ...VIENNOISERIE_CATEGORIES,
  ...HOMEMADE_CAKE_CATEGORIES,
  ...TAKEAWAY_VITAMIN_CATEGORIES,
  ...FRUIT_CATEGORIES,
  ...PASTRY_CATEGORIES,
  ...COLD_DRINK_CATEGORIES,
  ...HOT_DRINK_CATEGORIES,
  ...REUSABLE_PACKAGING_CATEGORIES,
  ...SINGLE_USE_PACKAGING_CATEGORIES,
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

// All flat: every Viennoiserie is priced the same across apprenants/
// adultes/visiteurs on the official list (unlike sandwiches/meals,
// which vary by tier) -- verified directly off a clean, head-on photo
// of the price list, not assumed.
export const VIENNOISERIE_PRICES = {
  "Bretzel salé 80 g": 1.61,
  "Croissant 50 g": 1.58,
  "Croissant fourré 70 g": 1.77,
  "Huit 80 g": 1.81,
  "Pain au chocolat 70 g": 1.68,
  "Poche aux pommes 80 g": 1.74,
  "Streusel 80 g": 1.54,
};

// Also flat across tiers. "Banaboom" and "Dark Secret" aren't in the
// live fixture data yet but are real, priced items on the same
// official list, alongside the 3 that are -- same "include it anyway"
// precedent as SANDWICH_PRICES above. Dark Secret's own price cell was
// cut off in every available photo; every other item in this category
// shares one flat price, so that same price is used for it too, not a
// guess at an unrelated number.
export const HOMEMADE_CAKE_PRICES = {
  "Tasty Crunchy": 1.65,
  Nutchy: 1.65,
  "Crispy Apple": 1.65,
  Banaboom: 1.65,
  "Dark Secret": 1.65,
};

export const TAKEAWAY_VITAMIN_PRICES = {
  "Mini salades 150 g": 3.5,
  "Petit bol de potage": 2.2,
};

export const FRUIT_PRICES = {
  'Banane "commerce équitable"': 1.4,
  "Fruit frais entier": 1.4,
  "Mini fruits découpés mélangés/non-mélangés 150 g": 3.5,
};

export const PASTRY_PRICES = {
  "Dessert du Jour": 2.2,
};

// Cross-checked across BOTH official lists (the dine-in "RESTAURANT"
// sheet, which sells these by the bottle/"btl", and the "CAFÉTÉRIA"
// sheet, which sells "non consigné" -- no deposit -- versions at
// different sizes/prices) -- every real item name in data/menus.json
// across all 3 cold-drink categories matched exactly one line on one of
// the two sheets, with no ambiguity.
export const COLD_DRINK_PRICES = {
  "Lodyss fine pétillante 0,25 l btl": 0.95,
  "Lodyss plate 0,25 l btl": 0.95,
  "Rosport Blue 0,25 l btl": 0.95,
  "Rosport Blue 0,50 l btl": 1.45,
  "Rosport Blue 0,50 l non consigné": 1.5,
  "Rosport Blue 1,00 l btl": 3.1,
  "Rosport mat Menthe 0,50 l non consigné": 1.8,
  "Rosport mat Zitroun 0,50 l non consigné": 1.8,
  "Viva 0,25 l btl": 0.95,
  "Viva 0,50 l btl": 1.45,
  "Viva 0,50 l non consigné": 1.5,
  "Viva 1,00 l btl": 3.1,
  "Lëtzbuerger Drauwejus 0,25 l btl": 1.7,
  "Ramborn Apple & Quince Juice 0,33 l btl": 1.8,
  "Ramborn Apple Juice 0,33 btl": 1.8,
  "Ramborn Apple Soda 0,33 l btl": 1.8,
  "Ramborn Pear Apple Juice 0,33 l btl": 1.8,
  "Rosport Sunny Citron-Citron vert 0,50 l non consigné": 1.8,
  "Rosport Sunny Pêche 0,50 l non consigné": 1.8,
  "Coca Cola 0,20 l btl": 1.8,
  "Coca Cola 0,50 l non consigné": 2.2,
  "Fuze Tea - Black Tea Pêche/Hibiscus 0,20 l btl": 1.8,
  "Fuze Tea - Black Tea Pêche/Hibiscus 0,40 l non consigné": 2.2,
  "Lët'z kola 0,33 btl": 1.8,
  "Lët'z limo lemon & lime 0,33 btl": 1.8,
  "Lët'z limo orange 0,33 btl": 1.8,
  "Rosport Pom's 0,50 l non consigné": 2.2,
  "Rosport Wave 0,50 l non-consigné": 2.2,
};

// Matches the "Boissons chaudes" adultes column on both official lists
// exactly (cross-checked, identical on both -- hot drinks aren't
// restaurant-specific).
export const HOT_DRINK_PRICES = {
  'Café "commerce équitable"': 1.9,
  Cappuccino: 2.25,
  'Chocolat chaud "Commerce équitable"': 1.9,
  Espresso: 1.9,
  "Espresso double": 2.25,
  'Thé "commerce équitable"': 1.65,
  "Thermo Café 1,00 l": 5.0,
  "Thermo Café 1,50 l": 7.5,
  Tisane: 1.65,
};

// ECOBOX deposits are genuinely negative for the "Remboursement" (refund)
// lines on the official list -- a customer returning a box gets money
// back, so that line reduces the order total rather than adding to it,
// same as the real price sheet states.
export const REUSABLE_PACKAGING_PRICES = {
  "Consigne ECOBOX (500 ml)": 5.0,
  "Consigne ECOBOX (1000 ml)": 5.0,
  "Remboursement Consigne ECOBOX (500 ml)": -5.0,
  "Remboursement Consigne ECOBOX (1000 ml)": -5.0,
  myFrupstut: 3.0,
  myCan: 9.0,
  myKit: 3.0,
  myNapkin: 2.0,
  myBento: 9.0,
  myMug: 5.0,
  myBowl: 5.0,
  myMiniBowl: 2.5,
};

export const SINGLE_USE_PACKAGING_PRICES = {
  "Serviette en papier (à partir de la 2e serviette)": 0.1,
  "Fourchette en bois": 0.2,
  "Barquette pour pâtes/salades à emporter": 0.5,
  "Couvercle pour barquette à emporter": 0.5,
  "Sachet pour sandwiches": 0.1,
  "Gobelet comestible 220 ml": 0.6,
  "Cuillère comestible": 0.15,
};

// Every category priced by exact item name -- pairs a category set with
// its own price table, so computeFormulaTotal() can sum across all of
// them uniformly. A name not present in its category's table is left
// unpriced, never guessed.
const NAME_PRICED_GROUPS = [
  [SANDWICH_CATEGORIES, SANDWICH_PRICES],
  [VIENNOISERIE_CATEGORIES, VIENNOISERIE_PRICES],
  [HOMEMADE_CAKE_CATEGORIES, HOMEMADE_CAKE_PRICES],
  [TAKEAWAY_VITAMIN_CATEGORIES, TAKEAWAY_VITAMIN_PRICES],
  [FRUIT_CATEGORIES, FRUIT_PRICES],
  [PASTRY_CATEGORIES, PASTRY_PRICES],
  [COLD_DRINK_CATEGORIES, COLD_DRINK_PRICES],
  [HOT_DRINK_CATEGORIES, HOT_DRINK_PRICES],
  [REUSABLE_PACKAGING_CATEGORIES, REUSABLE_PACKAGING_PRICES],
  [SINGLE_USE_PACKAGING_CATEGORIES, SINGLE_USE_PACKAGING_PRICES],
];

/**
 * The single, real adultes-tier price for ONE item ({ category, name }),
 * or null when this module doesn't have a fixed per-item price for it --
 * either because its category is bundle-priced (main/starter/dessert:
 * the real price depends on what else is in the order, see
 * computeFormulaTotal()) or because its exact name isn't in its
 * category's price table. Used to show a real number on a food card
 * instead of the generic "Canteen Price" label wherever one genuinely
 * exists and doesn't depend on the rest of the cart.
 */
export function priceForItem(item) {
  if (SNACK_CATEGORIES.has(item.category)) return SNACK_PRICE;
  for (const [categories, prices] of NAME_PRICED_GROUPS) {
    if (categories.has(item.category) && prices[item.name] !== undefined) {
      return prices[item.name];
    }
  }
  return null;
}

/**
 * lines: [{ category, name, quantity }] -- category/name are
 * Restopolis's raw strings. Returns { formulaCount, mainCount,
 * starterCount, dessertCount, sandwichCount, snackCount,
 * otherItemsCount, total, reason }, same shape (camelCase) and same
 * semantics as the backend's compute_formula_total(): a starter OR a
 * dessert alone (either one) upgrades a main to the middle tier, both
 * together reach the top tier -- otherwise `total` is null and
 * `reason` is "no_main_dish". Mains are paired against
 * starters/desserts greedily (full-tier pairs first, then
 * partial-tier), so an extra main with no side of its own stays at the
 * plain tier instead of being overcharged. Snacks and every
 * name-priced group (sandwiches, viennoiseries, drinks, packaging,
 * etc) price independently (never blocked by an unpriceable meal
 * formula); an unrecognized name is left unpriced, never guessed at.
 */
export function computeFormulaTotal(lines) {
  const mainQty = lines.filter((l) => MAIN_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const starterQty = lines.filter((l) => STARTER_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const dessertQty = lines.filter((l) => DESSERT_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const sandwichQty = lines.filter((l) => SANDWICH_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const snackQty = lines.filter((l) => SNACK_CATEGORIES.has(l.category)).reduce((sum, l) => sum + l.quantity, 0);
  const otherItemsQty = lines
    .filter((l) => OTHER_NAME_PRICED_CATEGORIES.has(l.category))
    .reduce((sum, l) => sum + l.quantity, 0);
  const formulaCount = mainQty + starterQty + dessertQty + sandwichQty + snackQty + otherItemsQty;

  const base = {
    formulaCount,
    mainCount: mainQty,
    starterCount: starterQty,
    dessertCount: dessertQty,
    sandwichCount: sandwichQty,
    snackCount: snackQty,
    otherItemsCount: otherItemsQty,
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
  const namePricedTotal = NAME_PRICED_GROUPS.reduce(
    (sum, [categories, prices]) =>
      sum +
      lines
        .filter((l) => categories.has(l.category) && prices[l.name] !== undefined)
        .reduce((s, l) => s + prices[l.name] * l.quantity, 0),
    0
  );

  const grandTotal = mealTotal + snackTotal + namePricedTotal;
  // Can genuinely be 0 despite formulaCount > 0: e.g. a cart containing
  // ONLY an item whose exact name isn't in its category's price table
  // (no main dish either, so mealTotal is also 0) -- nothing was
  // actually priced, so total must read as "we don't have a price for
  // this" (null), not a misleading €0.00 implying the order is free.
  return { ...base, total: grandTotal > 0 ? Math.round(grandTotal * 100) / 100 : null };
}
