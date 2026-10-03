import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// The courier-screen texts (HISTORY_STRINGS) live in static/app.js, outside
// i18n.js, so the i18n parity tests never saw them -- hi, ar, bn and ur once
// fell back to English for Online/Offline and friends. app.js can't be
// imported without a DOM, so read the table as text and evaluate the literal.
const js = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const start = js.indexOf("const HISTORY_STRINGS = ");
const end = js.indexOf("\n};\n", start);
const HISTORY_STRINGS = Function(`return ${js.slice(start + "const HISTORY_STRINGS = ".length, end + 2)}`)();
const LANGS = ["en", "zh", "hi", "es", "fr", "ar", "bn", "pt", "ru", "ur", "lb"];

test("the courier texts exist in all 11 languages", () => {
  assert.deepEqual(Object.keys(HISTORY_STRINGS).sort(), [...LANGS].sort());
});

for (const lang of LANGS) {
  test(`every courier text is translated in ${lang}`, () => {
    for (const key of Object.keys(HISTORY_STRINGS.en)) {
      const value = HISTORY_STRINGS[lang][key];
      assert.ok(typeof value === "string" && value.trim(), `${lang} is missing ${key}`);
      if (lang !== "en" && /\{n\}/.test(HISTORY_STRINGS.en[key])) assert.match(value, /\{n\}/, `${lang}.${key} lost {n}`);
    }
  });
}
