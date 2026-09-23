// UniResto mobile ordering UI (Task 3). Talks ONLY to our own backend's
// JSON API (never Restopolis directly, see README.md Part 3 §21). All
// menu/price/weight/availability data comes from the API responses --
// nothing here invents a dish, price, or weight.

import { clampQuantity, computeOrderTotals } from "./order-math.js";
import {
  DESSERT_CATEGORIES,
  INCLUDED_SIDE_CATEGORIES,
  MAIN_CATEGORIES,
  STARTER_CATEGORIES,
  computeFormulaTotal,
} from "./pricing.js";
import { LANGUAGES, allergenLabel, categoryLabel, getLanguage, intlLocale, langInfo, setLanguage, t } from "./i18n.js";
import {
  CALORIE_BUCKETS,
  WEIGHT_BUCKETS,
  activeFilterCount,
  availableAllergens,
  availableCategories as availableFilterCategories,
  defaultFilters,
  filterItems,
} from "./filters.js";
import { searchItems } from "./search.js";

const app = document.getElementById("app");
const toastEl = document.getElementById("toast");
const bottomNav = document.getElementById("bottom-nav");
const deviceScreen = document.getElementById("device-screen");
const scroller = document.getElementById("scroller");

// Must match the "Device frame" media query in app.css. When it matches,
// the app is drawn inside a foldable-phone frame whose screen (#scroller)
// scrolls on its own; otherwise (phones) the page itself scrolls.
const FRAMED = window.matchMedia("(min-width: 1024px)");

function scrollToTop() {
  window.scrollTo(0, 0);
  scroller.scrollTop = 0;
}

function onScroll(handler) {
  window.addEventListener("scroll", handler, { passive: true });
  scroller.addEventListener("scroll", handler, { passive: true });
}

function offScroll(handler) {
  window.removeEventListener("scroll", handler);
  scroller.removeEventListener("scroll", handler);
}

// Declared here (not next to loadFavorites()/saveFavorites() further
// down) because state.favorites below calls loadFavorites() eagerly,
// synchronously, as part of constructing `state` itself -- a `const`
// declared later in the file would still be in its temporal-dead-zone
// at that point. See loadFavorites()'s own comment for the real bug
// this ordering caused before it was moved here.
const FAVORITES_STORAGE_KEY = "uniresto.favorites.v1";

const state = {
  screen: "restaurants",
  lang: getLanguage(),
  restaurants: [],
  slug: null,
  restaurantName: null,
  availableDates: [], // [OrderabilityResult api_dict]
  targetDate: null,
  dateInfo: null, // the selected date's OrderabilityResult api_dict
  menu: null, // { items, service_time, max_quantity, restaurant }
  menuError: null, // { status, reason } when menu fetch was refused
  filters: defaultFilters(),
  filterSheetOpen: false,
  searchQuery: "",
  selection: [], // [{ menuItemId, quantity }]
  deliveryLocation: "",
  // Optional -- only sent if filled in, so the confirmed order can be
  // emailed (Part 23). Never persisted anywhere (no account system,
  // see saveCart()'s docstring); reset like deliveryLocation is, i.e.
  // it isn't -- both simply carry over across browsing within one
  // session, same existing pattern.
  customerEmail: "",
  confirmedOrder: null,
  serverQuote: null,
  favorites: loadFavorites(), // [{ slug, restaurantName, category, name }]
  favoritesData: {}, // slug -> { status: OrderabilityResult|null, menuByKey: Map|null }
  favoritesLoading: false,
  // Deliberately NOT loaded eagerly here (unlike favorites above) --
  // there's no persistent badge that needs it on first paint, so it's
  // loaded lazily inside openOrderHistory() instead. Keeps this state
  // object free of any call that could repeat the exact same
  // temporal-dead-zone hazard documented on FAVORITES_STORAGE_KEY above.
  orderHistoryOrders: [],
  orderHistoryLoading: false,
  smartLunchForm: null, // built lazily by openSmartLunch()
  smartLunchResult: null, // the POST /api/smart-lunch response, or null before searching
  smartLunchLoading: false,
};

// Shorthand bound to the current language, used throughout the render
// functions below. Only ever applied to OUR OWN UI chrome (labels,
// buttons, empty states) -- Restopolis data (dish names, categories,
// allergen names, service times) is always rendered exactly as the API
// returned it, in whatever language Restopolis itself used, regardless
// of this selector. See README.md Part 4.
function tr(key, vars) {
  return t(state.lang, key, vars);
}

function menuById() {
  const map = new Map();
  if (state.menu) for (const it of state.menu.items) map.set(it.id, it);
  return map;
}

// -------------------------------------------------------------- Cart storage
//
// Persists the in-progress cart to localStorage purely as a same-session
// safety net (there's no auth/account system to persist it server-side
// against, see README.md Part 6 §41-style client/server split).
// Deliberately keyed by (category, name) rather than the raw menu item
// `id`: menu_service.flatten_menu_items()'s own docstring states ids are
// "stable within one response" only -- the backend re-derives them
// fresh from the live menu on every fetch, so a later fetch could hand
// out a different id for the same dish, or (worse) reuse an old id for
// a DIFFERENT dish.
//
// The app never auto-restores this into the "Your order" screen on
// launch, by design -- opening the app always lands on the restaurant
// list (see README.md Part 21), never mid-cart from a previous visit.
const CART_STORAGE_KEY = "uniresto.cart.v1";

function cartItemKey(item) {
  return `${item.category}||${item.name}`;
}

function saveCart() {
  try {
    if (!state.slug || !state.targetDate || state.selection.length === 0 || !state.menu) {
      localStorage.removeItem(CART_STORAGE_KEY);
      return;
    }
    const byId = menuById();
    const items = state.selection
      .map((s) => {
        const item = byId.get(s.menuItemId);
        return item ? { key: cartItemKey(item), quantity: s.quantity } : null;
      })
      .filter(Boolean);
    if (items.length === 0) {
      localStorage.removeItem(CART_STORAGE_KEY);
      return;
    }
    localStorage.setItem(
      CART_STORAGE_KEY,
      JSON.stringify({ slug: state.slug, date: state.targetDate, deliveryLocation: state.deliveryLocation, items })
    );
  } catch {
    /* localStorage unavailable (private mode, quota, ...) -- cart just won't persist */
  }
}

function clearSavedCart() {
  try {
    localStorage.removeItem(CART_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

// --------------------------------------------------------- Favorites storage
//
// Same localStorage-only approach as the cart (Part 46) for the same
// reason: no auth/account system to persist favorites against server-side.
// "Designed so it can later move to backend" means exactly this shape --
// a flat list the UI reads/writes through loadFavorites()/saveFavorites()
// only, never touched directly elsewhere -- swapping those two functions
// for real API calls later wouldn't require changing any caller.
//
// Keyed by (slug, category, name) -- one step broader than the cart's
// (category, name) key (see cartItemKey's docstring) since favorites
// span BOTH restaurants, not just the one currently being browsed.
// FAVORITES_STORAGE_KEY itself is declared up top with the other
// top-level consts, not here -- loadFavorites() runs synchronously
// inside the `state` object literal below (state.favorites), which
// executes before this point in the file; a `const` declared here would
// still be in its temporal-dead-zone at that call time, throwing a
// ReferenceError that loadFavorites()'s own defensive catch{} would
// silently swallow, coming back as [] even with real data saved -- a
// real bug this caught (via a live "does the count badge survive a
// refresh" check, not a unit test, since it's a load-order issue that
// only shows up when this module actually initializes top-to-bottom).

function favoriteKey(slug, category, name) {
  return `${slug}||${category}||${name}`;
}

function loadFavorites() {
  try {
    const raw = localStorage.getItem(FAVORITES_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveFavorites() {
  try {
    localStorage.setItem(FAVORITES_STORAGE_KEY, JSON.stringify(state.favorites));
  } catch {
    /* localStorage unavailable (private mode, quota, ...) -- favorites just won't persist */
  }
}

function isFavorite(slug, category, name) {
  const key = favoriteKey(slug, category, name);
  return state.favorites.some((f) => favoriteKey(f.slug, f.category, f.name) === key);
}

function toggleFavorite(slug, restaurantName, category, name) {
  const key = favoriteKey(slug, category, name);
  if (state.favorites.some((f) => favoriteKey(f.slug, f.category, f.name) === key)) {
    state.favorites = state.favorites.filter((f) => favoriteKey(f.slug, f.category, f.name) !== key);
  } else {
    state.favorites.push({ slug, restaurantName, category, name });
  }
  saveFavorites();
  renderBottomNav(); // keeps the tab bar's favorites-count badge in sync
}

// ----------------------------------------------------- Order history storage
//
// Same localStorage-only shape as Cart/Favorites (Parts 46/49), for the
// same reason -- but stores only order IDS, not order content: the
// backend (GET /api/orders/<id>, Part 50) is re-fetched for the full,
// current record every time the History screen opens, so there's
// nothing here that could ever go stale the way a cached price/weight
// would.
const ORDER_HISTORY_STORAGE_KEY = "uniresto.orderHistory.v1";

function loadOrderHistoryIds() {
  try {
    const raw = localStorage.getItem(ORDER_HISTORY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((id) => Number.isInteger(id)) : [];
  } catch {
    return [];
  }
}

function addToOrderHistory(orderId) {
  try {
    const ids = loadOrderHistoryIds();
    if (!ids.includes(orderId)) ids.push(orderId);
    localStorage.setItem(ORDER_HISTORY_STORAGE_KEY, JSON.stringify(ids));
  } catch {
    /* localStorage unavailable -- this order just won't show up in history later */
  }
}

// ------------------------------------------------------------------ API

async function api(path, options) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try {
    body = await resp.json();
  } catch {
    /* no body */
  }
  if (!resp.ok) {
    const error = new Error((body && (body.message || body.reason || body.error)) || `Request failed (${resp.status})`);
    error.status = resp.status;
    error.body = body;
    throw error;
  }
  return body;
}

function showToast(message) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    toastEl.hidden = true;
  }, 2500);
}

// -------------------------------------------------------------- Helpers

// Date/weekday/month names are localized via Intl.DateTimeFormat rather
// than hand-maintained name arrays per language: it's the browser's own
// correctly-localized (and RTL-aware, for ar/ur) formatting, so there's
// no risk of a mistranslated day/month name sitting next to the rest of
// the UI text.
function currentLocale() {
  return intlLocale(state.lang);
}

function parseISODate(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function fmtShort(dateStr) {
  const d = parseISODate(dateStr);
  const dow = new Intl.DateTimeFormat(currentLocale(), { weekday: "short" }).format(d).toUpperCase();
  const dom = new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short" }).format(d);
  return { dow, dom };
}

function fmtLong(dateStr) {
  const d = parseISODate(dateStr);
  return new Intl.DateTimeFormat(currentLocale(), { weekday: "long", day: "numeric", month: "long" }).format(d);
}

function fmtDeadline(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  const datePart = new Intl.DateTimeFormat(currentLocale(), { weekday: "short", day: "numeric", month: "short" }).format(d);
  const timePart = new Intl.DateTimeFormat(currentLocale(), { hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
  return `${datePart} · ${timePart}`;
}

// Mirrors order-math.js's formatPriceSummary, but reads the backend's
// snake_case totals shape (order.totals from GET/POST /api/orders)
// instead of the frontend's local preview shape.
// Same idea as priceBreakdown() (defined further down, for the live
// client-side preview), but reading the backend's snake_case order
// shape (order.items / order.totals.formula from GET/POST /api/orders)
// -- this is the AUTHORITATIVE total, already computed server-side by
// orderability_engine/pricing.py, not recomputed here; this only
// separates "formula-covered" line items from any others (e.g. Constant
// Products) for display.
function serverPriceBreakdown(order) {
  const otherItems = order.items.filter(
    (it) =>
      !MAIN_CATEGORIES.has(it.category) &&
      !STARTER_CATEGORIES.has(it.category) &&
      !DESSERT_CATEGORIES.has(it.category) &&
      !INCLUDED_SIDE_CATEGORIES.has(it.category)
  );
  const otherKnownTotal = otherItems.filter((it) => it.line_price != null).reduce((sum, it) => sum + it.line_price, 0);
  const otherUnknownPortions = otherItems.filter((it) => it.line_price == null).reduce((sum, it) => sum + it.quantity, 0);
  return {
    formula: order.totals.formula,
    otherKnownTotal: Math.round(otherKnownTotal * 100) / 100,
    otherUnknownPortions,
  };
}

function formatServerPriceTotal(order) {
  const { formula, otherKnownTotal, otherUnknownPortions } = serverPriceBreakdown(order);
  const parts = [];
  if (formula.total != null) parts.push(`€${formula.total.toFixed(2)}`);
  else {
    const reasonText = formulaReasonText(formula);
    if (reasonText) parts.push(reasonText);
  }
  if (otherKnownTotal > 0) parts.push(`€${otherKnownTotal.toFixed(2)}`);
  if (otherUnknownPortions > 0) parts.push(`${otherUnknownPortions} ${tr("unpriced")}`);
  return parts.length ? parts.join(" + ") : tr("priceNotAvailable");
}

// order-math.js's own formatWeightSummary/formatPriceSummary are
// language-neutral on purpose (it's a pure module shared with the Node
// test suite, see tests_js/order-math.test.mjs) -- these two mirror the
// same logic using the current UI language for display, without adding
// an i18n dependency to that shared module.
function localizedWeightSummary(totals) {
  if (totals.itemCount === 0) return tr("noItemsSelected");
  const parts = Object.entries(totals.weightByUnit)
    .filter(([, v]) => v > 0)
    .map(([unit, v]) => `${v} ${unit}`);
  if (totals.unknownWeightPortions > 0) parts.push(`${totals.unknownWeightPortions} ${tr("statusUnknown").toLowerCase()}`);
  return parts.length ? parts.join(" + ") : tr("portionSizeNotSpecified");
}

// Combines OUR OWN meal-formula price (static/pricing.js -- covers a
// main dish + optional starter/dessert, Féculents/Légumes bundled free)
// with any per-dish Restopolis price for whatever's left over (Constant
// Products/snacks -- always null in practice today, but computed for
// real in case that ever changes). Never sums the two into one
// misleading "per-dish" number: the formula price is a property of the
// whole meal, not of any single line.
function priceBreakdown(totals) {
  const formula = computeFormulaTotal(totals.lines.map((l) => ({ category: l.category, quantity: l.quantity })));

  const otherLines = totals.lines.filter(
    (l) =>
      !MAIN_CATEGORIES.has(l.category) &&
      !STARTER_CATEGORIES.has(l.category) &&
      !DESSERT_CATEGORIES.has(l.category) &&
      !INCLUDED_SIDE_CATEGORIES.has(l.category)
  );
  const otherKnownTotal = otherLines.filter((l) => l.lineTotal != null).reduce((sum, l) => sum + l.lineTotal, 0);
  const otherUnknownPortions = otherLines.filter((l) => l.lineTotal == null).reduce((sum, l) => sum + l.quantity, 0);

  return { formula, otherKnownTotal: Math.round(otherKnownTotal * 100) / 100, otherUnknownPortions };
}

function formulaReasonText(formula) {
  if (!formula.reason) return null;
  return tr(formula.reason === "no_main_dish" ? "formulaReasonNoMainDish" : "formulaReasonDessertWithoutStarter");
}

function localizedPriceSummary(totals) {
  if (totals.itemCount === 0) return tr("noItemsSelected");
  const { formula, otherKnownTotal, otherUnknownPortions } = priceBreakdown(totals);

  const parts = [];
  if (formula.total != null) parts.push(`€${formula.total.toFixed(2)}`);
  else {
    const reasonText = formulaReasonText(formula);
    if (reasonText) parts.push(reasonText);
  }
  if (otherKnownTotal > 0) parts.push(`€${otherKnownTotal.toFixed(2)}`);
  if (otherUnknownPortions > 0) parts.push(`${otherUnknownPortions} ${tr("unpriced")}`);

  return parts.length ? parts.join(" + ") : tr("priceNotAvailable");
}

// Mirrors app.py's ALLOWED_EMAIL_DOMAINS/_is_allowed_customer_email
// exactly -- the server is still the actual authority (this only exists
// so a bad address is caught with a clear, translated message before a
// round trip, instead of Flask's generic HTML-only abort() response,
// which the frontend can't extract a specific reason string from; see
// README.md Part 23).
const ALLOWED_EMAIL_DOMAINS = ["@uni.lu", "@student.uni.lu"];

function isAllowedUniLuEmail(email) {
  const normalized = email.trim().toLowerCase();
  if ((normalized.match(/@/g) || []).length !== 1 || normalized.startsWith("@")) return false;
  return ALLOWED_EMAIL_DOMAINS.some((d) => normalized.endsWith(d));
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function escapeHtml(s) {
  return (s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ------------------------------------------------------------------ Icons
//
// A small inline-SVG icon set (line-icon style, matching the visual
// reference this app's screens were redesigned against) replacing the
// emoji/Unicode glyphs used earlier in this project. currentColor-based
// so CSS controls tint; RTL mirroring (e.g. the back chevron) is done in
// CSS via a transform, not by swapping paths, so this stays a single
// source of truth regardless of direction.
const ICON_PATHS = {
  back: '<path d="M15 18l-6-6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
  close: '<path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>',
  heart: '<path d="M12 21s-7.5-4.6-10-9.1C.5 8.4 2 4.8 5.6 4.1c2-.4 3.9.5 5 2.1a5.9 5.9 0 0 1 1.4-1.6c1.6-1.3 4-1.5 5.7-.5 2.8 1.6 3.4 5.3 1.3 8.8C19 16.4 12 21 12 21z" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linejoin="round"/>',
  heartFilled: '<path d="M12 21s-7.5-4.6-10-9.1C.5 8.4 2 4.8 5.6 4.1c2-.4 3.9.5 5 2.1a5.9 5.9 0 0 1 1.4-1.6c1.6-1.3 4-1.5 5.7-.5 2.8 1.6 3.4 5.3 1.3 8.8C19 16.4 12 21 12 21z" fill="currentColor"/>',
  plus: '<path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
  minus: '<path d="M5 12h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
  search: '<circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2" fill="none"/><path d="M21 21l-4.3-4.3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  sparkle: '<path d="M12 2l1.8 5.4L19 9l-5.2 1.8L12 16l-1.8-5.2L5 9l5.2-1.6L12 2z" fill="currentColor"/>',
  clock: '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" fill="none"/><path d="M12 7v5l3.5 2" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>',
  home: '<path d="M4 11.5L12 4l8 7.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/><path d="M6 10v9a1 1 0 0 0 1 1h3v-5h4v5h3a1 1 0 0 0 1-1v-9" stroke="currentColor" stroke-width="2" stroke-linejoin="round" fill="none"/>',
  receipt: '<path d="M6 3h12v18l-2-1.3L14 21l-2-1.3L10 21l-2-1.3L6 21V3z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" fill="none"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  user: '<circle cx="12" cy="8" r="3.6" stroke="currentColor" stroke-width="1.8" fill="none"/><path d="M4.5 20c1.4-3.7 4.4-5.6 7.5-5.6s6.1 1.9 7.5 5.6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none"/>',
  warn: '<path d="M12 3l10 18H2L12 3z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" fill="none"/><path d="M12 10v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="17" r="1" fill="currentColor"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.8" fill="none"/><path d="M3 9h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  plate: '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" fill="none"/><circle cx="12" cy="12" r="4.5" stroke="currentColor" stroke-width="1.4" fill="none"/>',
  ban: '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" fill="none"/><path d="M6 6l12 12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  cart: '<circle cx="9" cy="20" r="1.3" fill="currentColor"/><circle cx="17" cy="20" r="1.3" fill="currentColor"/><path d="M3 4h2l2.2 11.2a2 2 0 0 0 2 1.6h7.6a2 2 0 0 0 2-1.6L21 8H6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
  fork: '<path d="M7 2v8a2 2 0 0 0 4 0V2M9 10v12M17 2c-1.5 0-2.5 1.5-2.5 4s1 4 1 5v11" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
  info: '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" fill="none"/><path d="M12 11v5.5M12 8v.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  globe: '<circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.8" fill="none"/><path d="M3 12h18M12 3c2.4 2.6 3.7 5.6 3.7 9s-1.3 6.4-3.7 9c-2.4-2.6-3.7-5.6-3.7-9S9.6 5.6 12 3z" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linejoin="round"/>',
  chevron: '<path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
};

function icon(name, size = 24) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${ICON_PATHS[name] || ""}</svg>`;
}

// --------------------------------------------------------------- Language

// The desktop frame's fake status bar (hidden on real phones, which have
// their own) shows the real local time rather than a canned "9:41".
function tickStatusClock() {
  const el = document.getElementById("sb-time");
  if (!el) return;
  el.textContent = new Intl.DateTimeFormat(currentLocale(), { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
}

// Applies the current language to page-level chrome that no single screen
// render owns: <html lang/dir> (RTL for Arabic/Urdu) and the desktop
// frame's status-bar clock. The picker itself lives only on the Profile
// screen -- see openLanguageSheet().
function applyLanguage() {
  const info = langInfo(state.lang);
  document.documentElement.lang = info.locale;
  document.documentElement.dir = info.rtl ? "rtl" : "ltr";
  tickStatusClock();
}

function changeLanguage(code) {
  state.lang = code;
  setLanguage(code);
  applyLanguage();
  render();
}

// A language's name written in the CURRENT UI language (e.g.
// "Luxembourgish" while the UI is in English), shown under each option's
// own native name. Comes from the browser's Intl.DisplayNames; if that's
// unavailable the line is simply left out rather than guessed.
function languageNameInUi(code) {
  try {
    const name = new Intl.DisplayNames([currentLocale()], { type: "language" }).of(code);
    return name && name.toLowerCase() !== code ? name : null;
  } catch {
    return null;
  }
}

// Bottom sheet listing every language by its own native name, with a
// checkmark on the active one. Appended to the device screen (not #app)
// so it overlays the whole screen inside the desktop frame too, like the
// Filters sheet.
function openLanguageSheet(trigger) {
  const overlay = el(`<div class="sheet-overlay"></div>`);
  const sheet = el(`
    <div class="lang-sheet" role="dialog" aria-modal="true" aria-label="${escapeHtml(tr("language"))}">
      <div class="sheet-grabber" aria-hidden="true"></div>
      <div class="lang-sheet-header">
        <p class="screen-title">${escapeHtml(tr("language"))}</p>
        <button type="button" class="filter-close" aria-label="${escapeHtml(tr("back"))}">${icon("close", 20)}</button>
      </div>
      <div class="lang-list" role="radiogroup" aria-label="${escapeHtml(tr("language"))}"></div>
    </div>
  `);
  const list = sheet.querySelector(".lang-list");

  for (const lang of LANGUAGES) {
    const isActive = lang.code === state.lang;
    const inUi = languageNameInUi(lang.code);
    const option = el(`
      <button type="button" class="lang-option ${isActive ? "is-active" : ""}" role="radio" aria-checked="${isActive}" data-code="${lang.code}">
        <span class="lang-badge">${escapeHtml(lang.code.toUpperCase())}</span>
        <span class="lang-names">
          <span class="lang-native" lang="${lang.locale}" dir="${lang.rtl ? "rtl" : "ltr"}">${escapeHtml(lang.label)}</span>
          ${inUi && inUi !== lang.label ? `<span class="lang-in-ui">${escapeHtml(inUi)}</span>` : ""}
        </span>
        <span class="lang-check">${isActive ? icon("check", 18) : ""}</span>
      </button>
    `);
    option.addEventListener("click", () => {
      close();
      if (lang.code !== state.lang) changeLanguage(lang.code);
      document.querySelector(".profile-row-lang")?.focus();
    });
    list.append(option);
  }

  function close() {
    document.removeEventListener("keydown", onKey);
    overlay.remove();
  }

  function onKey(e) {
    if (e.key === "Escape") {
      close();
      trigger?.focus();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const options = [...list.querySelectorAll(".lang-option")];
    const i = options.indexOf(document.activeElement);
    const next = e.key === "ArrowDown" ? Math.min(i + 1, options.length - 1) : Math.max(i - 1, 0);
    options[next].focus();
  }

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) {
      close();
      trigger?.focus();
    }
  });
  sheet.querySelector(".filter-close").addEventListener("click", () => {
    close();
    trigger?.focus();
  });
  document.addEventListener("keydown", onKey);

  overlay.append(sheet);
  deviceScreen.append(overlay);
  (list.querySelector(".is-active") || list.firstElementChild).focus();
}

// Root-level tab destinations, matching the reference design's bottom
// tab bar. A "drill-down" screen (a restaurant's menu, the cart, Smart
// Lunch's form) is NOT in this set and hides the bar in favor of its own
// screen-header back button -- the same pattern the reference itself
// uses (its Menu/Filters/Item-detail/Cart/Smart-Lunch mockups don't show
// the tab bar either).
const BOTTOM_NAV_TABS = [
  { screen: "restaurants", labelKey: "home", iconName: "home", go: () => goTo("restaurants") },
  { screen: "favorites", labelKey: "favorites", iconName: "heart", go: () => openFavorites() },
  { screen: "order-history", labelKey: "orderHistory", iconName: "receipt", go: () => openOrderHistory() },
  { screen: "profile", labelKey: "profile", iconName: "user", go: () => goTo("profile") },
];

function renderBottomNav() {
  bottomNav.innerHTML = "";
  if (!BOTTOM_NAV_TABS.some((t) => t.screen === state.screen)) return;

  for (const tab of BOTTOM_NAV_TABS) {
    const isActive = state.screen === tab.screen;
    const btn = el(`
      <button type="button" class="nav-tab ${isActive ? "is-active" : ""}" aria-label="${escapeHtml(tr(tab.labelKey))}" aria-current="${isActive}">
        ${icon(tab.iconName, 22)}
        ${tab.screen === "favorites" && state.favorites.length > 0 ? `<span class="nav-tab-badge">${state.favorites.length}</span>` : ""}
        <span class="nav-tab-label">${escapeHtml(tr(tab.labelKey))}</span>
      </button>
    `);
    btn.addEventListener("click", tab.go);
    bottomNav.append(btn);
  }
}

// ---------------------------------------------------------------- Nav

function goTo(screen) {
  state.screen = screen;
  render();
  scrollToTop();
}

// ---------------------------------------------------------- Screen: restaurants

// The restaurant list itself no longer fetches or shows "today"
// availability -- a restaurant stays fully reachable here regardless of
// what today looks like. Real per-day availability (closed / no menu yet
// / ordering window over / etc, each with its own honest reason) is the
// date picker's job (renderDates()), which the user reaches right after
// tapping a restaurant -- see selectDate()'s "every day stays tappable"
// comment for the same principle applied one screen deeper.
async function loadRestaurants() {
  state.restaurants = await api("/api/restaurants");
}

function renderRestaurants() {
  app.innerHTML = "";
  app.append(el(`<p class="eyebrow" style="padding-top:28px">${escapeHtml(tr("tagline"))}</p>`));
  app.append(el(`<h1 class="large-title">${escapeHtml(tr("whereToEat"))}</h1>`));

  const grid = el(`<div class="restaurant-grid"></div>`);
  for (const r of state.restaurants) {
    const card = el(`
      <button class="restaurant-card" aria-label="${tr("select")}: ${escapeHtml(r.name)}">
        <div class="restaurant-card-main">
          <div class="icon-avatar is-other">${icon("fork", 20)}</div>
          <div>
            <h2>${escapeHtml(shortName(r.name))}</h2>
            <p class="kind">${escapeHtml(tr("universityRestaurant"))}</p>
          </div>
        </div>
      </button>
    `);
    card.addEventListener("click", () => selectRestaurant(r));
    grid.append(card);
  }
  app.append(grid);
}

function shortName(fullName) {
  // "UDL-CKB - Altius - Restaurant" -> "Altius" (Restopolis's own name,
  // never translated -- only split for a shorter title).
  const parts = fullName.split(" - ");
  return parts.length >= 2 ? parts[1] : fullName;
}

const DATE_PICKER_DAYS = 10;

async function selectRestaurant(restaurant) {
  state.slug = restaurant.slug;
  state.restaurantName = restaurant.name;
  state.targetDate = null;
  state.menu = null;
  goTo("dates-loading");
  // Shows every day in the window, not just orderable ones: a date the
  // orderability API refuses (closed / no_menu / ordering_closed / past /
  // unknown) must stay visible with its reason, per the task's "do not
  // hide it, explain why" requirement -- so this fetches each day's
  // status individually rather than only the pre-filtered available-dates
  // list (which is still exercised directly by the API tests/CLI).
  const today = new Date();
  const dates = Array.from({ length: DATE_PICKER_DAYS }, (_, i) => {
    const d = new Date(today);
    d.setDate(d.getDate() + i);
    return d.toISOString().slice(0, 10);
  });
  try {
    state.availableDates = await Promise.all(
      dates.map((d) => api(`/api/restaurants/${restaurant.slug}/status?date=${d}`))
    );
  } catch (err) {
    showToast(err.message);
    state.availableDates = [];
  }
  goTo("dates");
}

// --------------------------------------------------------------- Screen: dates

function dateStatusLabel(status) {
  const key = { available: "statusOpen", no_menu: "statusNoMenu", closed: "statusClosed",
    ordering_closed: "statusOrderingClosed", past_date: "statusPast", unknown: "statusUnknown" }[status];
  return key ? tr(key) : status.toUpperCase();
}

function renderDates() {
  app.innerHTML = "";
  app.append(header({ title: shortName(state.restaurantName), subtitle: tr("chooseYourDay"), back: () => goTo("restaurants") }));

  if (state.availableDates.length === 0) {
    app.append(emptyState("calendar", tr("couldNotLoadDatesTitle"), tr("couldNotLoadDatesBody")));
    return;
  }

  const scroller = el(`<div class="date-scroller"></div>`);
  for (const d of state.availableDates) {
    const { dow, dom } = fmtShort(d.date);
    const isAvailable = d.status === "available";
    const deadline = fmtDeadline(d.our_delivery && d.our_delivery.deadline);
    const ariaPrefix = isAvailable ? tr("select") : `${tr("unavailable")}:`;
    const card = el(`
      <button class="date-card ${isAvailable ? "" : "is-disabled"}" aria-label="${ariaPrefix} ${dow} ${dom}${!isAvailable ? `, ${dateStatusLabel(d.status)}` : ""}">
        <div class="dow">${dow}</div>
        <div class="dom">${dom}</div>
        <span class="status-chip ${d.status}">${escapeHtml(dateStatusLabel(d.status))}</span>
        ${isAvailable && deadline ? `<div class="deadline">${escapeHtml(tr("orderBefore"))}<br>${deadline}</div>` : ""}
      </button>
    `);
    // Every day stays tappable (even when disabled) so the reason is
    // never just hidden -- tapping an unavailable day still opens the
    // menu screen, which shows the specific empty state for it.
    card.addEventListener("click", () => selectDate(d));
    scroller.append(card);
  }
  app.append(scroller);
}

async function selectDate(dateInfo) {
  state.targetDate = dateInfo.date;
  state.dateInfo = dateInfo;
  state.selection = [];
  state.menu = null;
  state.menuError = null;
  state.filters = defaultFilters();
  state.filterSheetOpen = false;
  state.searchQuery = "";
  state.smartLunchForm = null;
  state.smartLunchResult = null;
  goTo("menu-loading");
  try {
    state.menu = await api(`/api/restaurants/${state.slug}/menu/${state.targetDate}`);
  } catch (err) {
    state.menuError = { status: err.body && err.body.status, reason: err.message };
  }
  goTo("menu");
}

// ------------------------------------------------------------ Favorites

// Jumps straight to today's menu for a favorited dish's restaurant --
// reuses selectDate() itself (same reset-selection/filters/search +
// menu-fetch behavior as picking a date normally) rather than
// duplicating it, once slug/restaurantName are set for this restaurant.
async function goToFavoriteToday(slug, restaurantName, dateInfo) {
  state.slug = slug;
  state.restaurantName = restaurantName;
  await selectDate(dateInfo);
}

// Checks TODAY's live availability for every restaurant that has at
// least one favorite -- never assumes a saved favorite is still
// orderable. Per-restaurant: closed/no_menu/ordering_closed/etc. is
// shown via the same status vocabulary as the date picker
// (dateStatusLabel); a restaurant that IS open today but no longer
// lists this specific dish gets its own distinct, honest reason
// (favoriteNotOnTodayMenu) rather than being lumped in with the
// restaurant-level statuses above.
async function openFavorites() {
  state.favoritesLoading = true;
  goTo("favorites");

  const today = new Date().toISOString().slice(0, 10);
  const uniqueSlugs = [...new Set(state.favorites.map((f) => f.slug))];
  const data = {};
  await Promise.all(
    uniqueSlugs.map(async (slug) => {
      try {
        const status = await api(`/api/restaurants/${slug}/status?date=${today}`);
        let menuByKey = null;
        if (status.status === "available") {
          try {
            const menu = await api(`/api/restaurants/${slug}/menu/${today}`);
            menuByKey = new Map(menu.items.map((it) => [cartItemKey(it), it]));
          } catch {
            menuByKey = null;
          }
        }
        data[slug] = { status, menuByKey, date: today };
      } catch {
        data[slug] = { status: null, menuByKey: null, date: today };
      }
    })
  );

  state.favoritesData = data;
  state.favoritesLoading = false;
  render();
}

function renderFavorites() {
  app.innerHTML = "";
  app.append(header({ title: tr("favorites"), back: () => goTo("restaurants") }));

  if (state.favoritesLoading) {
    app.append(loadingState(tr("loadingFavorites")));
    return;
  }

  if (state.favorites.length === 0) {
    app.append(emptyState("heart", tr("favoritesEmptyTitle"), tr("favoritesEmptyBody")));
    return;
  }

  for (const fav of state.favorites) {
    const data = state.favoritesData[fav.slug];
    const liveItem = data && data.menuByKey ? data.menuByKey.get(cartItemKey(fav)) : null;
    const restaurantStatus = data && data.status ? data.status.status : "unknown";

    const row = el(`
      <article class="favorite-row">
        <button type="button" class="heart-btn is-favorite" aria-label="${escapeHtml(tr("removeFavorite", { name: fav.name }))}" aria-pressed="true">${icon("heartFilled", 20)}</button>
        <div class="favorite-info">
          <p class="name">${escapeHtml(fav.name)}</p>
          <p class="restaurant">${escapeHtml(shortName(fav.restaurantName))}</p>
          ${
            liveItem
              ? `<div class="weight-price-row">
                   ${weightText(liveItem) ? `<span class="weight">${escapeHtml(weightText(liveItem))}</span><span class="dot">·</span>` : ""}
                   <span class="price ${liveItem.price == null ? "is-unspecified" : ""}">${escapeHtml(priceText(liveItem))}</span>
                   ${caloriesText(liveItem) ? `<span class="dot">·</span><span class="calories">${escapeHtml(caloriesText(liveItem))}</span>` : ""}
                 </div>`
              : `<p class="status-line">${escapeHtml(restaurantStatus === "available" ? tr("favoriteNotOnTodayMenu") : dateStatusLabel(restaurantStatus))}</p>`
          }
        </div>
      </article>
    `);

    row.querySelector(".heart-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFavorite(fav.slug, fav.restaurantName, fav.category, fav.name);
      renderFavorites();
    });

    if (liveItem) {
      row.classList.add("is-clickable");
      row.setAttribute("role", "button");
      row.setAttribute("tabindex", "0");
      row.setAttribute("aria-label", tr("viewTodayMenuFor", { name: shortName(fav.restaurantName) }));
      const go = () => goToFavoriteToday(fav.slug, fav.restaurantName, data.status);
      row.addEventListener("click", go);
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          go();
        }
      });
    }

    app.append(row);
  }
}

// -------------------------------------------------------- Order history

// Mirrors localizedWeightSummary()'s local-preview version, but reads
// the backend's snake_case order.totals shape (same idea as
// serverPriceBreakdown/formatServerPriceTotal further up).
function historyWeightSummary(order) {
  const totals = order.totals;
  const parts = Object.entries(totals.weight_by_unit || {})
    .filter(([, v]) => v > 0)
    .map(([unit, v]) => `${v} ${unit}`);
  if (totals.unknown_weight_portions > 0) parts.push(`${totals.unknown_weight_portions} ${tr("statusUnknown").toLowerCase()}`);
  return parts.length ? parts.join(" + ") : tr("portionSizeNotSpecified");
}

function orderStatusLabel(status) {
  // Only "pending" exists today (OrderStore has no real fulfillment
  // flow yet, see its schema's DEFAULT) -- the fallback keeps a future
  // status value visible/honest rather than mistranslated as "Pending".
  if (status === "pending") return tr("statusPending");
  return status;
}

async function openOrderHistory() {
  state.orderHistoryLoading = true;
  state.orderHistoryOrders = [];
  goTo("order-history");

  const ids = loadOrderHistoryIds();
  const orders = [];
  await Promise.all(
    ids.map(async (id) => {
      try {
        orders.push(await api(`/api/orders/${id}`));
      } catch {
        // Order id no longer resolves (or the request failed) -- skip it
        // silently rather than showing a broken row; nothing else in
        // this app surfaces a raw fetch failure per stale list entry.
      }
    })
  );
  orders.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  state.orderHistoryOrders = orders;
  state.orderHistoryLoading = false;
  render();
}

function renderOrderHistory() {
  app.innerHTML = "";
  app.append(header({ title: tr("orderHistory"), back: () => goTo("restaurants") }));

  if (state.orderHistoryLoading) {
    app.append(loadingState(tr("loadingOrderHistory")));
    return;
  }

  if (state.orderHistoryOrders.length === 0) {
    app.append(emptyState("clock", tr("orderHistoryEmptyTitle"), tr("orderHistoryEmptyBody")));
    return;
  }

  for (const order of state.orderHistoryOrders) {
    const itemsSummary = order.items.map((it) => `${it.name}${it.quantity > 1 ? ` ×${it.quantity}` : ""}`).join(", ");
    const row = el(`
      <article class="history-row">
        <p class="restaurant">${escapeHtml(shortName(order.restaurant_name))} · ${escapeHtml(fmtLong(order.order_date))}</p>
        <p class="items-summary">${escapeHtml(itemsSummary)}</p>
        <p class="meta">${escapeHtml(tr("placedOn"))} ${escapeHtml(fmtDeadline(order.created_at))} · ${escapeHtml(orderStatusLabel(order.status))}</p>
        <p class="meta">${escapeHtml(historyWeightSummary(order))} · ${escapeHtml(formatServerPriceTotal(order))}</p>
        <button type="button" class="history-reorder-btn">${escapeHtml(tr("reorder"))}</button>
      </article>
    `);
    row.querySelector(".history-reorder-btn").addEventListener("click", () => reorderPastOrder(order));
    app.append(row);
  }
}

// ------------------------------------------------------------- Screen: profile
//
// A lightweight "settings" screen, not a real account profile -- there's
// no auth/account system in this app (see README intro), so this
// deliberately has no name/avatar/"Student" line, no delivery addresses,
// no notifications toggle, and no log-out (nothing to log out of). Just
// what's genuinely real and useful: shortcuts to the two other
// localStorage-backed personal lists, the language picker, and an
// honest one-paragraph explanation of what this app actually is.
function renderProfile() {
  app.innerHTML = "";
  app.append(header({ title: tr("profile"), back: () => goTo("restaurants") }));

  app.append(el(`<p class="eyebrow" style="padding-top:0">${escapeHtml(tr("tagline"))}</p>`));

  const rows = el(`<div class="profile-rows"></div>`);

  const favRow = el(`
    <button type="button" class="profile-row">
      <span class="profile-row-icon">${icon("heart", 20)}</span>
      <span class="profile-row-label">${escapeHtml(tr("favorites"))}</span>
      <span class="profile-row-count">${state.favorites.length}</span>
      <span class="profile-row-chevron">${icon("chevron", 16)}</span>
    </button>
  `);
  favRow.addEventListener("click", () => openFavorites());
  rows.append(favRow);

  const historyRow = el(`
    <button type="button" class="profile-row">
      <span class="profile-row-icon">${icon("receipt", 20)}</span>
      <span class="profile-row-label">${escapeHtml(tr("orderHistory"))}</span>
      <span class="profile-row-count">${loadOrderHistoryIds().length}</span>
      <span class="profile-row-chevron">${icon("chevron", 16)}</span>
    </button>
  `);
  historyRow.addEventListener("click", () => openOrderHistory());
  rows.append(historyRow);

  const current = langInfo(state.lang);
  const langRow = el(`
    <button type="button" class="profile-row profile-row-lang" aria-haspopup="dialog">
      <span class="profile-row-icon">${icon("globe", 20)}</span>
      <span class="profile-row-label">${escapeHtml(tr("language"))}</span>
      <span class="profile-row-count" lang="${current.locale}">${escapeHtml(current.label)}</span>
      <span class="profile-row-chevron">${icon("chevron", 16)}</span>
    </button>
  `);
  langRow.addEventListener("click", () => openLanguageSheet(langRow));
  rows.append(langRow);

  app.append(rows);

  app.append(el(`
    <div class="profile-about">
      <h4>${escapeHtml(tr("aboutTitle"))}</h4>
      <p>${escapeHtml(tr("aboutBody"))}</p>
    </div>
  `));
}

// Re-validates a past order against TODAY's live menu -- never blindly
// resubmits the old order or trusts its stored prices/weights/ids (all
// of Restopolis's own data can change; menu_service.flatten_menu_items()
// re-derives ids fresh on every fetch, see Part 46's Cart-restore
// writeup for the same underlying hazard). Matches by (category, name),
// drops anything no longer on today's menu with a clear explanation,
// and lands on the cart screen (Part 46) with a fresh, server-verifiable
// selection -- it never re-creates the order directly.
async function reorderPastOrder(order) {
  const restaurant = state.restaurants.find((r) => r.code === order.restaurant_code);
  if (!restaurant) {
    showToast(tr("couldNotReachServerTitle"));
    return;
  }

  const today = new Date().toISOString().slice(0, 10);
  let dateInfo;
  try {
    dateInfo = await api(`/api/restaurants/${restaurant.slug}/status?date=${today}`);
  } catch (err) {
    showToast(err.message);
    return;
  }
  if (dateInfo.status !== "available") {
    showToast(tr("reorderNotAvailableToday", { name: shortName(restaurant.name) }));
    return;
  }

  let menu;
  try {
    menu = await api(`/api/restaurants/${restaurant.slug}/menu/${today}`);
  } catch (err) {
    showToast(err.message);
    return;
  }

  const byKey = new Map(menu.items.map((it) => [cartItemKey(it), it]));
  const newSelection = [];
  let droppedCount = 0;
  for (const oldItem of order.items) {
    const liveItem = byKey.get(cartItemKey(oldItem));
    if (liveItem) newSelection.push({ menuItemId: liveItem.id, quantity: oldItem.quantity });
    else droppedCount++;
  }

  if (newSelection.length === 0) {
    showToast(tr("reorderNoneAvailable"));
    return;
  }

  state.slug = restaurant.slug;
  state.restaurantName = restaurant.name;
  state.targetDate = today;
  state.dateInfo = dateInfo;
  state.menu = menu;
  state.menuError = null;
  state.filters = defaultFilters();
  state.filterSheetOpen = false;
  state.searchQuery = "";
  state.selection = newSelection;
  state.serverQuote = null;
  state.deliveryLocation = order.delivery_location || "";

  if (droppedCount > 0) showToast(tr("reorderItemsUnavailable", { n: droppedCount }));
  saveCart();
  goTo("review");
}

// --------------------------------------------------------------- Screen: menu

function renderMenu() {
  app.innerHTML = "";
  app.append(header({ title: shortName(state.restaurantName), subtitle: fmtLong(state.targetDate), back: () => goTo("dates") }));

  if (state.menuError) {
    const messages = {
      no_menu: ["plate", tr("menuNotYetTitle"), tr("menuNotYetBody")],
      closed: ["ban", tr("restaurantClosedTitle"), tr("restaurantClosedBody")],
      ordering_closed: ["clock", tr("orderingClosedTitle"), tr("orderingClosedBody")],
      past_date: ["calendar", tr("dateNoLongerAvailableTitle"), state.menuError.reason],
      unknown: ["info", tr("statusUnknownTitle"), state.menuError.reason],
    };
    const [iconName, title, body] = messages[state.menuError.status] || ["warn", tr("menuUnavailableTitle"), state.menuError.reason];
    app.append(emptyState(iconName, title, body));
    return;
  }

  if (!state.menu || state.menu.items.length === 0) {
    app.append(emptyState("plate", tr("menuNotYetTitle"), tr("menuNoDishesBody")));
    return;
  }

  const headerBlock = el(`<div class="menu-header"></div>`);
  if (state.menu.service_time) headerBlock.append(el(`<p class="service-time">${escapeHtml(state.menu.service_time)}</p>`));
  const deadline = fmtDeadline(state.dateInfo && state.dateInfo.our_delivery && state.dateInfo.our_delivery.deadline);
  if (deadline) headerBlock.append(el(`<p class="deadline-line">${escapeHtml(tr("orderDeadline"))}: ${deadline}</p>`));
  app.append(headerBlock);

  app.append(searchBar());
  app.append(filterBar());

  const searchedItems = searchItems(state.menu.items, state.searchQuery, (cat) => categoryLabel(cat, state.lang), (a) => allergenLabel(a, state.lang));
  const filteredItems = filterItems(searchedItems, state.filters);

  if (filteredItems.length === 0) {
    const query = state.searchQuery.trim();
    if (query) app.append(emptyState("search", tr("noSearchResultsTitle", { query }), tr("noSearchResultsBody")));
    else app.append(emptyState("search", tr("noResultsTitle"), tr("noResultsBody")));
    // Zero results can come from search, filters, or both -- this button
    // clears everything narrowing the view, unlike the filter sheet's own
    // "Clear all" (below), which only clears filters and deliberately
    // leaves an in-progress search term in place.
    const clearBtn = el(`<button type="button" class="secondary-button" style="margin:0 16px">${escapeHtml(tr("clearFilters"))}</button>`);
    clearBtn.addEventListener("click", () => {
      state.filters = defaultFilters();
      state.searchQuery = "";
      renderMenu();
    });
    app.append(clearBtn);
    if (state.filterSheetOpen) app.append(filterSheet());
    return;
  }

  // data-cat always carries the RAW Restopolis category string (the
  // stable identifier used for anchors/highlighting); only the visible
  // text goes through categoryLabel() -- see static/i18n.js's
  // CATEGORY_LABELS for which ~25 known categories that translates.
  // Derived from the FILTERED items, not the full menu, so a category
  // with nothing currently visible doesn't show an empty nav button/section.
  const categories = availableFilterCategories(filteredItems);
  const nav = el(`<nav class="category-nav" aria-label="${escapeHtml(tr("jumpToCategory"))}"></nav>`);
  for (const cat of categories) {
    const btn = el(`<button data-cat="${escapeHtml(cat)}">${escapeHtml(categoryLabel(cat, state.lang))}</button>`);
    btn.addEventListener("click", () => {
      document.getElementById(`cat-${cssId(cat)}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    nav.append(btn);
  }
  app.append(nav);

  const byCategory = new Map();
  for (const it of filteredItems) {
    if (!byCategory.has(it.category)) byCategory.set(it.category, []);
    byCategory.get(it.category).push(it);
  }

  for (const cat of categories) {
    const section = el(`<section class="category-section" id="cat-${cssId(cat)}" data-cat="${escapeHtml(cat)}"><h3>${escapeHtml(categoryLabel(cat, state.lang))}</h3></section>`);
    const grid = el(`<div class="food-grid"></div>`);
    for (const item of byCategory.get(cat)) grid.append(foodCard(item));
    section.append(grid);
    app.append(section);
  }

  updateCategoryNavHighlight();
  onScroll(updateCategoryNavHighlight);

  renderSummaryBar();
  if (state.filterSheetOpen) app.append(filterSheet());
}

// ------------------------------------------------------------ Filters

const WEIGHT_BUCKET_I18N_KEYS = {
  any: "weightAny",
  under100: "weightUnder100",
  "100to250": "weight100to250",
  over250: "weightOver250",
};
const CALORIE_BUCKET_I18N_KEYS = {
  any: "caloriesAny",
  under200: "caloriesUnder200",
  "200to400": "calories200to400",
  over400: "caloriesOver400",
};

function filterBar() {
  const count = activeFilterCount(state.filters);
  const bar = el(`
    <div class="filter-bar">
      <button type="button" class="filter-button">
        ${escapeHtml(tr("filters"))}${count > 0 ? `<span class="filter-count">${count}</span>` : ""}
      </button>
      <button type="button" class="filter-button smart-lunch-button">${icon("sparkle", 16)} ${escapeHtml(tr("smartLunch"))}</button>
    </div>
  `);
  bar.querySelector(".filter-button:not(.smart-lunch-button)").addEventListener("click", () => {
    state.filterSheetOpen = true;
    renderMenu();
  });
  bar.querySelector(".smart-lunch-button").addEventListener("click", () => openSmartLunch());
  return bar;
}

// ------------------------------------------------------------- Search

// renderMenu() rebuilds the whole screen (app.innerHTML = "") on every
// call, which would normally steal focus/cursor position out of the
// search <input> on each debounced re-render while the user is still
// typing. Saving and restoring them around the call keeps typing feeling
// uninterrupted despite the full-rebuild render strategy used everywhere
// else in this app (see renderReview()'s quantity steppers for the same
// full-re-render pattern, where losing focus doesn't matter since
// there's no text cursor to preserve).
function rerenderMenuPreservingSearchFocus() {
  const input = document.querySelector(".search-input");
  const hadFocus = !!input && document.activeElement === input;
  const cursorPos = input ? input.selectionStart : null;
  renderMenu();
  if (hadFocus) {
    const freshInput = document.querySelector(".search-input");
    if (freshInput) {
      freshInput.focus();
      if (cursorPos != null) freshInput.setSelectionRange(cursorPos, cursorPos);
    }
  }
}

// Debounced so fast typing collapses into one re-render per pause
// rather than one per keystroke, matching the same performance-minded
// debouncing already used for the cart's server-quote requests.
const debouncedSearchRerender = debounce(rerenderMenuPreservingSearchFocus, 250);

function searchBar() {
  const bar = el(`
    <div class="search-bar">
      <input
        type="search"
        class="search-input"
        placeholder="${escapeHtml(tr("searchPlaceholder"))}"
        aria-label="${escapeHtml(tr("searchPlaceholder"))}"
        value="${escapeHtml(state.searchQuery)}"
      >
      ${state.searchQuery ? `<button type="button" class="search-clear" aria-label="${escapeHtml(tr("clearSearch"))}">${icon("close", 18)}</button>` : ""}
    </div>
  `);
  bar.querySelector(".search-input").addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    debouncedSearchRerender();
  });
  const clearBtn = bar.querySelector(".search-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      state.searchQuery = "";
      renderMenu();
    });
  }
  return bar;
}

function toggleInArray(arr, value) {
  return arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value];
}

function applyFilterChange(mutate) {
  mutate(state.filters);
  renderMenu();
}

function chipButton(label, isActive, onClick) {
  const btn = el(`<button type="button" class="chip ${isActive ? "is-active" : ""}">${escapeHtml(label)}</button>`);
  btn.addEventListener("click", onClick);
  return btn;
}

// Bottom-sheet overlay: works identically at any viewport width (this
// app's shell is a single centered column even on wide screens, see
// static/app.css's --max-content-width -- a persistent desktop SIDEBAR
// would need a wider two-pane shell, deferred to the later UI-redesign
// pass rather than built as a one-off here; see README.md Part 9's
// Known limitations).
function filterSheet() {
  const fullMenuItems = state.menu.items;
  const categories = availableFilterCategories(fullMenuItems);
  const allergens = availableAllergens(fullMenuItems);
  const hasVegetarian = fullMenuItems.some((it) => it.vegetarian || it.vegan);
  const hasVegan = fullMenuItems.some((it) => it.vegan);
  // Reflects the FULL combined narrowing (search + filters together),
  // same as what renderMenu() will actually show once applied.
  const searchedForCount = searchItems(fullMenuItems, state.searchQuery, (cat) => categoryLabel(cat, state.lang), (a) => allergenLabel(a, state.lang));
  const resultCount = filterItems(searchedForCount, state.filters).length;

  const overlay = el(`<div class="filter-sheet-overlay"></div>`);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) {
      state.filterSheetOpen = false;
      renderMenu();
    }
  });

  const sheet = el(`
    <div class="filter-sheet" role="dialog" aria-label="${escapeHtml(tr("filters"))}">
      <div class="filter-sheet-header">
        <p class="screen-title">${escapeHtml(tr("filters"))}</p>
        <button type="button" class="filter-close" aria-label="${escapeHtml(tr("back"))}">${icon("close", 20)}</button>
      </div>
      <div class="filter-sheet-body"></div>
      <div class="filter-sheet-footer">
        <button type="button" class="secondary-button filter-clear">${escapeHtml(tr("clearFilters"))}</button>
        <button type="button" class="primary-button filter-apply">${escapeHtml(tr("showResults", { n: resultCount }))}</button>
      </div>
    </div>
  `);
  sheet.querySelector(".filter-close").addEventListener("click", () => {
    state.filterSheetOpen = false;
    renderMenu();
  });
  sheet.querySelector(".filter-clear").addEventListener("click", () => {
    state.filters = defaultFilters();
    renderMenu();
  });
  sheet.querySelector(".filter-apply").addEventListener("click", () => {
    state.filterSheetOpen = false;
    renderMenu();
  });

  const body = sheet.querySelector(".filter-sheet-body");

  if (categories.length > 0) {
    const section = el(`<div class="filter-section"><h4>${escapeHtml(tr("categoryFilter"))}</h4><div class="chip-row"></div></div>`);
    const row = section.querySelector(".chip-row");
    for (const cat of categories) {
      row.append(
        chipButton(categoryLabel(cat, state.lang), state.filters.categories.includes(cat), () =>
          applyFilterChange((f) => (f.categories = toggleInArray(f.categories, cat)))
        )
      );
    }
    body.append(section);
  }

  if (hasVegetarian || hasVegan) {
    const section = el(`<div class="filter-section"><h4>${escapeHtml(tr("dietaryFilter"))}</h4><div class="chip-row"></div></div>`);
    const row = section.querySelector(".chip-row");
    if (hasVegetarian) {
      row.append(
        chipButton(tr("vegetarian"), state.filters.dietary.includes("vegetarian"), () =>
          applyFilterChange((f) => (f.dietary = toggleInArray(f.dietary, "vegetarian")))
        )
      );
    }
    if (hasVegan) {
      row.append(
        chipButton(tr("vegan"), state.filters.dietary.includes("vegan"), () =>
          applyFilterChange((f) => (f.dietary = toggleInArray(f.dietary, "vegan")))
        )
      );
    }
    body.append(section);
  }

  if (allergens.length > 0) {
    const section = el(`<div class="filter-section"><h4>${escapeHtml(tr("allergensToAvoid"))}</h4><div class="chip-row"></div></div>`);
    const row = section.querySelector(".chip-row");
    for (const a of allergens) {
      row.append(
        chipButton(allergenLabel(a, state.lang), state.filters.excludedAllergens.includes(a.code), () =>
          applyFilterChange((f) => (f.excludedAllergens = toggleInArray(f.excludedAllergens, a.code)))
        )
      );
    }
    body.append(section);
  }

  const weightSection = el(`<div class="filter-section"><h4>${escapeHtml(tr("weight"))}</h4><div class="chip-row"></div></div>`);
  const weightRow = weightSection.querySelector(".chip-row");
  for (const bucket of WEIGHT_BUCKETS) {
    weightRow.append(
      chipButton(tr(WEIGHT_BUCKET_I18N_KEYS[bucket]), state.filters.weightBucket === bucket, () =>
        applyFilterChange((f) => (f.weightBucket = bucket))
      )
    );
  }
  if (state.filters.weightBucket !== "any") weightSection.append(el(`<p class="filter-note">${escapeHtml(tr("weightBucketNote"))}</p>`));
  body.append(weightSection);

  const caloriesSection = el(`<div class="filter-section"><h4>${escapeHtml(tr("calories"))}</h4><div class="chip-row"></div></div>`);
  const caloriesRow = caloriesSection.querySelector(".chip-row");
  for (const bucket of CALORIE_BUCKETS) {
    caloriesRow.append(
      chipButton(tr(CALORIE_BUCKET_I18N_KEYS[bucket]), state.filters.caloriesBucket === bucket, () =>
        applyFilterChange((f) => (f.caloriesBucket = bucket))
      )
    );
  }
  if (state.filters.caloriesBucket !== "any") caloriesSection.append(el(`<p class="filter-note">${escapeHtml(tr("caloriesBucketNote"))}</p>`));
  body.append(caloriesSection);

  overlay.append(sheet);
  return overlay;
}

function cssId(s) {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase();
}

function updateCategoryNavHighlight() {
  const nav = document.querySelector(".category-nav");
  if (!nav) return;
  const sections = [...document.querySelectorAll(".category-section")];
  // Inside the desktop frame, positions are measured from the device
  // screen's top edge rather than the browser viewport's.
  const baseTop = FRAMED.matches ? scroller.getBoundingClientRect().top : 0;
  let activeCat = null;
  for (const sec of sections) {
    const rect = sec.getBoundingClientRect();
    if (rect.top - baseTop <= 120) activeCat = sec.dataset.cat;
  }
  let activeBtn = null;
  let justBecameActive = false;
  for (const btn of nav.querySelectorAll("button")) {
    const isActive = btn.dataset.cat === activeCat;
    if (isActive) {
      activeBtn = btn;
      if (!btn.classList.contains("is-active")) justBecameActive = true;
    }
    btn.classList.toggle("is-active", isActive);
  }
  // Keeps the horizontal category-chip row moving in sync with vertical
  // dish scrolling -- e.g. scrolling down from "Starter" into "Dessert"
  // auto-scrolls the row right so the Dessert chip stays in view, the
  // same synced-tabs pattern most food delivery apps use, instead of
  // the active chip silently scrolling out of sight. Only scrolls the
  // row when the active category actually just changed (not on every
  // scroll tick), so it never fights the user's own manual left/right
  // drag on the row itself.
  if (activeBtn && justBecameActive) {
    activeBtn.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }
}

function selectionFor(itemId) {
  return state.selection.find((s) => s.menuItemId === itemId);
}

// item.weight_display / order-math.js's formatWeightValue are both
// language-neutral (backend-formatted, e.g. "80 g"). Returns null when
// no weight was ever published for this dish (the common case for
// Restopolis's daily-formula items, see README.md Part 3/7) -- callers
// simply omit the weight segment in that case rather than stating "not
// specified" on every single item, the same conditional-segment idiom
// already used for caloriesText().
function weightText(item) {
  return item.weight_value != null ? item.weight_display : null;
}

// Same idea as weightText(), but for raw (value, unit) pairs -- used for
// the confirmed-order screen, whose items come from POST /api/orders'
// response shape rather than the /menu endpoint's pre-formatted items.
function localizedWeightValue(value, unit) {
  if (value == null || unit == null) return null;
  return unit === "piece" ? `${value} pc` : `${value} ${unit}`;
}

// There's no per-dish Restopolis price (see static/pricing.js's module
// docstring) -- but Féculents/Légumes are KNOWN to be bundled free with
// any main dish (our own formula rule, not a guess), so those get an
// honest "Included" instead of a generic "price not available".
function priceText(item) {
  if (item.price != null) return `€${item.price.toFixed(2)}`;
  if (INCLUDED_SIDE_CATEGORIES.has(item.category)) return tr("included");
  return tr("priceNotAvailable");
}

// Per the confirmed calorie methodology: only ever shown for items with
// a real known weight AND a matched food-type keyword (never a guessed
// default -- see orderability_engine/nutrition.py), and always prefixed
// with the "≈ estimated" label so it's never mistaken for a precise or
// Restopolis-sourced fact. Returns null (render nothing) rather than a
// "not available" placeholder when there's nothing to show -- unlike
// weight/price, an absent calorie estimate isn't a data-integrity fact
// worth calling out on every single card.
function caloriesText(item) {
  if (item.calories == null) return null;
  return `${tr("estimated")} ${Math.round(item.calories)} ${tr("kcal")}`;
}

// Purely a visual grouping cue for the icon-avatar's color -- derived
// from real fields already on the item (vegetarian/vegan flags,
// weight_unit, category), never a new classification invented for this.
// The glyph itself doesn't vary; only the color does, matching the
// reference design's own use of a single icon shape per row with color
// as the category signal.
function categoryIconClass(item) {
  if (item.weight_unit === "ml" || item.weight_unit === "l") return "is-drink";
  if (item.vegan || item.vegetarian) return "is-veg";
  if (MAIN_CATEGORIES.has(item.category)) return "is-meat";
  return "is-other";
}

function foodCard(item) {
  const sel = selectionFor(item.id);
  const isSelected = !!sel;
  const isFav = isFavorite(state.slug, item.category, item.name);
  const card = el(`
    <article class="food-card ${isSelected ? "is-selected" : ""}" data-item-id="${item.id}">
      <div class="select-check" aria-hidden="true">${icon(isSelected ? "check" : "plus", 16)}</div>
      <button type="button" class="heart-btn ${isFav ? "is-favorite" : ""}" aria-label="${escapeHtml(tr(isFav ? "removeFavorite" : "addFavorite", { name: item.name }))}" aria-pressed="${isFav}">${icon(isFav ? "heartFilled" : "heart", 20)}</button>
      <div class="card-head">
        <div class="icon-avatar ${categoryIconClass(item)}">${icon("fork", 18)}</div>
        <div>
          <p class="name">${escapeHtml(item.name)}</p>
          ${item.description ? `<p class="description">${escapeHtml(item.description)}</p>` : ""}
        </div>
      </div>
      <div class="weight-price-row">
        ${weightText(item) ? `<span class="weight">${escapeHtml(weightText(item))}</span><span class="dot">·</span>` : ""}
        <span class="price ${item.price == null ? "is-unspecified" : ""}">${escapeHtml(priceText(item))}</span>
        ${caloriesText(item) ? `<span class="dot">·</span><span class="calories">${escapeHtml(caloriesText(item))}</span>` : ""}
      </div>
      <div class="badge-row">
        ${item.vegan ? `<span class="badge">${escapeHtml(tr("vegan"))}</span>` : item.vegetarian ? `<span class="badge">${escapeHtml(tr("vegetarian"))}</span>` : ""}
      </div>
      ${item.allergens && item.allergens.length ? `<p class="allergen-line">${escapeHtml(tr("allergens"))} ${item.allergens.map((a) => escapeHtml(allergenLabel(a, state.lang))).join(" · ")}</p>` : ""}
      <div class="quantity-row"></div>
    </article>
  `);

  const qtyRow = card.querySelector(".quantity-row");
  if (isSelected) {
    qtyRow.append(
      el(`
      <div class="quantity-stepper">
        <button type="button" aria-label="${escapeHtml(tr("decreaseQuantityOf", { name: item.name }))}">−</button>
        <span class="quantity-value">${sel.quantity}</span>
        <button type="button" aria-label="${escapeHtml(tr("increaseQuantityOf", { name: item.name }))}">+</button>
      </div>
    `)
    );
    const [decBtn, , incBtn] = qtyRow.querySelectorAll("button, span");
    decBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      changeQuantity(item.id, -1);
    });
    incBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      changeQuantity(item.id, +1);
    });
  }

  card.querySelector(".heart-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleFavorite(state.slug, state.restaurantName, item.category, item.name);
    card.replaceWith(foodCard(item));
  });

  card.addEventListener("click", () => toggleSelection(item.id));
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  card.setAttribute("aria-pressed", String(isSelected));
  card.setAttribute("aria-label", tr(isSelected ? "deselectItem" : "selectItem", { name: item.name }));
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleSelection(item.id);
    }
  });

  return card;
}

function toggleSelection(itemId) {
  const existing = selectionFor(itemId);
  if (existing) {
    state.selection = state.selection.filter((s) => s.menuItemId !== itemId);
  } else {
    state.selection.push({ menuItemId: itemId, quantity: 1 });
  }
  state.serverQuote = null;
  saveCart();
  refreshMenuScreen();
}

function changeQuantity(itemId, delta) {
  const existing = selectionFor(itemId);
  if (!existing) return;
  const maxQ = (state.menu && state.menu.max_quantity) || 10;
  const next = existing.quantity + delta;
  if (next < 1) {
    state.selection = state.selection.filter((s) => s.menuItemId !== itemId);
  } else {
    existing.quantity = clampQuantity(next, maxQ);
  }
  state.serverQuote = null;
  saveCart();
  refreshMenuScreen();
}

function refreshMenuScreen() {
  // Re-render just the affected pieces to keep scroll position stable.
  for (const sel of [...document.querySelectorAll(".food-card")]) {
    const id = Number(sel.dataset.itemId);
    const item = menuById().get(id);
    if (item) sel.replaceWith(foodCard(item));
  }
  renderSummaryBar();
}

function renderSummaryBar() {
  document.querySelector(".summary-bar")?.remove();
  if (state.selection.length === 0) return;
  const totals = computeOrderTotals(state.selection, menuById());
  const bar = el(`
    <div class="summary-bar">
      <div class="summary-text">
        <strong>${tr("itemCount", { n: totals.itemCount })} · ${localizedWeightSummary(totals)}</strong>
        ${localizedPriceSummary(totals)}
      </div>
      <button type="button">${escapeHtml(tr("viewOrder"))}</button>
    </div>
  `);
  bar.querySelector("button").addEventListener("click", () => goTo("review"));
  deviceScreen.append(bar);
}

// ---------------------------------------------------------- Smart Lunch
//
// A deterministic BACKEND search (POST /api/smart-lunch, Part 51) over
// today's live menu -- this screen only collects constraints and
// displays what the server found. It never ranks results as "best" or
// "healthiest" (no such claim exists anywhere in the response, see
// orderability_engine/smart_lunch.py's module docstring): the
// server-returned option order is structural (by meal tier, or by main
// dish -- see select_options()), not a quality score, and the "Option
// N" labels below are built from the response array's own position,
// never text sent by the backend (which never sends UI prose, only
// reason/constraint CODES -- same "codes, not prose" rule Part 6/39's
// formula-reason handling already follows).

const SMART_LUNCH_CONSTRAINT_KEYS = {
  dietary_preferences: "constraintDietary",
  excluded_allergens: "constraintAllergens",
  meal_preference: "constraintMealPreference",
  max_price: "constraintMaxPrice",
  min_weight: "constraintMinWeight",
  max_calories: "constraintMaxCalories",
};

const SMART_LUNCH_REASON_KEYS = {
  no_weight_data_available: "reasonNoWeightData",
  no_calorie_data_available: "reasonNoCalorieData",
  no_combination_meets_minimum_weight: "reasonNoWeightMatch",
  no_combination_within_calorie_limit: "reasonNoCalorieMatch",
  no_combination_within_price: "reasonNoPriceMatch",
  no_combination_at_requested_tier: "reasonNoTierMatch",
  no_main_dishes_match_dietary_or_allergen_filters: "reasonNoMainsFiltered",
  no_main_dishes_available: "reasonNoMainsAvailable",
  no_valid_combination_found: "reasonNoValidCombo",
  no_matching_combination: "reasonGeneric",
};

function defaultSmartLunchForm() {
  return { dietary: [], excludedAllergens: [], mealPreference: null, maxPrice: "", minWeight: "", maxCalories: "" };
}

function openSmartLunch() {
  state.smartLunchForm = state.smartLunchForm || defaultSmartLunchForm();
  state.smartLunchResult = null;
  state.smartLunchLoading = false;
  goTo("smart-lunch");
}

async function submitSmartLunch() {
  const form = state.smartLunchForm;
  const body = {
    restaurant: state.slug,
    date: state.targetDate,
    dietary_preferences: form.dietary,
    excluded_allergens: form.excludedAllergens,
  };
  if (form.mealPreference) body.meal_preference = form.mealPreference;
  const maxPrice = parseFloat(form.maxPrice);
  if (!Number.isNaN(maxPrice)) body.max_price = maxPrice;
  const minWeight = parseFloat(form.minWeight);
  if (!Number.isNaN(minWeight)) body.min_weight = minWeight;
  const maxCalories = parseFloat(form.maxCalories);
  if (!Number.isNaN(maxCalories)) body.max_calories = maxCalories;

  state.smartLunchLoading = true;
  render();
  try {
    state.smartLunchResult = await api("/api/smart-lunch", { method: "POST", body: JSON.stringify(body) });
  } catch (err) {
    showToast(err.message);
    state.smartLunchResult = null;
  }
  state.smartLunchLoading = false;
  render();
}

// Adds every item in a chosen option to the CURRENT selection, matched
// by (category, name) against the menu already loaded for this exact
// restaurant/date (state.menu) -- never trusting the smart-lunch
// response's ids directly, same "never trust an id across a separate
// fetch" principle as Cart restore/Favorites/Reorder (Parts 46/49/50).
function addSmartLunchOptionToSelection(option) {
  const byKey = new Map(state.menu.items.map((it) => [cartItemKey(it), it]));
  const maxQ = (state.menu && state.menu.max_quantity) || 10;
  for (const item of option.items) {
    const liveItem = byKey.get(cartItemKey(item));
    if (!liveItem) continue;
    const existing = selectionFor(liveItem.id);
    if (existing) existing.quantity = clampQuantity(existing.quantity + 1, maxQ);
    else state.selection.push({ menuItemId: liveItem.id, quantity: 1 });
  }
  state.serverQuote = null;
  saveCart();
  showToast(tr("smartLunchOptionAdded"));
  goTo("review");
}

function renderSmartLunch() {
  app.innerHTML = "";
  app.append(
    header({
      title: tr("smartLunch"),
      subtitle: `${shortName(state.restaurantName)} · ${fmtLong(state.targetDate)}`,
      back: () => goTo("menu"),
    })
  );

  if (state.smartLunchLoading) {
    app.append(loadingState(tr("smartLunchSearching")));
    return;
  }

  if (state.smartLunchResult) {
    renderSmartLunchResult();
    return;
  }

  renderSmartLunchForm();
}

function renderSmartLunchForm() {
  const form = state.smartLunchForm;
  const fullMenuItems = state.menu.items;
  const allergens = availableAllergens(fullMenuItems);
  const hasVegetarian = fullMenuItems.some((it) => it.vegetarian || it.vegan);
  const hasVegan = fullMenuItems.some((it) => it.vegan);

  const body = el(`<div class="smart-lunch-form"></div>`);

  const tierSection = el(`<div class="filter-section"><h4>${escapeHtml(tr("smartLunchMealPreference"))}</h4><div class="chip-row"></div></div>`);
  const tierRow = tierSection.querySelector(".chip-row");
  const tierOptions = [
    [null, "mealPrefAny"],
    ["main", "mealPrefMain"],
    ["main_starter", "mealPrefMainStarter"],
    ["main_starter_dessert", "mealPrefMainStarterDessert"],
  ];
  for (const [value, key] of tierOptions) {
    tierRow.append(
      chipButton(tr(key), form.mealPreference === value, () => {
        form.mealPreference = value;
        renderSmartLunch();
      })
    );
  }
  body.append(tierSection);

  if (hasVegetarian || hasVegan) {
    const section = el(`<div class="filter-section"><h4>${escapeHtml(tr("dietaryFilter"))}</h4><div class="chip-row"></div></div>`);
    const row = section.querySelector(".chip-row");
    if (hasVegetarian) {
      row.append(
        chipButton(tr("vegetarian"), form.dietary.includes("vegetarian"), () => {
          form.dietary = toggleInArray(form.dietary, "vegetarian");
          renderSmartLunch();
        })
      );
    }
    if (hasVegan) {
      row.append(
        chipButton(tr("vegan"), form.dietary.includes("vegan"), () => {
          form.dietary = toggleInArray(form.dietary, "vegan");
          renderSmartLunch();
        })
      );
    }
    body.append(section);
  }

  if (allergens.length > 0) {
    const section = el(`<div class="filter-section"><h4>${escapeHtml(tr("allergensToAvoid"))}</h4><div class="chip-row"></div></div>`);
    const row = section.querySelector(".chip-row");
    for (const a of allergens) {
      row.append(
        chipButton(allergenLabel(a, state.lang), form.excludedAllergens.includes(a.code), () => {
          form.excludedAllergens = toggleInArray(form.excludedAllergens, a.code);
          renderSmartLunch();
        })
      );
    }
    body.append(section);
  }

  const numericSection = el(`
    <div class="filter-section">
      <div class="field-block"><label>${escapeHtml(tr("maxPriceLabel"))}</label><input type="number" inputmode="decimal" min="0" step="0.10" class="sl-max-price" value="${escapeHtml(form.maxPrice)}"></div>
      <div class="field-block"><label>${escapeHtml(tr("minWeightLabel"))}</label><input type="number" inputmode="numeric" min="0" step="10" class="sl-min-weight" value="${escapeHtml(form.minWeight)}"></div>
      <div class="field-block"><label>${escapeHtml(tr("maxCaloriesLabel"))}</label><input type="number" inputmode="numeric" min="0" step="10" class="sl-max-calories" value="${escapeHtml(form.maxCalories)}"></div>
    </div>
  `);
  numericSection.querySelector(".sl-max-price").addEventListener("input", (e) => (form.maxPrice = e.target.value));
  numericSection.querySelector(".sl-min-weight").addEventListener("input", (e) => (form.minWeight = e.target.value));
  numericSection.querySelector(".sl-max-calories").addEventListener("input", (e) => (form.maxCalories = e.target.value));
  body.append(numericSection);

  app.append(body);

  const submitBtn = el(`<button type="button" class="primary-button">${escapeHtml(tr("findMyLunch"))}</button>`);
  submitBtn.addEventListener("click", submitSmartLunch);
  app.append(submitBtn);
}

function renderSmartLunchResult() {
  const result = state.smartLunchResult;

  const editRow = el(`<div class="smart-lunch-edit-row"><button type="button" class="link-button">${icon("back", 16)} ${escapeHtml(tr("back"))}</button></div>`);
  editRow.querySelector("button").addEventListener("click", () => {
    state.smartLunchResult = null;
    renderSmartLunch();
  });
  app.append(editRow);

  if (result.options.length === 0) {
    const failure = result.unavailable_constraints[0];
    const reasonText = failure ? tr(SMART_LUNCH_REASON_KEYS[failure.reason] || "reasonGeneric") : "";
    app.append(emptyState("plate", tr("smartLunchNoResultsTitle"), reasonText));
    return;
  }

  for (const option of result.options) {
    const index = result.options.indexOf(option);
    const card = el(`<article class="smart-lunch-option"><p class="option-label">${escapeHtml(tr("smartLunchOptionLabel", { n: index + 1 }))}</p></article>`);

    const grid = el(`<div class="smart-lunch-items"></div>`);
    for (const item of option.items) {
      grid.append(
        el(`
          <div class="smart-lunch-item">
            <p class="name">${escapeHtml(item.name)}</p>
            <p class="meta">${weightText(item) ? escapeHtml(weightText(item)) : ""}${weightText(item) && caloriesText(item) ? " · " : ""}${caloriesText(item) ? escapeHtml(caloriesText(item)) : ""}</p>
          </div>
        `)
      );
    }
    card.append(grid);

    const totalWeightText = option.weight_fully_known && option.total_known_weight_g != null ? `${option.total_known_weight_g} g` : null;
    const totalCaloriesText = option.calories_fully_known && option.total_calories != null ? `${tr("estimated")} ${Math.round(option.total_calories)} ${tr("kcal")}` : null;
    card.append(
      el(`
        <p class="option-totals">
          <strong>€${option.total_price.toFixed(2)}</strong>${totalWeightText ? ` · ${escapeHtml(totalWeightText)}` : ""}${totalCaloriesText ? ` · ${escapeHtml(totalCaloriesText)}` : ""}
        </p>
      `)
    );

    const selectBtn = el(`<button type="button" class="secondary-button">${escapeHtml(tr("selectThisOption"))}</button>`);
    selectBtn.addEventListener("click", () => addSmartLunchOptionToSelection(option));
    card.append(selectBtn);

    app.append(card);
  }

  if (result.matched_constraints.length > 0 || result.unavailable_constraints.length > 0) {
    const summary = el(`<div class="smart-lunch-summary"></div>`);
    if (result.matched_constraints.length > 0) {
      const list = result.matched_constraints.map((c) => escapeHtml(tr(SMART_LUNCH_CONSTRAINT_KEYS[c] || c))).join(", ");
      summary.append(el(`<p class="constraint-note"><strong>${escapeHtml(tr("smartLunchMatchedLabel"))}:</strong> ${list}</p>`));
    }
    if (result.unavailable_constraints.length > 0) {
      const list = result.unavailable_constraints
        .map((c) => `${escapeHtml(tr(SMART_LUNCH_CONSTRAINT_KEYS[c.constraint] || c.constraint))} (${escapeHtml(tr(SMART_LUNCH_REASON_KEYS[c.reason] || "reasonGeneric"))})`)
        .join("; ");
      summary.append(el(`<p class="constraint-note is-unavailable"><strong>${escapeHtml(tr("smartLunchUnavailableLabel"))}:</strong> ${list}</p>`));
    }
    app.append(summary);
  }
}

// ------------------------------------------------------------- Screen: review
//
// This IS the cart: it shows every selected line with quantity/remove
// controls (same as a typical cart screen), plus the delivery-location
// field and confirm action in one place rather than a separate checkout
// step -- there's no real payment/checkout to separate it from (see
// README.md's "no real Restopolis checkout" constraint). What makes it
// a persisted cart rather than just a review step: CART_STORAGE_KEY
// (survives a refresh) and buildTotalsBox()'s server-verified totals
// (never just the client's own arithmetic) below.

// Debounces rapid-fire quantity taps into a single authoritative
// recalculation call instead of one request per tap -- see the
// Performance requirement this was built against.
function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

// Reuses the SAME /api/orders/quote endpoint POST /api/orders itself
// calls (via recalculate_order()) to price/weigh the order at confirm
// time -- not a second, separately-maintained calculation. This is what
// makes the cart's running total authoritative rather than just the
// client-side preview (priceBreakdown()/computeOrderTotals() below),
// matching the task's "never trust the browser for price/weight" rule
// one step earlier than confirm, not just at it.
async function refreshServerQuote() {
  if (state.selection.length === 0 || !state.slug || !state.targetDate) {
    state.serverQuote = null;
    return;
  }
  try {
    const quote = await api("/api/orders/quote", {
      method: "POST",
      body: JSON.stringify({
        restaurant: state.slug,
        date: state.targetDate,
        items: state.selection.map((s) => ({ id: s.menuItemId, quantity: s.quantity })),
      }),
    });
    state.serverQuote = quote;
  } catch {
    // Network hiccup or a line no longer on the live menu -- fall back
    // to the (clearly-marked, see buildTotalsBox) local preview rather
    // than blocking the cart screen on it.
    state.serverQuote = null;
  }
  if (state.screen === "review") {
    const existing = document.querySelector(".totals-box");
    if (existing) existing.replaceWith(buildTotalsBox());
  }
}

const debouncedRefreshServerQuote = debounce(refreshServerQuote, 400);

// Builds the totals box from the server-verified quote when one's
// available (state.serverQuote, shape identical to GET/POST
// /api/orders's `order` -- see serverPriceBreakdown/formatServerPriceTotal
// above, shared with the confirmation screen), falling back to the
// instant local preview (marked "is-unverified") while that request is
// in flight or if it failed.
function buildTotalsBox() {
  if (state.serverQuote) {
    const order = state.serverQuote;
    const totals = order.totals;
    const weightLines = Object.entries(totals.weight_by_unit || {})
      .filter(([, v]) => v > 0)
      .map(([unit, v]) => `<div class="totals-row"><span>${escapeHtml(tr("weight"))} (${unit})</span><span>${v} ${unit}</span></div>`)
      .join("");
    const formula = totals.formula;
    const formulaLine =
      formula.total != null
        ? `<div class="totals-row"><span>${escapeHtml(tr("mealFormula"))} (${formula.formula_count}×)</span><span>€${formula.total.toFixed(2)}</span></div>`
        : formulaReasonText(formula)
        ? `<div class="totals-row"><span></span><span>${escapeHtml(formulaReasonText(formula))}</span></div>`
        : "";
    return el(`
      <div class="totals-box">
        <div class="totals-row"><span>${escapeHtml(tr("items"))}</span><span>${totals.item_count} (${totals.total_quantity})</span></div>
        ${weightLines}
        ${totals.unknown_weight_portions > 0 ? `<div class="totals-row"><span></span><span>${totals.unknown_weight_portions} ${escapeHtml(tr("portionsWithoutWeight"))}</span></div>` : ""}
        ${formulaLine}
        <div class="totals-row grand"><span>${escapeHtml(tr("total"))}</span><span>${formatServerPriceTotal(order)}</span></div>
      </div>
    `);
  }

  const totals = computeOrderTotals(state.selection, menuById());
  const weightLines = Object.entries(totals.weightByUnit)
    .filter(([, v]) => v > 0)
    .map(([unit, v]) => `<div class="totals-row"><span>${escapeHtml(tr("weight"))} (${unit})</span><span>${v} ${unit}</span></div>`)
    .join("");
  const { formula } = priceBreakdown(totals);
  const formulaLine =
    formula.total != null
      ? `<div class="totals-row"><span>${escapeHtml(tr("mealFormula"))} (${formula.formulaCount}×)</span><span>€${formula.total.toFixed(2)}</span></div>`
      : formulaReasonText(formula)
      ? `<div class="totals-row"><span></span><span>${escapeHtml(formulaReasonText(formula))}</span></div>`
      : "";
  return el(`
    <div class="totals-box is-unverified">
      <div class="totals-row"><span>${escapeHtml(tr("items"))}</span><span>${totals.itemCount} (${totals.totalQuantity})</span></div>
      ${weightLines}
      ${totals.unknownWeightPortions > 0 ? `<div class="totals-row"><span></span><span>${totals.unknownWeightPortions} ${escapeHtml(tr("portionsWithoutWeight"))}</span></div>` : ""}
      ${formulaLine}
      <div class="totals-row grand"><span>${escapeHtml(tr("total"))}</span><span>${localizedPriceSummary(totals)}</span></div>
      <p class="verifying-badge">${escapeHtml(tr("verifyingTotals"))}</p>
    </div>
  `);
}

async function renderReview() {
  app.innerHTML = "";
  app.append(header({ title: tr("yourOrder"), subtitle: `${shortName(state.restaurantName)} · ${fmtLong(state.targetDate)}`, back: () => goTo("menu") }));

  if (state.selection.length === 0) {
    app.append(emptyState("cart", tr("yourOrderEmptyTitle"), tr("yourOrderEmptyBody")));
    return;
  }

  const items = menuById();
  for (const sel of state.selection) {
    const item = items.get(sel.menuItemId);
    if (!item) continue;
    const line = el(`
      <div class="review-line">
        <div class="details">
          <p class="name">${escapeHtml(item.name)}</p>
          <p class="meta">${weightText(item) ? `${escapeHtml(weightText(item))} ` : ""}× ${sel.quantity}${item.price != null ? ` · €${(item.price * sel.quantity).toFixed(2)}` : ""}</p>
        </div>
        <div class="line-actions">
          <div class="quantity-stepper">
            <button type="button" aria-label="${escapeHtml(tr("decreaseQuantityOf", { name: item.name }))}">−</button>
            <span class="quantity-value">${sel.quantity}</span>
            <button type="button" aria-label="${escapeHtml(tr("increaseQuantityOf", { name: item.name }))}">+</button>
          </div>
          <button type="button" class="remove-btn" aria-label="${escapeHtml(tr("remove"))}: ${escapeHtml(item.name)}">${escapeHtml(tr("remove"))}</button>
        </div>
      </div>
    `);
    const [decBtn, , incBtn] = line.querySelectorAll(".quantity-stepper button, .quantity-stepper span");
    decBtn.addEventListener("click", () => {
      changeQuantity(item.id, -1);
      goTo("review");
    });
    incBtn.addEventListener("click", () => {
      changeQuantity(item.id, +1);
      goTo("review");
    });
    line.querySelector(".remove-btn").addEventListener("click", () => {
      state.selection = state.selection.filter((s) => s.menuItemId !== item.id);
      state.serverQuote = null;
      saveCart();
      goTo("review");
    });
    app.append(line);
  }

  app.append(buildTotalsBox());
  debouncedRefreshServerQuote();

  const fieldBlock = el(`
    <div class="field-block">
      <label for="delivery-location">${escapeHtml(tr("deliveryLocation"))}</label>
      <input id="delivery-location" type="text" placeholder="${escapeHtml(tr("deliveryLocationPlaceholder"))}" value="${escapeHtml(state.deliveryLocation)}">
    </div>
  `);
  fieldBlock.querySelector("input").addEventListener("input", (e) => {
    state.deliveryLocation = e.target.value;
    saveCart();
  });
  app.append(fieldBlock);

  // Optional -- only used to email the confirmation (Part 23). Campus-
  // only audience, so it's validated against a uni.lu address, same as
  // the backend re-validates on submit (never trusted from the client
  // alone).
  const emailBlock = el(`
    <div class="field-block">
      <label for="customer-email">${escapeHtml(tr("customerEmail"))}</label>
      <input id="customer-email" type="email" inputmode="email" placeholder="${escapeHtml(tr("customerEmailPlaceholder"))}" value="${escapeHtml(state.customerEmail)}">
    </div>
  `);
  emailBlock.querySelector("input").addEventListener("input", (e) => {
    state.customerEmail = e.target.value;
  });
  app.append(emailBlock);

  const confirmBtn = el(`<button type="button" class="primary-button">${escapeHtml(tr("confirmOrder"))}</button>`);
  confirmBtn.addEventListener("click", confirmOrder);
  app.append(confirmBtn);

  const backBtn = el(`<button type="button" class="secondary-button">${escapeHtml(tr("continueBrowsing"))}</button>`);
  backBtn.addEventListener("click", () => goTo("menu"));
  app.append(backBtn);
}

async function confirmOrder() {
  const email = state.customerEmail.trim();
  // Checked here, before the request, rather than only relying on the
  // server's own re-validation: Flask's abort() returns an HTML body
  // for this app's validation errors (no custom JSON error handler),
  // which api()'s error handling can't pull a specific reason out of --
  // this catches it locally with a real, translated message instead of
  // falling back to a generic "Request failed (400)" toast.
  if (email && !isAllowedUniLuEmail(email)) {
    showToast(tr("invalidUniLuEmail"));
    return;
  }

  goTo("confirming");
  try {
    const order = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({
        restaurant: state.slug,
        date: state.targetDate,
        // API selection shape is {id, quantity}; local state uses
        // menuItemId internally (see order-math.js). Map at the boundary.
        items: state.selection.map((s) => ({ id: s.menuItemId, quantity: s.quantity })),
        delivery_location: state.deliveryLocation || null,
        customer_email: email || null,
      }),
    });
    state.confirmedOrder = order;
    clearSavedCart();
    addToOrderHistory(order.id);
    goTo("confirmation");
  } catch (err) {
    showToast(err.message);
    goTo("review");
  }
}

// -------------------------------------------------------- Screen: confirmation

function renderConfirmation() {
  app.innerHTML = "";
  const order = state.confirmedOrder;
  app.append(header({ title: tr("orderConfirmedTitle"), back: () => goTo("restaurants") }));

  const box = el(`
    <div class="totals-box">
      <p class="eyebrow" style="padding:0 0 4px">${escapeHtml(tr("order"))} #${order.id}</p>
      <p style="margin:0 0 8px"><strong>${escapeHtml(order.restaurant_name)}</strong><br>${fmtLong(order.order_date)}</p>
      ${order.delivery_location ? `<p style="margin:0 0 8px">${escapeHtml(tr("deliveryTo"))} ${escapeHtml(order.delivery_location)}</p>` : ""}
      ${
        order.email_sent === true
          ? `<p style="margin:0" class="email-status">${escapeHtml(tr("confirmationEmailSent"))}</p>`
          : order.email_sent === false
          ? `<p style="margin:0" class="email-status is-error">${escapeHtml(tr("confirmationEmailFailed"))}</p>`
          : ""
      }
    </div>
  `);
  app.append(box);

  for (const it of order.items) {
    app.append(el(`
      <div class="review-line">
        <div class="details">
          <p class="name">${escapeHtml(it.name)}</p>
          <p class="meta">${localizedWeightValue(it.weight_value, it.weight_unit) ? `${escapeHtml(localizedWeightValue(it.weight_value, it.weight_unit))} ` : ""}× ${it.quantity}${it.price != null ? ` · €${it.line_price.toFixed(2)}` : ""}</p>
        </div>
      </div>
    `));
  }

  const totals = order.totals;
  const weightLines = Object.entries(totals.weight_by_unit || {})
    .filter(([, v]) => v > 0)
    .map(([unit, v]) => `<div class="totals-row"><span>${escapeHtml(tr("weight"))} (${unit})</span><span>${v} ${unit}</span></div>`)
    .join("");
  const formula = totals.formula;
  const formulaLine =
    formula.total != null
      ? `<div class="totals-row"><span>${escapeHtml(tr("mealFormula"))} (${formula.formula_count}×)</span><span>€${formula.total.toFixed(2)}</span></div>`
      : formulaReasonText(formula)
      ? `<div class="totals-row"><span></span><span>${escapeHtml(formulaReasonText(formula))}</span></div>`
      : "";
  app.append(el(`
    <div class="totals-box">
      <div class="totals-row"><span>${escapeHtml(tr("items"))}</span><span>${totals.item_count} (${totals.total_quantity})</span></div>
      ${weightLines}
      ${totals.unknown_weight_portions > 0 ? `<div class="totals-row"><span></span><span>${totals.unknown_weight_portions} ${escapeHtml(tr("portionsWithoutWeight"))}</span></div>` : ""}
      ${formulaLine}
      <div class="totals-row grand"><span>${escapeHtml(tr("total"))}</span><span>${formatServerPriceTotal(order)}</span></div>
    </div>
    <p style="text-align:center;color:var(--color-text-muted);font-size:0.85rem;padding:0 16px 24px">
      ${escapeHtml(tr("disclaimer"))}
    </p>
  `));

  const doneBtn = el(`<button type="button" class="primary-button">${escapeHtml(tr("backToRestaurants"))}</button>`);
  doneBtn.addEventListener("click", () => {
    state.selection = [];
    state.confirmedOrder = null;
    goTo("restaurants");
  });
  app.append(doneBtn);
}

// ------------------------------------------------------------------ Shared

function header({ title, subtitle, back }) {
  const h = el(`
    <div class="screen-header">
      <button class="back-button" aria-label="${escapeHtml(tr("back"))}">${icon("back", 20)}</button>
      <div>
        <p class="screen-title">${escapeHtml(title)}</p>
        ${subtitle ? `<p class="screen-subtitle">${escapeHtml(subtitle)}</p>` : ""}
      </div>
    </div>
  `);
  h.querySelector(".back-button").addEventListener("click", back);
  return h;
}

function emptyState(iconName, title, body) {
  return el(`
    <div class="empty-state">
      <div class="icon">${icon(iconName, 40)}</div>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(body || "")}</p>
    </div>
  `);
}

function loadingState(label) {
  const d = document.createElement("div");
  d.className = "loading-state";
  d.textContent = label;
  return d;
}

// --------------------------------------------------------------- Router

function render() {
  document.querySelector(".summary-bar")?.remove();
  offScroll(updateCategoryNavHighlight);

  switch (state.screen) {
    case "restaurants":
      renderRestaurants();
      break;
    case "dates-loading":
      app.innerHTML = "";
      app.append(loadingState(tr("checkingAvailability")));
      break;
    case "dates":
      renderDates();
      break;
    case "menu-loading":
      app.innerHTML = "";
      app.append(loadingState(tr("loadingMenu")));
      break;
    case "menu":
      renderMenu();
      break;
    case "review":
      renderReview();
      break;
    case "confirming":
      app.innerHTML = "";
      app.append(loadingState(tr("confirmingOrder")));
      break;
    case "confirmation":
      renderConfirmation();
      break;
    case "favorites":
      renderFavorites();
      break;
    case "order-history":
      renderOrderHistory();
      break;
    case "smart-lunch":
      renderSmartLunch();
      break;
    case "profile":
      renderProfile();
      break;
    default:
      renderRestaurants();
  }

  renderBottomNav();
}

async function init() {
  applyLanguage();
  setInterval(tickStatusClock, 30000);
  app.append(loadingState(tr("loadingRestaurants")));
  try {
    await loadRestaurants();
  } catch (err) {
    app.innerHTML = "";
    app.append(emptyState("warn", tr("couldNotReachServerTitle"), err.message));
    return;
  }

  goTo("restaurants");
}

init();
