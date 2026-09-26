// Food filters (dietary / category / allergens / weight / calories) --
// pure client-side visibility logic over the menu the backend already
// returned (see README.md Part 3/49): filtering never re-fetches or
// re-derives data, it only decides which of the already-trusted items
// to show. Kept in its own pure module (no DOM) for the same reason as
// order-math.js/pricing.js/nutrition.js -- directly unit-testable under
// Node, see tests_js/filters.test.mjs.
//
// Filter OPTIONS (which categories/allergens are even offered) are
// always derived from the real fetched menu (availableCategories/
// availableAllergens below), never a fixed hardcoded list -- so a
// filter chip only ever appears for something actually orderable today.

export function defaultFilters() {
  return {
    categories: [], // raw Restopolis category strings, OR-matched
    dietary: [], // subset of ["vegetarian", "vegan"], OR-matched
    excludedAllergens: [], // allergen codes (numbers) to hide
    weightBucket: "any", // "any" | "under100" | "100to250" | "over250"
    caloriesBucket: "any", // "any" | "under200" | "200to400" | "over400"
  };
}

export const WEIGHT_BUCKETS = ["any", "under100", "100to250", "over250"];
export const CALORIE_BUCKETS = ["any", "under200", "200to400", "over400"];

// How people actually order at the canteen: pick a main dish first,
// then a starter/side, then dessert, and only then browse extras
// (takeaway snacks, sandwiches, pastries, drinks, packaging) -- NOT the
// raw order Restopolis's own HTML happens to list categories in (which
// puts Entrée before the mains). A category not listed here (Restopolis
// adding one this table doesn't know about yet) still shows, just
// trailing after every known one, in whatever order it was first seen
// -- never hidden, same "don't guess, don't hide" rule as
// categoryLabel().
const CATEGORY_DISPLAY_PRIORITY = [
  "Non-végétarien",
  "Végétarien",
  "Végan",
  "Entrée",
  "Féculents",
  "Légumes",
  "Dessert",
  "Snack à emporter",
  "01.1 Sandwiches végétariens",
  "01.2 Sandwiches végans",
  "01.3 Sandwiches non-végétariens",
  "01.4 Sandwiches sans gluten",
  "02. Viennoiseries",
  "03. Gâteaux et cookies maison",
  "04. Vitamines à emporter",
  "05. Laitages",
  "06. Fruits",
  "07. Glaces",
  "08. Pâtisserie",
  "10.1 Boissons froides - Eau minérale et pétillante",
  "10.2 Boissons froides - Jus",
  "10.3 Boissons froides - Sodas",
  "11. Boissons chaudes",
  "12.1 Emballages et articles réutilisables",
  "12.2 Emballages et articles à usage unique",
];
const CATEGORY_PRIORITY_INDEX = new Map(CATEGORY_DISPLAY_PRIORITY.map((category, i) => [category, i]));

// Dedupes to first-seen order, then reorders by CATEGORY_DISPLAY_PRIORITY
// (a stable sort, so anything not in that list keeps its first-seen
// order, trailing after every known category) -- so filter chips and
// the menu below them read in the order people actually order in, not
// however Restopolis's HTML happens to list categories.
export function availableCategories(items) {
  const seen = new Set();
  const order = [];
  for (const it of items) {
    if (!seen.has(it.category)) {
      seen.add(it.category);
      order.push(it.category);
    }
  }
  return order
    .map((category, i) => ({ category, i }))
    .sort((a, b) => {
      const ai = CATEGORY_PRIORITY_INDEX.has(a.category) ? CATEGORY_PRIORITY_INDEX.get(a.category) : Infinity;
      const bi = CATEGORY_PRIORITY_INDEX.has(b.category) ? CATEGORY_PRIORITY_INDEX.get(b.category) : Infinity;
      return ai !== bi ? ai - bi : a.i - b.i;
    })
    .map(({ category }) => category);
}

// [{code, name}], deduplicated by code, sorted by code -- a stable order
// independent of which dish happens to list it first.
export function availableAllergens(items) {
  const byCode = new Map();
  for (const it of items) {
    for (const a of it.allergens || []) {
      if (!byCode.has(a.code)) byCode.set(a.code, { code: a.code, name: a.name });
    }
  }
  return [...byCode.values()].sort((a, b) => a.code - b.code);
}

function weightBucketMatches(bucket, value) {
  if (bucket === "under100") return value < 100;
  if (bucket === "100to250") return value >= 100 && value <= 250;
  if (bucket === "over250") return value > 250;
  return true;
}

function caloriesBucketMatches(bucket, value) {
  if (bucket === "under200") return value < 200;
  if (bucket === "200to400") return value >= 200 && value <= 400;
  if (bucket === "over400") return value > 400;
  return true;
}

/**
 * Returns true if `item` should be shown under `filters`. Every
 * dimension defaults to "show everything" when untouched (empty
 * array / "any" bucket) -- filters only ever narrow, never require
 * data that isn't there. The weight/calories buckets are the one
 * exception: when a specific (non-"any") bucket IS selected, an item
 * with no comparable value in that dimension (wrong/missing weight
 * unit, no calorie estimate) is excluded rather than guessed into a
 * bucket -- see WEIGHT_BUCKETS/CALORIE_BUCKETS' UI notes for why this
 * is surfaced to the user, not just silently done.
 */
export function itemMatchesFilters(item, filters) {
  if (filters.categories.length > 0 && !filters.categories.includes(item.category)) return false;

  if (filters.dietary.length > 0) {
    const okVegan = filters.dietary.includes("vegan") && item.vegan;
    const okVegetarian = filters.dietary.includes("vegetarian") && (item.vegetarian || item.vegan);
    if (!okVegan && !okVegetarian) return false;
  }

  if (filters.excludedAllergens.length > 0) {
    const codes = (item.allergens || []).map((a) => a.code);
    if (filters.excludedAllergens.some((c) => codes.includes(c))) return false;
  }

  if (filters.weightBucket !== "any") {
    if (item.weight_unit !== "g" || item.weight_value == null) return false;
    if (!weightBucketMatches(filters.weightBucket, item.weight_value)) return false;
  }

  if (filters.caloriesBucket !== "any") {
    if (item.calories == null) return false;
    if (!caloriesBucketMatches(filters.caloriesBucket, item.calories)) return false;
  }

  return true;
}

export function filterItems(items, filters) {
  return items.filter((it) => itemMatchesFilters(it, filters));
}

export function activeFilterCount(filters) {
  let count = filters.categories.length + filters.dietary.length + filters.excludedAllergens.length;
  if (filters.weightBucket !== "any") count += 1;
  if (filters.caloriesBucket !== "any") count += 1;
  return count;
}
