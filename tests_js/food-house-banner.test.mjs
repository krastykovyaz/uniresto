import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { translations, LANGUAGES } from "../static/i18n.js";

const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");

// Run the real helper from app.js, not a copy of it.
const constants = app.match(/const FOOD_HOUSE_SLUG = [^\n]+\nconst FOOD_HOUSE_BANNER_UNTIL = [^\n]+\n/)[0];
const helper = app.match(/function foodHouseBannerVisible\(restaurants, today\) \{[\s\S]*?\n\}\n/)[0];
const visible = new Function(`${constants}\n${helper}\nreturn foodHouseBannerVisible;`)();

const withFoodHouse = [{ slug: "altius" }, { slug: "udl-cbv-fh" }];
const without = [{ slug: "altius" }];

test("the banner shows while Food House is listed, through the last banner day", () => {
  assert.equal(visible(withFoodHouse, "2026-11-01"), true);
  assert.equal(visible(withFoodHouse, "2026-11-08"), true);
});

test("the banner is gone after its last day, and never shows before Food House is listed", () => {
  assert.equal(visible(withFoodHouse, "2026-11-09"), false);
  assert.equal(visible(without, "2026-11-02"), false);
  assert.equal(visible(undefined, "2026-11-02"), false);
});

test("Home draws the banner first, closing is remembered, a tap opens the Belval tab", () => {
  assert.match(app, /const celebration = foodHouseBanner\(\);\n\s+if \(celebration\) app\.append\(celebration\);\n\s+const discount = discountBanner\(\);/);
  assert.match(app, /localStorage\.setItem\(FOOD_HOUSE_BANNER_DISMISSED_KEY, "1"\)/);
  assert.match(app, /state\.restaurantsCampusFilter = "belval";\n\s+goTo\("restaurants"\);/);
});

test("the banner text exists in all 11 languages", () => {
  for (const lang of LANGUAGES) {
    for (const key of ["foodHouseBannerTitle", "foodHouseBannerBody"]) {
      assert.ok(translations[lang.code][key], `${key} missing for ${lang.code}`);
    }
  }
});

test("a registered courier gets the campus choice on the Delivery screen, and a failed save is undone", () => {
  assert.match(app, /const campusRow = DEMO \? null : registeredCourierCampusRow\(\);\n\s+if \(campusRow\) app\.append\(campusRow\);/);
  assert.match(app, /if \(!email \|\| !belvalListed\(\)\) return null;/);
  assert.match(app, /Promise\.resolve\(onPick\(current\)\)\.catch\(\(\) => \{\n\s+current = previous;\n\s+paint\(\);/);
});
