import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ALLERGEN_LABELS, CATEGORY_LABELS, DISH_NAME_LABELS, LANGUAGES, allergenLabel, categoryLabel, dishNameLabel, intlLocale, langInfo, t, translations, dishSize, dishTitle, dishTitleWithSize } from "../static/i18n.js";

test("11 languages are configured: the 10 most-spoken plus Luxembourgish", () => {
  assert.equal(LANGUAGES.length, 11);
  assert.ok(LANGUAGES.some((l) => l.code === "lb"));
});

test("every language has a full translation dictionary with matching keys", () => {
  const englishKeys = Object.keys(translations.en).sort();
  for (const lang of LANGUAGES) {
    const dict = translations[lang.code];
    assert.ok(dict, `missing translations for ${lang.code}`);
    assert.deepEqual(Object.keys(dict).sort(), englishKeys, `key mismatch for ${lang.code}`);
  }
});

test("t() returns the translated string for a known key", () => {
  assert.equal(t("fr", "confirmOrder"), "Confirmer la commande");
  assert.equal(t("ar", "back"), "رجوع");
});

test("t() falls back to English for an unknown language code", () => {
  assert.equal(t("xx", "confirmOrder"), translations.en.confirmOrder);
});

test("t() falls back to the key itself if missing from every dictionary", () => {
  assert.equal(t("en", "thisKeyDoesNotExist"), "thisKeyDoesNotExist");
});

test("t() substitutes {placeholder} variables", () => {
  const result = t("en", "selectItem", { name: "Salad'bar" });
  assert.equal(result, "Select Salad'bar");
});

test("t() does not translate the dish name passed as a variable", () => {
  // The dish name itself must survive untouched even in a non-Latin-script UI.
  const result = t("zh", "selectItem", { name: "Salad'bar" });
  assert.match(result, /Salad'bar/);
});

test("t() singular/plural split picks the right form", () => {
  assert.equal(t("en", "itemCount", { n: 1 }), "1 item");
  assert.equal(t("en", "itemCount", { n: 3 }), "3 items");
  assert.equal(t("es", "itemCount", { n: 1 }), "1 artículo");
  assert.equal(t("es", "itemCount", { n: 3 }), "3 artículos");
});

test("langInfo marks Arabic and Urdu as RTL, English as not", () => {
  assert.equal(langInfo("ar").rtl, true);
  assert.equal(langInfo("ur").rtl, true);
  assert.equal(langInfo("en").rtl, undefined);
});

test("langInfo falls back to English for an unknown code", () => {
  assert.equal(langInfo("zz").code, "en");
});

// ---------------------------------------------------------------------------
// categoryLabel / CATEGORY_LABELS
// ---------------------------------------------------------------------------

test("exactly the 26 known real Restopolis categories are covered", () => {
  // See README.md Part 5: confirmed identical across both restaurants'
  // real fixtures. A count check catches an accidental typo'd/duplicate
  // key that Object.keys wouldn't otherwise surface.
  assert.equal(Object.keys(CATEGORY_LABELS).length, 26);
});

test("every category has a translation in every configured language", () => {
  const langCodes = LANGUAGES.map((l) => l.code).sort();
  for (const [category, dict] of Object.entries(CATEGORY_LABELS)) {
    assert.deepEqual(Object.keys(dict).sort(), langCodes, `incomplete translations for category "${category}"`);
  }
});

test("categoryLabel translates a known category", () => {
  assert.equal(categoryLabel("Végétarien", "en"), "Vegetarian");
  assert.equal(categoryLabel("Végétarien", "zh"), "素食");
});

test("categoryLabel falls back to the raw string for an unknown category", () => {
  assert.equal(categoryLabel("Some Future Category Restopolis Adds", "fr"), "Some Future Category Restopolis Adds");
});

test("categoryLabel in French returns the category unchanged (already French)", () => {
  for (const category of Object.keys(CATEGORY_LABELS)) {
    assert.equal(categoryLabel(category, "fr"), category);
  }
});

// ---------------------------------------------------------------------------
// dishNameLabel / DISH_NAME_LABELS
// ---------------------------------------------------------------------------

test("every covered dish name has a translation in every configured language", () => {
  // Unlike CATEGORY_LABELS/ALLERGEN_LABELS, this is NOT a closed set (the
  // menu rotates daily) -- just checks internal consistency of whatever
  // is covered so far, never completeness against the whole menu.
  const langCodes = LANGUAGES.map((l) => l.code).sort();
  for (const [name, dict] of Object.entries(DISH_NAME_LABELS)) {
    assert.deepEqual(Object.keys(dict).sort(), langCodes, `incomplete translations for dish "${name}"`);
  }
});

test("dishNameLabel translates a known descriptive dish name", () => {
  assert.equal(dishNameLabel("Salade campagnarde", "en"), "Country salad");
  assert.equal(dishNameLabel("Soupe de pommes de terre", "ru"), "Картофельный суп");
});

test("dishNameLabel falls back to the raw name for an unmapped dish", () => {
  assert.equal(dishNameLabel("Some Future Dish Restopolis Adds", "en"), "Some Future Dish Restopolis Adds");
});

test("dishNameLabel in French returns the name unchanged (already French)", () => {
  for (const name of Object.keys(DISH_NAME_LABELS)) {
    assert.equal(dishNameLabel(name, "fr"), name);
  }
});

test("dishNameLabel deliberately leaves real product/brand names untranslated", () => {
  // Same "if it is not strange" judgment call documented on
  // DISH_NAME_LABELS itself -- these read as brand names, not
  // descriptive dish text, so they're simply not in the table at all.
  for (const brandName of ["Rosport Blue 0,50 l btl", "Coca Cola 0,20 l btl", "myBento", "Nutchy"]) {
    assert.equal(dishNameLabel(brandName, "zh"), brandName);
  }
});

// ---------------------------------------------------------------------------
// allergenLabel / ALLERGEN_LABELS
// ---------------------------------------------------------------------------

test("all 14 EU 1169/2011 allergen codes are covered", () => {
  assert.equal(Object.keys(ALLERGEN_LABELS).length, 14);
});

test("every allergen code has a translation in every configured language", () => {
  const langCodes = LANGUAGES.map((l) => l.code).sort();
  for (const [code, dict] of Object.entries(ALLERGEN_LABELS)) {
    assert.deepEqual(Object.keys(dict).sort(), langCodes, `incomplete translations for allergen code ${code}`);
  }
});

test("allergenLabel translates a known code", () => {
  assert.equal(allergenLabel({ code: 7, name: "Lait" }, "en"), "Milk");
  assert.equal(allergenLabel({ code: 7, name: "Lait" }, "ar"), "حليب");
});

test("allergenLabel falls back to Restopolis's own name for an unmapped code", () => {
  assert.equal(allergenLabel({ code: 99, name: "Something New" }, "en"), "Something New");
});

test("allergenLabel falls back to 'code N' when neither a mapping nor a name exists", () => {
  assert.equal(allergenLabel({ code: 99, name: null }, "en"), "code 99");
});

test("allergenLabel never translates the dish-specific detail text", () => {
  // detail (e.g. "Blé, Orge, Épeautre") is intentionally not part of
  // allergenLabel's contract at all -- it's rendered separately, raw,
  // by the caller. This just documents that allergenLabel's return value
  // never includes it.
  const entry = { code: 1, name: "Céréales contenant du gluten", detail: "Blé, Orge, Épeautre" };
  const label = allergenLabel(entry, "en");
  assert.equal(label, "Gluten-containing cereals");
  assert.ok(!label.includes("Blé"));
});

// ---------------------------------------------------------------------------
// Luxembourgish
// ---------------------------------------------------------------------------

test("Luxembourgish UI strings, plurals, categories and allergens resolve", () => {
  assert.equal(t("lb", "confirmOrder"), "Bestellung confirméieren");
  assert.equal(t("lb", "itemCount", { n: 1 }), "1 Artikel");
  assert.equal(t("lb", "itemCount", { n: 3 }), "3 Artikelen");
  assert.equal(categoryLabel("Légumes", "lb"), "Geméis");
  assert.equal(allergenLabel({ code: 7, name: "Lait" }, "lb"), "Mëllech");
  assert.equal(langInfo("lb").rtl, undefined);
});

// ---------------------------------------------------------------------------
// Order-confirmation email (Part 23)
// ---------------------------------------------------------------------------

test("customer-email checkout strings exist for every configured language", () => {
  for (const lang of LANGUAGES) {
    for (const key of ["customerEmail", "customerEmailPlaceholder", "invalidUniLuEmail", "confirmationEmailSent", "confirmationEmailFailed"]) {
      const value = t(lang.code, key);
      assert.ok(value && value !== key, `${lang.code}.${key} should resolve to real text, got ${JSON.stringify(value)}`);
    }
  }
});

test("customer-email strings spot-check in a few languages", () => {
  assert.equal(t("en", "customerEmail"), "Email (required, for a confirmation)");
  assert.equal(t("en", "confirmationEmailSent"), "Confirmation email sent");
  assert.equal(t("lb", "customerEmailPlaceholder"), "du@uni.lu");
  assert.equal(t("ar", "confirmationEmailFailed"), "تعذر إرسال بريد التأكيد");
});

// ---------------------------------------------------------------------------
// Restaurant building labels (Part 24) -- NOT a Restopolis field, see
// RestaurantConfig.building's docstring
// ---------------------------------------------------------------------------

test("building-label strings exist for every configured language", () => {
  for (const lang of LANGUAGES) {
    for (const key of ["buildingMain", "buildingJfk"]) {
      const value = t(lang.code, key);
      assert.ok(value && value !== key, `${lang.code}.${key} should resolve to real text, got ${JSON.stringify(value)}`);
    }
  }
});

test("building-label strings spot-check in a few languages", () => {
  assert.equal(t("en", "buildingMain"), "Main building");
  assert.equal(t("en", "buildingJfk"), "JFK building");
  assert.equal(t("fr", "buildingMain"), "Bâtiment principal");
  assert.equal(t("lb", "buildingJfk"), "JFK-Gebai");
});

// ---------------------------------------------------------------------------
// Registered email (Part 25) -- Profile-only, separate from per-order
// customerEmail (Part 23)
// ---------------------------------------------------------------------------

test("registered-email strings exist for every configured language", () => {
  for (const lang of LANGUAGES) {
    for (const key of ["registeredEmail", "registeredEmailHint", "removeEmail", "notSet", "save"]) {
      const value = t(lang.code, key);
      assert.ok(value && value !== key, `${lang.code}.${key} should resolve to real text, got ${JSON.stringify(value)}`);
    }
  }
});

test("registered-email strings spot-check in a few languages", () => {
  assert.equal(t("en", "registeredEmail"), "University Email");
  assert.equal(t("en", "notSet"), "Not set");
  assert.equal(t("en", "save"), "Save");
  assert.equal(t("ru", "removeEmail"), "Удалить");
});

// ---------------------------------------------------------------------------
// Email verification code (Part 27) + registered phone number (Part 28)
// ---------------------------------------------------------------------------

test("email-verification strings exist for every configured language", () => {
  for (const lang of LANGUAGES) {
    for (const key of [
      "sendCode",
      "sending",
      "verifyEmailTitle",
      "codeSentHint",
      "confirmCode",
      "resendCode",
      "changeEmail",
      "invalidCode",
      "codeExpired",
      "tooManyAttempts",
      "verificationFailed",
      "verificationSendFailed",
      "resendCooldown",
    ]) {
      const value = t(lang.code, key);
      assert.ok(value && value !== key, `${lang.code}.${key} should resolve to real text, got ${JSON.stringify(value)}`);
    }
  }
});

test("email-verification strings spot-check, including the spam-folder hint", () => {
  assert.equal(t("en", "sendCode"), "Send code");
  assert.equal(t("en", "codeSentHint", { email: "x@uni.lu" }), "We sent a 6-digit code to x@uni.lu. It can take a minute to arrive — check your spam or junk folder too.");
  assert.equal(t("fr", "confirmCode"), "Confirmer");
  assert.equal(t("lb", "resendCode"), "Code nach eng Kéier schécken");
});

test("phone-number strings exist for every configured language", () => {
  for (const lang of LANGUAGES) {
    for (const key of ["phoneNumber", "phoneNumberHint", "phoneNumberPlaceholder", "invalidPhoneNumber", "removePhoneNumber"]) {
      const value = t(lang.code, key);
      assert.ok(value && value !== key, `${lang.code}.${key} should resolve to real text, got ${JSON.stringify(value)}`);
    }
  }
});

test("phone-number strings spot-check in a few languages", () => {
  assert.equal(t("en", "phoneNumber"), "Phone number");
  assert.equal(t("es", "removePhoneNumber"), "Eliminar");
  assert.equal(t("ar", "invalidPhoneNumber"), "أدخل رقم هاتف صالح");
});

// ---------------------------------------------------------------------------
// "Canteen Price" label (Part 29) -- replaces a bare €X.XX / "Price not
// available" on food cards, since Restopolis's own real reservation
// flow shows no per-item price either (verified live, screenshots
// compared 2026-09-24)
// ---------------------------------------------------------------------------

test("canteenPrice exists for every configured language", () => {
  for (const lang of LANGUAGES) {
    const value = t(lang.code, "canteenPrice");
    assert.ok(value && value !== "canteenPrice", `${lang.code}.canteenPrice should resolve to real text, got ${JSON.stringify(value)}`);
  }
});

test("canteenPrice spot-check in a few languages", () => {
  assert.equal(t("en", "canteenPrice"), "Canteen Price");
  assert.equal(t("fr", "canteenPrice"), "Prix de la cantine");
  assert.equal(t("lb", "canteenPrice"), "Kantinn-Präis");
});

// ---------------------------------------------------------------------------
// Admin confirmation workflow order statuses + real price (Part 30)
// ---------------------------------------------------------------------------

test("new order-status and real-price strings exist for every configured language", () => {
  for (const lang of LANGUAGES) {
    for (const key of ["statusAwaitingConfirmation", "statusConfirmed", "statusCancelled", "realPrice"]) {
      const value = t(lang.code, key);
      assert.ok(value && value !== key, `${lang.code}.${key} should resolve to real text, got ${JSON.stringify(value)}`);
    }
  }
});

test("order-status and real-price strings spot-check in a few languages", () => {
  assert.equal(t("en", "statusAwaitingConfirmation"), "Awaiting your confirmation");
  assert.equal(t("en", "statusConfirmed"), "Confirmed");
  assert.equal(t("en", "statusCancelled"), "Cancelled");
  assert.equal(t("en", "realPrice"), "Real price");
  assert.equal(t("fr", "statusCancelled"), "Annulée");
});

test("intlLocale uses the declared locale, or Luxembourgish's German fallback", () => {
  assert.equal(intlLocale("en"), "en-US");
  // lb-LU where the runtime's Intl data has it; de-LU on runtimes (some
  // Chromium builds) that ship without Luxembourgish.
  assert.ok(["lb-LU", "de-LU"].includes(intlLocale("lb")));
});


// ---------------------------------------------------------------------------
// Sizes belong in the card body, not in the item's title
// ---------------------------------------------------------------------------

test("dishTitle drops the size and dishSize keeps it, for every shape Restopolis uses", () => {
  const cases = [
    ["Mini salades 150 g", "Mini salades", "150 g"],
    ["Rosport Blue 0,50 l non consigné", "Rosport Blue", "0,50 l non consigné"],
    ["Rosport Blue 1,00 l btl", "Rosport Blue", "1,00 l btl"],
    ["Rosport Wave 0,50 l non-consigné", "Rosport Wave", "0,50 l non-consigné"],
    ["Lët'z kola 0,33 btl", "Lët'z kola", "0,33 btl"],
    ["Ramborn Apple Soda 0,33 l btl", "Ramborn Apple Soda", "0,33 l btl"],
    ["Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)", "Lait Luxlait BIO", "0,25 l Tétra Pack (gratuit)"],
    ["Lait chocolaté Luxlait 0,25 l Tétra Pack", "Lait chocolaté Luxlait", "0,25 l Tétra Pack"],
    ["Consigne ECOBOX (500 ml)", "Consigne ECOBOX", "500 ml"],
    ["Thermo Café 1,50 l", "Thermo Café", "1,50 l"],
    ["Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)", "Cornet Luxlait (Chocolat, Fraise, Vanille)", "130 ml"],
    ["Glace miniature Luxlait 100 ml (Framboise, Praliné, Vanille)", "Glace miniature Luxlait (Framboise, Praliné, Vanille)", "100 ml"],
    ['Mini muesli maison "Douceur d\'automne" 150 g', 'Mini muesli maison "Douceur d\'automne"', "150 g"],
    ["Fuze Tea - Black Tea Pêche/Hibiscus 0,20 l btl", "Fuze Tea - Black Tea Pêche/Hibiscus", "0,20 l btl"],
  ];
  for (const [raw, title, size] of cases) {
    assert.equal(dishTitle(raw, "fr"), title, raw);
    assert.equal(dishSize(raw), size, raw);
  }
});

test("names without a size come back untouched", () => {
  for (const raw of ["Salad'bar", "1/2 Levain jambon cuit", 'Banane "commerce équitable"', "Café \"commerce équitable\"", "Cappuccino", "Dessert du Jour"]) {
    assert.equal(dishTitle(raw, "en"), dishNameLabel(raw, "en"), raw);
    assert.equal(dishSize(raw), null, raw);
  }
});

test("translated names lose their size too, in every script", () => {
  for (const lang of ["en", "zh", "hi", "es", "fr", "ar", "bn", "pt", "ru", "ur", "lb"]) {
    const title = dishTitle("Mini salades 150 g", lang);
    assert.ok(!/[\d\u0660-\u0669\u09E6-\u09EF]/.test(title), `${lang}: ${title}`);
    assert.ok(title.length > 3, `${lang}: ${title}`);
  }
  assert.equal(dishTitle("Mini salades 150 g", "en"), "Mini salads");
  assert.equal(dishTitle("Gobelet comestible 220 ml", "en"), "Edible cup");
});

test("the three Rosport Blue bottles get one title and three different sizes", () => {
  const raws = ["Rosport Blue 0,25 l btl", "Rosport Blue 0,50 l btl", "Rosport Blue 1,00 l btl"];
  assert.deepEqual([...new Set(raws.map((r) => dishTitle(r, "en")))], ["Rosport Blue"]);
  assert.equal(new Set(raws.map((r) => dishSize(r))).size, 3);
});

test("dishTitleWithSize keeps the exact product in one-line summaries", () => {
  assert.equal(dishTitleWithSize("Rosport Blue 0,50 l non consigné", "en"), "Rosport Blue (0,50 l non consigné)");
  assert.equal(dishTitleWithSize("A dish that is not on the menu yet", "en"), "A dish that is not on the menu yet");
  assert.equal(dishTitleWithSize("Salad'bar", "en"), "Salad bar"); // translated, and it has no size to add
});

test("no live menu item title still contains a size", async () => {
  const fs = await import("node:fs");
  const menus = JSON.parse(fs.readFileSync(new URL("../data/menus.json", import.meta.url), "utf-8"));
  const names = new Set();
  (function walk(x) {
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") {
      if (typeof x.name === "string" && "category" in x) names.add(x.name);
      Object.values(x).forEach(walk);
    }
  })(menus);
  assert.ok(names.size > 50);
  for (const raw of names) {
    assert.ok(!/\d[\d.,]*\s*(g|kg|ml|cl|l)\b|\bbtl\b|Tétra|non[ -]consigné/i.test(dishTitle(raw, "fr")), `${raw} -> ${dishTitle(raw, "fr")}`);
  }
});


// ---------------------------------------------------------------------------
// Dish-name translations: every fixed product is covered, in every language
// ---------------------------------------------------------------------------

const ALL_LANGS = ["en", "zh", "hi", "es", "fr", "ar", "bn", "pt", "ru", "ur", "lb"];
const SIZE_RE = /\d[\d.,]*\s*(g|kg|ml|cl|l)\b|\bbtl\b|Tétra|non[ -]consign/i;

// Brands / coined product names that are identical in every language, so they
// have no entry on purpose (mirrors i18n.js's comment above DISH_NAME_LABELS).
const BRAND_ONLY = new Set([
  "Rosport Blue", "Viva", "Coca Cola", "Lët'z kola", "Rosport Pom's", "Rosport Wave",
  "Ramborn Apple & Quince Juice", "Ramborn Apple Juice", "Ramborn Apple Soda", "Ramborn Pear Apple Juice",
  "Nutchy", "Tasty Crunchy", "Crispy Apple", "myBento", "myBowl", "myCan", "myFrupstut", "myKit", "myMiniBowl", "myMug", "myNapkin",
]);

function fixedProductNames() {
  const fs = readFileSync(new URL("../data/menus.json", import.meta.url), "utf-8");
  const names = new Set();
  (function walk(x) {
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") {
      if (typeof x.name === "string" && typeof x.category === "string" && /^\d\d/.test(x.category)) names.add(x.name);
      Object.values(x).forEach(walk);
    }
  })(JSON.parse(fs));
  return [...names];
}

test("every dish-name entry has all 11 languages, and French is the raw name", () => {
  for (const [raw, labels] of Object.entries(DISH_NAME_LABELS)) {
    assert.deepEqual(Object.keys(labels).sort(), [...ALL_LANGS].sort(), raw);
    assert.equal(labels.fr, raw, raw);
    for (const lang of ALL_LANGS) assert.ok(labels[lang] && labels[lang].trim().length > 0, `${raw} [${lang}]`);
  }
});

test("every fixed product on the menu is translated, or is a brand that needs no translation", () => {
  const missing = fixedProductNames().filter((raw) => {
    if (DISH_NAME_LABELS[raw]) return false;
    return !BRAND_ONLY.has(dishTitle(raw, "fr"));
  });
  assert.deepEqual(missing, []);
});

test("a translated title never carries the size, in any language", () => {
  for (const raw of Object.keys(DISH_NAME_LABELS)) {
    if (!SIZE_RE.test(raw)) continue;
    for (const lang of ALL_LANGS) {
      assert.ok(!SIZE_RE.test(dishTitle(raw, lang)), `${raw} [${lang}] -> ${dishTitle(raw, lang)}`);
      assert.ok(dishTitle(raw, lang).length > 2, `${raw} [${lang}]`);
    }
  }
});

test("translated titles read as real words in the user's language", () => {
  assert.equal(dishTitle("Croissant fourré 70 g", "en"), "Filled croissant");
  assert.equal(dishTitle("Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)", "ru"), "Органическое молоко Luxlait");
  assert.equal(dishTitle("Rosport mat Menthe 0,50 l non consigné", "es"), "Rosport con menta");
  assert.equal(dishTitle("Consigne ECOBOX (500 ml)", "fr"), "Consigne ECOBOX");
  assert.equal(dishTitle("Consigne ECOBOX (500 ml)", "ar"), "وديعة ECOBOX");
  assert.equal(dishTitle("Espresso double", "zh"), "双份意式浓缩");
  // a brand-only product keeps its name in every language
  assert.equal(dishTitle("Rosport Blue 0,50 l btl", "zh"), "Rosport Blue");
  assert.equal(dishTitle("Coca Cola 0,20 l btl", "ar"), "Coca Cola");
});

test("the size stays available for the card body even when the title is translated", () => {
  assert.equal(dishSize("Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)"), "0,25 l Tétra Pack (gratuit)");
  assert.equal(dishSize("Consigne ECOBOX (500 ml)"), "500 ml");
});


test("every daily dish in the menu snapshot is translated", () => {
  const menus = JSON.parse(readFileSync(new URL("../data/menus.json", import.meta.url), "utf-8"));
  const names = new Set();
  (function walk(x) {
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") {
      if (typeof x.name === "string" && typeof x.category === "string" && !/^\d\d/.test(x.category)) names.add(x.name);
      Object.values(x).forEach(walk);
    }
  })(menus);
  assert.ok(names.size > 10);
  assert.deepEqual([...names].filter((n) => !DISH_NAME_LABELS[n]), []);
});

test("daily-dish translations are real translations, not copies of the French", () => {
  // Latin-script languages may keep a loanword (Minestrone, Falafel), but the whole
  // name is never left as the French original in a non-Latin script.
  for (const lang of ["zh", "hi", "ar", "bn", "ru", "ur"]) {
    for (const [raw, labels] of Object.entries(DISH_NAME_LABELS)) {
      if (/^[A-Za-z0-9 '"&\/().,-]+$/.test(labels.en) && labels.en === raw) continue; // brand-like names identical everywhere
      assert.notEqual(labels[lang], raw, `${raw} [${lang}]`);
    }
  }
});

test("daily dishes read as real dishes in a few languages", () => {
  assert.equal(dishTitle("Potiron farci aux lentilles et fromage de chèvre", "en"), "Pumpkin stuffed with lentils and goat cheese");
  assert.equal(dishTitle("Potiron farci aux lentilles et fromage de chèvre", "es"), "Calabaza rellena de lentejas y queso de cabra");
  assert.equal(dishTitle("Soupe à l'oignon", "ru"), "Луковый суп");
  assert.equal(dishTitle("Gratin dauphinois", "ar"), "غراتان دوفينوا");
  assert.equal(dishTitle("Salad'bar", "zh"), "沙拉吧");
  assert.equal(dishTitle("Chili sin carne", "hi"), "चिली सिन कार्ने");
});
