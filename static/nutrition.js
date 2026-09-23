// Approximate calorie estimation -- NOT Restopolis data, and not exact.
// Mirrors orderability_engine/nutrition.py exactly (same table, same
// word-boundary matching, same longest-match tie-break), so the instant
// local preview the UI shows matches what the backend already computed
// and put in the menu API response. See that module's docstring for the
// full rationale, including two real classification bugs (a dairy BRAND
// name "Luxlait" falsely matching "lait"/milk, and "Menthe" falsely
// matching "the"/tea) that word-boundary matching fixed -- this file
// only re-states the table/logic, not the reasoning, to avoid drifting
// out of sync.
//
// Pure, no DOM access -- unit-tested directly under Node
// (tests_js/nutrition.test.mjs), same pattern as pricing.js.

const TABLE = [
  // -- Protein / mains --
  [["quorn", "tofu"], "plant_protein", 140],
  [["boeuf", "bœuf", "steak", "roti de porc", "rôti de porc", "porc", "veau", "agneau",
    "saucisse", "jambon", "salami", "bacon", "chorizo"], "red_meat", 220],
  [["poulet", "dinde", "volaille", "canard", "nuggets", "renuggets"], "poultry", 190],
  [["poisson", "saumon", "thon", "cabillaud", "truite", "merlan", "crevette", "colin"], "fish_seafood", 150],
  [["oeuf", "œuf", "omelette"], "egg", 155],
  // -- Starches --
  [["pomme de terre", "pommes de terre", "frite", "frites", "puree", "purée", "gratin dauphinois"], "potato", 95],
  [["riz", "quinoa", "boulgour", "semoule", "couscous", "polenta"], "grain", 135],
  [["pate", "pâte", "pates", "pâtes", "linguine", "spaghetti", "penne", "lasagne",
    "cannelloni", "nouilles", "gnocchi"], "pasta", 155],
  [["lentille", "pois chiche", "haricot rouge", "haricot blanc"], "legume", 115],
  // -- Bread / bakery (savory) --
  [["sandwich", "wrap", "baguette", "panini", "burger", "hot-dog", "hot dog"], "bread_savory", 250],
  [["poche aux pommes", "chausson aux pommes"], "pastry_sweet", 260],
  [["croissant", "pain au chocolat", "viennoiserie", "brioche", "muffin", "bretzel"], "pastry_savory_sweet", 350],
  // -- Sweets / desserts / ice cream -- listed BEFORE fruit/vegetable
  // below: see orderability_engine/nutrition.py's table comment for why
  // (dish-type keywords like "cornet"/"glace" must win same-length ties
  // against flavor-descriptor words like "fraise"/"vanille").
  [["glace", "cornet", "dame blanche", "esquimau", "cassata"], "ice_cream", 200],
  [["gateau", "gâteau", "tarte", "cookie", "biscuit", "flan", "mousse",
    "brest", "eclair", "éclair", "cheesecake", "brownie", "cheescake",
    "streusel", "paris"], "dessert", 320],
  // -- Vegetables / salads / soups --
  [["salade", "crudites", "crudités", "mezze", "mezzés"], "composed_salad", 90],
  [["soupe", "potage", "bouillon", "veloute", "velouté", "minestrone", "gaspacho"], "soup", 45],
  [["legume", "légume", "carotte", "courgette", "brocoli", "epinard", "épinard",
    "chou", "tomate", "poivron", "aubergine", "champignon", "haricot vert",
    "petit pois", "betterave"], "vegetable", 35],
  [["fruit", "pomme", "banane", "orange", "poire", "fraise", "peche", "pêche",
    "ananas", "raisin"], "fruit", 55],
  // -- Dairy / cheese --
  [["fromage frais", "faisselle"], "fresh_cheese", 90],
  [["fromage", "cheddar", "mozzarella", "emmental", "gruyere", "gruyère", "parmesan"], "cheese", 350],
  [["yaourt", "yogourt"], "dairy", 70],
  // -- Beverages --
  [["eau"], "water", 0],
  [["coca", "soda", "fanta", "sprite", "rosport sunny", "rosport wave"], "soda", 42],
  [["fuze tea", "black tea", "iced tea", "ice tea"], "iced_tea", 40],
  [["limo", "drauwejus", "jus"], "juice", 45],
  [["chocolat chaude", "chocolat chaud", "chocolate"], "hot_chocolate", 70],
  [["cafe", "café", "espresso", "cappuccino"], "hot_beverage_coffee", 5],
  [["the", "thé", "tisane"], "hot_beverage_tea", 1],
  [["lait"], "milk", 60],
];

function normalize(text) {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Returns [foodType, kcalPer100] for the best (longest) whole-word/
 * phrase keyword match in the raw (French) dish name, or null if
 * nothing matched -- never a default/fallback density.
 */
export function classifyFoodType(name) {
  const normalized = normalize(name);

  let best = null; // { foodType, kcalPer100, keyword }
  for (const [keywords, foodType, kcalPer100] of TABLE) {
    for (const kw of keywords) {
      const normalizedKw = normalize(kw);
      const pattern = new RegExp(`\\b${escapeRegExp(normalizedKw)}\\b`);
      if (pattern.test(normalized)) {
        if (best === null || normalizedKw.length > best.keyword.length) {
          best = { foodType, kcalPer100, keyword: normalizedKw };
        }
      }
    }
  }

  return best ? [best.foodType, best.kcalPer100] : null;
}

/**
 * Returns { calories, foodType, isEstimated }, same shape (camelCase)
 * and same semantics as the backend's estimate_calories(): `calories`
 * is null whenever there's no known weight to base an estimate on, or
 * the name doesn't match any known food-type keyword -- never a
 * guessed default.
 */
export function estimateCalories(name, weightValue, weightUnit) {
  if (weightValue == null || weightUnit == null) {
    return { calories: null, foodType: null, isEstimated: false };
  }
  if (weightUnit === "piece") {
    return { calories: null, foodType: null, isEstimated: false };
  }

  const match = classifyFoodType(name);
  if (match === null) {
    return { calories: null, foodType: null, isEstimated: false };
  }

  const [foodType, kcalPer100] = match;
  const gramsOrMl = weightUnit === "l" ? weightValue * 1000 : weightValue;
  const calories = Math.round((kcalPer100 * gramsOrMl) / 100 * 10) / 10;
  return { calories, foodType, isEstimated: true };
}
