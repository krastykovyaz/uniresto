import { test } from "node:test";
import assert from "node:assert/strict";
import { ALLERGEN_LABELS, CATEGORY_LABELS, LANGUAGES, allergenLabel, categoryLabel, intlLocale, langInfo, t, translations } from "../static/i18n.js";

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

test("exactly the 25 verified real Restopolis categories are covered", () => {
  // See README.md Part 5: confirmed identical across both restaurants'
  // real fixtures. A count check catches an accidental typo'd/duplicate
  // key that Object.keys wouldn't otherwise surface.
  assert.equal(Object.keys(CATEGORY_LABELS).length, 25);
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
  assert.equal(t("en", "customerEmail"), "Email (optional, for a confirmation)");
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
  assert.equal(t("en", "registeredEmail"), "Email");
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

test("intlLocale uses the declared locale, or Luxembourgish's German fallback", () => {
  assert.equal(intlLocale("en"), "en-US");
  // lb-LU where the runtime's Intl data has it; de-LU on runtimes (some
  // Chromium builds) that ship without Luxembourgish.
  assert.ok(["lb-LU", "de-LU"].includes(intlLocale("lb")));
});
