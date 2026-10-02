// The card title is just the dish; what the name says after a comma, after a
// spaced dash, or in brackets moves to the card body (dishNameParts).
import assert from "node:assert/strict";
import { dishNameParts } from "../static/i18n.js";

const cases = [
  // brackets, wherever they are
  ["Glace (chocolat, fraise, vanille, praliné, moka-vanille)", "fr", "Glace", "chocolat, fraise, vanille, praliné, moka-vanille"],
  ["Wrap (from the 2nd napkin)", "en", "Wrap", "from the 2nd napkin"],
  // after the first comma (fr keeps the source wording)
  ["Poulet, sauce aux cacahuètes", "fr", "Poulet", "sauce aux cacahuètes"],
  // after a spaced dash
  ["Thé glacé - Black Tea Peach/Hibiscus", "fr", "Thé glacé", "Black Tea Peach/Hibiscus"],
  ["Thé glacé – Black Tea Peach/Hibiscus", "fr", "Thé glacé", "Black Tea Peach/Hibiscus"],
  // all three together: text after the comma first, then the brackets
  ["Poulet, sauce (piquante)", "fr", "Poulet", "sauce, piquante"],
  // a size is taken out first (it has its own line), then the rest is split
  ["Cornet Luxlait 130 ml (Chocolat, Vanille)", "fr", "Cornet Luxlait", "Chocolat, Vanille"],
  // translated names are split in the language they are shown in
  ["Yaourt grec fouetté, compotée d'oranges", "en", "Whipped Greek yoghurt", "orange compote"],
  // things that must NOT split
  ["Glace moka-vanille", "fr", "Glace moka-vanille", ""], // hyphen inside a word
  ["Ratio 1,5 pour 2", "fr", "Ratio 1,5 pour 2", ""], // decimal comma
  ["Pain complet", "fr", "Pain complet", ""], // nothing to split
  ["(Boisson)", "fr", "(Boisson)", ""], // would leave an empty title
];

for (const [raw, lang, title, details] of cases) {
  const parts = dishNameParts(raw, lang);
  assert.deepEqual(parts, { title, details }, `${raw} [${lang}] -> ${JSON.stringify(parts)}`);
}

console.log(`dish_name_parts: ${cases.length} cases ok`);
