// Food search -- pure client-side text matching over the menu the app
// already fetched (same reasoning as filters.js: the whole day's menu
// for one restaurant is already in hand, so search never re-fetches).
//
// Matches against dish name, description, category, AND allergens -- the
// closest thing to an "ingredients" list Restopolis exposes (it has no
// ingredient text at all, only the allergen tags, see
// restopolis/allergens.py). Category and allergens each match both the
// raw Restopolis string AND their current-language translated label
// (categoryLabel()/allergenLabel() from static/i18n.js), so searching
// "starter" in English finds "Entrée" items and searching "milk" finds
// dishes tagged "Lait" without the user having to know the raw French
// wording. Dish names/descriptions themselves are never translated (see
// README.md Part 5) and are matched exactly as Restopolis wrote them, in
// whatever language that is -- searching is text matching, not a second
// translation layer.
//
// Deliberately stays decoupled from static/i18n.js (no import of
// categoryLabel/allergenLabel), matching filters.js's separation: the
// caller computes the translated labels per item and passes them in.
//
// Pure, no DOM access -- unit-tested directly under Node
// (tests_js/search.test.mjs), same pattern as filters.js/pricing.js.

export function normalizeText(text) {
  return (text || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .trim();
}

/**
 * `translatedCategory` is the current-language label for item.category
 * (e.g. categoryLabel(item.category, lang)), or null/undefined if not
 * available. `translatedAllergens` is an array of current-language
 * allergen labels (e.g. item.allergens.map(a => allergenLabel(a, lang))),
 * or null/undefined. An empty query always matches everything.
 */
export function itemMatchesQuery(item, query, translatedCategory, translatedAllergens) {
  const q = normalizeText(query);
  if (!q) return true;
  const fields = [item.name, item.description, item.category, translatedCategory];
  if (fields.some((f) => f && normalizeText(f).includes(q))) return true;
  const allergenNames = [...(item.allergens || []).map((a) => a.name), ...(translatedAllergens || [])];
  return allergenNames.some((f) => f && normalizeText(f).includes(q));
}

/**
 * `getTranslatedCategory` is an optional (rawCategory) => string
 * function. `getTranslatedAllergen` is an optional (allergenEntry) =>
 * string function. Either can be omitted, in which case matching falls
 * back to the raw Restopolis strings only.
 */
export function searchItems(items, query, getTranslatedCategory, getTranslatedAllergen) {
  const q = normalizeText(query);
  if (!q) return items;
  return items.filter((it) =>
    itemMatchesQuery(
      it,
      query,
      getTranslatedCategory ? getTranslatedCategory(it.category) : null,
      getTranslatedAllergen ? (it.allergens || []).map((a) => getTranslatedAllergen(a)) : null
    )
  );
}
