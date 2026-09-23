# Restopolis menu collector

Scrapes and normalizes menus from the official Restopolis site
(https://ssl.education.lu/eRestauration/CustomerServices/Menu) for two
University of Luxembourg Campus Kirchberg restaurants:

- `UDL-CKB - Altius - Restaurant`
- `UDL-CKB - Brasserie John's - Restaurant`

Scope of this first version is collection only: no ordering, payment,
accounts, or delivery/courier logic.

## 1. Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dependencies (`requirements.txt`): `requests`, `beautifulsoup4`, `PyYAML`,
`pytest`. No browser automation (Playwright) is used — see §3 for why.

## 2. Dependencies

- **requests** — HTTP client with a persistent cookie-jar session.
- **beautifulsoup4** — HTML parsing.
- **PyYAML** — loads `restaurants.yaml`.
- **pytest** — test runner.

## 3. How Restopolis menu selection actually works

This was determined by inspecting the live site's network requests and
HTML (cookies, redirects, forms), not by assumption or by copying an old
parser unverified. Summary (see `restopolis/client.py` and
`restopolis/parser.py` docstrings for the full detail):

1. **No JSON/XHR API.** The whole week's menu is server-rendered HTML.
   There is no `fetch`/XHR call that returns menu data — a claim we
   verified by watching the network tab while switching restaurant/date in
   a real browser session: the only requests were page navigations and two
   small AJAX calls (`UpdateDate`, see point 4) that return no menu data.
   Plain `requests` is therefore sufficient; **Playwright/JS execution is
   not needed**.

2. **Restaurant selection** is a plain `GET` with a query parameter:
   ```
   GET /eRestauration/CustomerServices/Menu/BtnChangeRestaurant?pRestaurantSelection=<id>
   ```
   This sets two cookies, `CustomerServices.Restopolis.SelectedRestaurant`
   and `...SelectedService`, and starts a `CustomerServices.Session`
   cookie that anchors all further server-side state for that session.

3. **Language** (which controls the category/dish text language) is
   likewise a cookie set by a plain GET:
   ```
   GET /eRestauration/CustomerServices/Menu/BtnChangeLanguage?pNewLanguage=fr
   ```
   sets `.AspNetCore.Culture=c=fr|uic=fr`. We scrape in French because the
   category names Restopolis itself uses in French (`Entrée`,
   `Végétarien`, `Végan`, `Non-végétarien`, `Féculents`, `Légumes`,
   `Dessert`, `Snack à emporter`) are the ones this project's spec uses as
   canonical category names to preserve as-is.

4. **Date selection is week-based, not day-based, and only current-week-
   onward is reachable.** The Menu page always renders **all 7 days**
   (Mon–Sun) of one week in a single response, inside a `slick.js`
   carousel — all days' data is already in the HTML, none of it is loaded
   lazily. Which *week* is shown is controlled by two more plain GETs:
   ```
   GET /eRestauration/CustomerServices/Menu/NextWeek
   GET /eRestauration/CustomerServices/Menu/PreviousWeek
   ```
   Each shifts a week-offset stored server-side against the
   `CustomerServices.Session` cookie. We verified experimentally (see
   commit history / this investigation) that:
   - `NextWeek` is cumulative and unbounded going forward (tested up to 2
     weeks ahead; further weeks presumably just render "no products
     scheduled" until Restopolis publishes them).
   - `PreviousWeek` is **clamped at the real-world current week** — you
     cannot navigate to a week before today's. This means **past menus
     are not retrievable from this site at all**, by design (there's
     nothing to reserve for a date that has passed). The scraper detects
     a requested `--date` before the current week and refuses to
     fabricate an answer (see §11 below).
   - A separate endpoint, `POST /Menu/UpdateDate` with a JSON body
     `{"dateAsString": "DD.MM.YYYY"}`, exists but only changes which day
     tab is cosmetically active within the already-loaded week — it does
     **not** change what data is returned by a subsequent GET, so the
     scraper does not use it at all.

   The cookie `CustomerServices.Restopolis.SelectedDate` you can find
   referenced (commented out) in the page's own JavaScript is a red
   herring: the client-side code explicitly does **not** set it
   (`//Cookies.set(cookieNames.SelectedDate, strDate);` is commented out
   in the shipped script), confirming date state lives server-side only.

5. Putting it together, `restopolis/client.py`'s `fetch_week_html`:
   `BtnChangeLanguage` → `BtnChangeRestaurant` → `NextWeek` × N →
   `GET /Menu`, all on one fresh `requests.Session` per (restaurant, week)
   fetch, so there's no cross-request/cross-restaurant state bleed.

## 4. Restaurant & service ids

Verified against the live site on 2026-09-23 (see `restaurants.yaml` for
how, and run `python scraper.py discover` to re-verify at any time):

| Code | Name | `restaurant_id` | `service_id` |
|---|---|---|---|
| `UDL-CKB-ALTIUS` | UDL-CKB - Altius - Restaurant | 164 | 1183 |
| `UDL-CKB-BRASSERIE-JOHNS` | UDL-CKB - Brasserie John's - Restaurant | 160 | 178 |

Both restaurants are part of site id `30354` ("Université de Luxembourg
Campus Kirchberg"). Each restaurant exposes exactly one lunch service,
"Service 11:00 - 14:30" (Altius) / similar hours (Brasserie John's), plus
a permanent, day-independent "Produits constants" (constant products)
list — mostly sandwiches — that Restopolis renders identically on every
day's slide.

`python scraper.py discover` re-parses the live restaurant picker (the
same dropdown a human user searches in the top of the page) and flags any
mismatch against `restaurants.yaml`, so a future renumbering by
Restopolis is caught rather than silently producing wrong data.

## 5. Running the scraper

```bash
# Both restaurants, today
python scraper.py

# Both restaurants, one date
python scraper.py --date 2026-09-24

# One restaurant
python scraper.py --restaurant altius --date 2026-09-24
python scraper.py --restaurant brasserie-johns --date 2026-09-24

# Date range (inclusive)
python scraper.py --from 2026-09-21 --to 2026-09-25

# Only write JSON (skip SQLite)
python scraper.py --date 2026-09-24 --format json

# Only write SQLite (skip JSON)
python scraper.py --date 2026-09-24 --format sqlite

# Re-verify restaurant ids against the live site
python scraper.py discover
```

Other flags: `--db PATH` (default `restopolis.db`), `--json-out PATH`
(default `data/menus.json`), `--raw-dir PATH` (default `data/raw`),
`--no-constant-products` (skip the sandwich list, keep only the daily
formula), `-v/--verbose` (DEBUG logging).

Requests are spaced ~1s apart with exponential-backoff retries on
transient errors (see §12), to stay polite to the server; a multi-week
range therefore takes a few seconds per week per restaurant.

## 6. Database schema (`restopolis.db`)

```
restaurants(id, code UNIQUE, name, restaurant_id, service_id, created_at, updated_at)
menus(id, restaurant_id -> restaurants.id, menu_date, service_name, service_time,
      source_url, scraped_at, UNIQUE(restaurant_id, menu_date, service_name))
menu_items(id, menu_id -> menus.id, category, name, description, price,
           allergens_json, dietary_json, raw_text, sort_order,
           UNIQUE(menu_id, category, name, sort_order))
```

Re-running the scraper for a (restaurant, date, service) already in the
DB does **not** duplicate rows: `upsert_daily_menu` upserts the `menus`
row, then deletes and re-inserts its `menu_items` in one transaction.
Delete+reinsert (rather than a plain per-item upsert) was chosen
deliberately: if a dish is removed from Restopolis between two scrapes, a
naive "insert or ignore" would leave a stale row forever, whereas
delete+reinsert makes the DB match the site exactly on every run.

`service_name` is either `"Menu"` (the daily formula: Entrée, Végétarien,
Végan, Non-végétarien, Féculents, Légumes, Dessert, Snack à emporter) or
`"Constant products"` (the permanent sandwich/snack list), so a consumer
can filter to just the daily formula if they don't want the ~100-item
constant list repeated every day.

## 7. Example output (`data/menus.json`)

```json
{
  "generated_at": "2026-09-23T12:56:54.272287+00:00",
  "restaurants": [
    {
      "code": "UDL-CKB-ALTIUS",
      "name": "UDL-CKB - Altius - Restaurant",
      "menus": [
        {
          "date": "2026-09-24",
          "service": "Menu",
          "service_time": "11:00-14:30",
          "source_url": "https://ssl.education.lu/eRestauration/CustomerServices/Menu",
          "items": [
            {
              "category": "Entrée",
              "name": "Salad'bar",
              "description": null,
              "price": null,
              "allergens": [
                {"code": 3, "name": "Œufs", "detail": null},
                {"code": 7, "name": "Lait", "detail": null}
              ],
              "dietary": ["vegetarian", "non_vegetarian"],
              "source": "Restopolis"
            }
          ]
        }
      ]
    }
  ]
}
```

`price` is always `null`: Restopolis's public menu page never renders a
price for these restaurants (confirmed: no `price`/`prix`-related class
anywhere in the fetched HTML). Allergen codes 1–14 are the EU 1169/2011
Annex II major allergens, mapped in `restopolis/allergens.py`; the
optional `detail` is Restopolis's own free-text refinement (e.g. which
cereal exactly contains the gluten). Dietary/origin flags (`vegetarian`,
`vegan`, `non_vegetarian`, `gluten_free`, `sugar_free`, `organic`,
`fairtrade`, `luxembourg`, `greater_region`, `benelux`) are mapped in
`restopolis/flags.py`, read directly off the page's own icon legend.

## 8. Known limitations

- **Past dates are unavailable.** Restopolis's own `PreviousWeek`
  navigation is clamped at the current week server-side; there is no way
  to retrieve a menu for a date before today's week from this site. The
  scraper detects this and reports it clearly (exit code 1, `[ERROR]`
  log line) rather than returning an empty/fake menu.
- **Future dates depend on Restopolis having published that far ahead.**
  Weeks far in the future will parse successfully but every day will
  come back as "no products scheduled" until the restaurant actually
  publishes that week's menu.
- **Day↔date mapping is positional.** The raw per-day HTML block inside
  the `.menu-slider` carousel carries no date attribute of its own
  (`data-slick-index` is added by `slick.js` client-side, not present in
  the server response); the parser aligns the Nth day block with the Nth
  `#date-selector` entry and raises `MenuParseError` if the two lists
  don't have the same length, rather than silently mis-mapping dates.
- **"Constant products" repeats verbatim on every day** (by Restopolis's
  own design), which means storing it per-date multiplies its ~100 items
  by 7 for a full week. Use `--no-constant-products` if you only want the
  daily formula.
- No price data is available from this page at all (see §7).
- Only the two Campus Kirchberg restaurants are configured; add more
  entries to `restaurants.yaml` (ids found via `python scraper.py
  discover`) to extend.

## 9. If Restopolis changes its HTML

The parser (`restopolis/parser.py`) fails loudly instead of guessing:

- If `#date-selector a.day` is missing, or `.menu-slider` is missing, or
  their day-counts don't match 1:1, it raises `MenuParseError` with a
  specific message rather than returning a partial/empty result.
- If a `.product-name` has no preceding `.course-name`, the item is kept
  (category `"Unknown"`) and a `[WARN]` is logged, rather than dropping
  the dish.
- If the restaurant name isn't found on the loaded page at all
  (`RestaurantSelectionError` in `client.py` / `MenuParseError` in
  `parser.py`), the restaurant id in `restaurants.yaml` is probably
  stale — run `python scraper.py discover` to find the new id and update
  `restaurants.yaml`.

To adapt the parser to a markup change: re-run `python scraper.py
--date <today> -v`, inspect the freshly saved `data/raw/<date>/<slug>.html`,
diff it against `tests/fixtures/*.html`, and update the CSS selectors in
`restopolis/parser.py` (`.course-name`, `.product-name`,
`.product-allergens`, `.product-flag`, `.product-description`,
`.formulaeContainer`, `.constantProductContainer`) accordingly. Then
refresh the fixtures and re-run the tests.

## 10. Tests

```bash
pytest -v
```

`tests/fixtures/altius_week0.html` and `tests/fixtures/brasserie_johns_week0.html`
are real HTML captured from the live site (2026-09-23), used so parser
tests never depend on network access. Coverage includes: restaurant
discovery (`test_discovery.py`), CLI date/restaurant selection logic
(`test_scraper.py`), menu/category/dish parsing including the apostrophe-
in-name HTML-entity edge case, allergen and dietary-flag extraction,
vegetarian/vegan detection, weekend "no products" handling, malformed/
missing-field handling (`test_parser.py`), and SQLite upsert / duplicate
prevention (`test_database.py`).

---

# Part 2: Dynamic orderability engine

Answers, from **live Restopolis data only** (never a hardcoded weekly
schedule): "Can I order from Altius for 2026-09-24?" This is intentionally
a separate layer on top of Part 1 -- no delivery routing, no payment, no
real Restopolis order placement yet.

## 11. The Restopolis mechanism this is built on

Investigated live (2026-09-23) the same way as Part 1: watching real
requests/cookies/HTML, not assuming anything from old parsers. Two
findings drive the whole engine:

**1. Restopolis has a real, independent "can I reserve this day" signal.**
Every day-slide has an `.action-buttons` region with either:

```html
<!-- ordering CLOSED for this date -->
<button disabled="disabled">Réservation clôturée</button>

<!-- ordering OPEN for this date -->
<button onclick="window.location.href='/eRestauration/CustomerServices/saml/login
  ?returnUrl=%2f...%2fRedirectToReservationView%3fRestaurantId%3d164%26ServiceId%3d1183%26Date%3d24.09.2026'">
  Réserver
</button>
```

The enabled link goes through a SAML login we can't complete anonymously,
so we never actually place a reservation -- but the button's
presence/enabled state is itself the public signal, and it was verified to
be **genuinely independent of menu content**: on 2026-09-23, Mon–Wed
(already-passed days that week) showed a real menu with `Réservation
clôturée` (menu YES, ordering NO), while the following Sat/Sun showed no
menu at all with `Réserver` enabled (menu NO, ordering YES). This is
exactly why the engine reports `menu_available` and `ordering_available`
as two separate fields rather than inferring one from the other.

**2. Restopolis's own booking window is a narrow, rolling one, discovered
empirically, not configured.** On 2026-09-23 (Wednesday), ordering was
open only for Thu–Mon (a 5-calendar-day-ahead rolling window) and closed
for every other date in the entire 6-week browsable horizon (see Part 1
§3 for `NextWeek`/`WeekOutOfRangeError`, which also clamps *forward*, not
just backward -- discovered while building this part). The engine never
hardcodes "N days ahead" anywhere; `orderability_engine/detector.py`
re-reads the button on every check.

No cutoff **time** is exposed anywhere in the public HTML (no title,
`aria-*`, or `data-*` attribute near the button carries one) -- so
`order_deadline` (Restopolis's own deadline) is always reported as `null`.
If Restopolis ever adds one, it goes in `orderability_engine/detector.py`'s
`_read_reservation_signal`.

## 12. Status decision table

`orderability_engine/service.py` computes `status` purely from the two
signals above (see its module docstring for the exact rationale):

| menu_available | ordering_available | status |
|---|---|---|
| — | before current week | `past_date` |
| — | beyond the browsable horizon, or fetch/parse failed | `unknown` |
| `None` (signal unreadable) | `None` | `unknown` |
| `False` | `False` | `closed` |
| `True` | `False` | `ordering_closed` |
| `False` | `True` | `no_menu` |
| `True` | `True` | `available` |

`not_yet_published` is a recognized status value (`orderability_engine/models.py`)
but the engine **never emits it automatically**: Restopolis's public page
gives no way to tell "this weekday's menu just isn't uploaded yet" apart
from "this restaurant doesn't serve here" -- both look like `no_menu`.
Inventing that distinction would be exactly the kind of guessing the task
says not to do. `unknown` is always used instead of a guessed `closed` or
`available` whenever a signal can't be read, the site can't be reached,
or the date falls outside what Restopolis will show us at all.

## 13. OUR delivery rule vs. Restopolis's own signal

`orderability_engine/delivery_rules.py` computes a completely separate
`our_delivery.deadline` (08:00 Europe/Luxembourg on the target date
itself, the SAME day -- superseded from an earlier v1 rule of 08:30 the
day before, see Part 20) and `our_delivery.available`. The two are
never merged: a result can be `status: "available"` (Restopolis says
yes) with `our_delivery.available: false` (our own cutoff already
passed) -- exactly the task's §12 example, reproduced live (numbers
updated for the current same-day rule):

```
Restaurant: Altius, Date: 2026-09-24
Restopolis: ordering_available = true
Our deadline: 2026-09-24 08:00 Europe/Luxembourg
Checked at:  2026-09-24 08:15 (after the deadline)
-> status: "available", our_delivery.available: false
```

`our_delivery.available` additionally requires Restopolis's own
`menu_available` and `ordering_available` to both be `true` -- the engine
never promises a delivery Restopolis itself wouldn't allow.

## 14. Architecture

```
restopolis/client.py (Part 1)
        |
orderability_engine/detector.py     -- reads menu_available / ordering_available
        |                              / service times straight off the page
orderability_engine/cache.py        -- per (restaurant, date) SQLite cache, TTL + --refresh
        |
orderability_engine/service.py      -- OrderabilityService: status decision table,
        |                              change-[CHANGED]-detection, get_next_available_dates
        |
orderability_engine/delivery_rules.py -- OUR same-day 08:00 rule, kept structurally separate
        |
orderability_engine/menu_service.py -- loads the actual dish list (Part 1's parser)
        |                              once a date is confirmed "available"
        |
orderability_engine/orders.py       -- internal order bookkeeping (no payment)
        |
app.py (Flask)                    -- JSON API + /admin/orderability + customer UI
orderability.py                   -- CLI
```

`OrderabilityService` also keeps a short-lived **in-process** cache of raw
week HTML (separate from the persistent per-date SQLite cache): several
dates in the same week share one Restopolis fetch instead of each
re-running the whole `language -> restaurant -> NextWeek*N -> Menu`
sequence. This was a real, measured problem while building
`get_next_available_dates` (a naive per-date fetch made a 5-result scan
take minutes); see `OrderabilityService.get_week_html`.

**Note on the package name**: the engine's Python package is called
`orderability_engine/`, not `orderability/`, even though the CLI script
is `orderability.py`. Python resolves `import orderability` to a
same-named *package* over a same-named *module* in the same directory --
naming the package `orderability/` would have silently shadowed the CLI
script for anything trying to import it (this was caught by `tests/test_orderability_cli.py`
failing, not by inspection).

## 15. CLI

```bash
python orderability.py --restaurant altius --date 2026-09-24
python orderability.py --restaurant altius --date 2026-09-24 --refresh
python orderability.py --restaurant brasserie-johns --date 2026-09-26
python orderability.py --restaurant altius --next-available --count 5
python orderability.py --restaurant altius --date 2026-09-24 --json
```

`--json` writes only the JSON to stdout (all `[CHECK]`/`[RESTOPOLIS]`/
`[OUR RULE]`/`[RESULT]` logging goes to stderr, so it's pipeable). Exit
code is `1` when the final status is `unknown`, `0` otherwise.

## 16. Caching, `--refresh`, and change detection

Every `check_orderability` call first looks in `orderability.db`'s
`orderability_cache` table (15-minute TTL by default, `--cache-ttl` /
`cache_ttl_seconds` to change it). `--refresh` bypasses it and forces a
live Restopolis check -- but even then, the previous cached value is
still read first (via `get_raw`, ignoring expiry) purely so a genuine
change can be logged:

```
[CHANGED]
UDL-CKB-ALTIUS
2026-09-24
service_end:
14:30 -> 13:30
```

`_CHANGE_TRACKED_FIELDS` in `orderability_engine/service.py` lists what's
compared (menu/ordering availability, service times, item count).

## 17. API

```
GET  /api/restaurants
GET  /api/restaurants/<slug>/status?date=YYYY-MM-DD[&refresh=true]
GET  /api/restaurants/<slug>/available-dates?count=5
GET  /api/restaurants/<slug>/menu/<date>          (409 if that date isn't "available")
POST /api/orderability/check   {"restaurant": "altius", "date": "...", "refresh": false}
POST /api/orders               {"restaurant": "altius", "date": "...", "items": [...], "delivery_location": "..."}
```

Example (matches the task's own spec example):

```
GET /api/restaurants/altius/status?date=2026-09-24
```
```json
{
  "restaurant": "UDL-CKB - Altius - Restaurant",
  "date": "2026-09-24",
  "restopolis": {
    "open": true,
    "menu_available": true,
    "ordering_available": true,
    "service_start": "11:00",
    "service_end": "14:30",
    "order_deadline": null
  },
  "our_delivery": {
    "deadline": "2026-09-23T08:30:00+02:00",
    "available": false
  },
  "status": "available",
  "reason": null,
  "checked_at": "2026-09-23T15:11:15.230579+02:00",
  "from_cache": false
}
```

`restopolis.order_deadline` is `null` rather than a fabricated time (see
§11); `our_delivery.available` is `false` here because the check happened
after 08:30 that day, even though Restopolis itself still allows ordering.

## 18. Admin debug page & customer UI

`GET /admin/orderability` -- a plain HTML table, both restaurants x the
next 10 days, showing Restopolis's open/menu/ordering signals, our
deadline, the final status, and whether the row came from cache.

Customer flow: `/` (restaurant picker) -> `/order/<slug>` (date picker,
each date showing its real status -- available/closed/no_menu/unknown are
never hidden or glossed over) -> `/order/<slug>/<date>` (menu, loaded via
Part 1's parser, only rendered as orderable when `status == "available"`;
otherwise shows the reason) -> submits to an internal `orders` table (no
payment, no Restopolis order placed) -> confirmation page.

Run it:

```bash
python app.py   # http://localhost:5050
```

This is Flask's development server (`debug=True`, single-threaded) --
fine for this task's scope, not meant for production traffic. SQLite
connections are opened with `check_same_thread=False` since the dev
server can dispatch requests on a different thread than the one that
opened the connection; this is safe only because the dev server
processes requests sequentially, not concurrently.

## 19. Known limitations

- **`not_yet_published` is unimplemented** by design -- see §12. It's a
  valid value in `orderability_engine/models.py.STATUS_VALUES` for any
  future signal that lets it be distinguished from `no_menu`.
- **No Restopolis-exposed cutoff *time*.** `order_deadline` is always
  `null`; only the binary open/closed button state is public.
- **`restaurant_open` is coarse.** Restopolis's page never states "this
  restaurant is closed" as a distinct fact from "no menu today" -- it's
  `true` whenever Restopolis returned data for that restaurant/date at
  all (i.e. the id still resolves and the date is in range), `null`
  (unknown) otherwise. It is never fabricated as `false`.
- **`get_next_available_dates` can return fewer than `count` results.**
  Given the real ~5-day rolling reservation window found live, there can
  be as few as 2-3 genuinely `available` dates in the *entire* ~6-week
  horizon at any moment -- returning fewer than requested, honestly, is
  correct behavior here, not a bug.
- **Dev server only** (`app.py`); no auth, no concurrency hardening, no
  production WSGI server -- out of scope for this task.
- Only the two Campus Kirchberg restaurants are wired into the Flask app
  and CLI (`restaurants.yaml`, shared with Part 1).

## 20. Testing (orderability engine)

```bash
pytest tests/test_orderability_*.py tests/test_delivery_rules.py tests/test_orders.py tests/test_app.py -v
```

All of it runs against fixtures/fakes, never the live site:
`tests/fixtures/altius_week0.html` (real capture, covers 3 of the 4
menu/ordering signal combinations) plus `tests/fixtures/altius_closed_week.html`
(synthetic -- see `tests/fixtures/generate_closed_week_fixture.py` -- for
the 4th: menu absent *and* ordering closed, which didn't occur in the
live capture's week). `tests/orderability_helpers.FakeRestopolisClient`
stands in for network access, including a `fail=True` mode for simulating
a Restopolis outage/timeout, and a `max_weeks_ahead` mode for simulating
the horizon clamp. Coverage: all 7 status values reachable given the
signals that justify them, the horizon-vs-closed distinction, network
failure -> `unknown` (never `closed`/`available`), our-deadline-vs-
Restopolis-deadline interaction, caching + `--refresh`, change-detection
logging, `get_next_available_dates` (including graceful early stop at the
horizon), Europe/Luxembourg timezone arithmetic, and the full Flask API +
customer UI + admin page via `app.test_client()`.

---

# Part 3: Mobile food selection UI

A mobile-first customer app for picking dishes with weight/portion
awareness, on top of Parts 1-2. Still no payment, no delivery routing, no
real Restopolis order placement.

## 21. Whether Restopolis exposes weight/price at all (read this first)

Checked directly against the live fixture before writing any UI code:
**the daily "Menu" formula (Entrée/Végétarien/Végan/Non-végétarien/
Féculents/Légumes/Dessert -- the categories this task's own examples use)
has zero price data and zero weight data, for every item, every day.**
Confirmed two ways: no `€`/price markup anywhere on the page (Part 1 §7),
and a regex scan of all 62 formula items that week found 0 with a
weight/volume pattern in the name.

Where portion size genuinely exists is "Constant products" (the permanent
sandwich/drink/snack list) -- there it's embedded directly in the product
**name** text (e.g. `"Bretzel salé 80 g"`, `"Coca Cola 0,20 l btl"`), not a
separate field; 350 of 714 Constant products items had a parseable
weight/volume, the rest (mostly plain sandwiches, coffee, cutlery) simply
don't state one. See `restopolis/weight.py`'s module docstring for the
full breakdown and exact regex.

Two consequences for this task, both deliberate:
- **The customer menu includes Constant products alongside the daily
  formula** (`orderability_engine/menu_service.get_customer_menu`), not
  just the formula. Restricting to the formula alone would make the
  weight feature permanently untestable with real data -- every card
  would say "Portion size not specified" and success criterion #4
  ("every dish displays its weight when available") would never be
  demonstrable.
- **`price` is `null` for essentially every real item.** The UI never
  fabricates a price -- see §26.

## 22. Weight parsing (`restopolis/weight.py`)

`parse_weight(name) -> (value, unit)` extracts a trailing `number + unit`
pattern (`g`, `kg`, `ml`, `l`, `cl` -> converted to `ml`, or `pièce`/`pc`
-> `piece`), handling French decimal commas (`"0,20 l"` -> `0.2`) and
picking the right-most match when a name has more than one number (e.g.
`"Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)"` correctly extracts
`130 ml`, not a flavor-list false positive). It never modifies or strips
the matched text from the name -- `"Bretzel salé 80 g"` stays that exact
string in `MenuItem.name`, so nothing is lost if the extraction is ever
wrong; the weight badge is additional, not a replacement.

Deliberately does **not** guess: `"Lët'z kola 0,33 btl"` is real data
where `0,33` is almost certainly liters, but the text never says so, so
`parse_weight` returns `(None, None)` rather than inferring a unit. Every
extraction was checked by hand against all 102 unique real Constant
products names (`tests/test_weight.py`) before wiring it in.

`MenuItem` (Part 1's model) gained `weight_value`/`weight_unit` fields,
populated by `restopolis/parser.py` the same way allergens/dietary flags
already were; `restopolis/database.py` and `restopolis/exporter.py` carry
the two new columns/fields through.

## 23. Data model / API changes

- `MenuItem.weight_value: float | None`, `.weight_unit: str | None` (Part 1).
- `menu_items` table: `weight_value REAL`, `weight_unit TEXT` (Part 1 DB).
- `GET /api/restaurants/<slug>/menu/<date>`: now returns the combined
  Menu + Constant products list, each item with a response-stable `id`
  (sequential, re-derived fresh from the live menu on every request --
  never trusted from a stale client cache), `weight_value`, `weight_unit`,
  `weight_display` (pre-formatted, e.g. `"80 g"` / `"Portion size not
  specified"`), plus the existing category/name/description/price/
  allergens/dietary/vegetarian/vegan fields. Also returns `max_quantity`.
- `POST /api/orders/quote` (new): recalculates totals server-side from a
  `{restaurant, date, items: [{id, quantity}]}` body **without** creating
  an order -- used for authoritative on-demand totals if a client wants
  them without submitting.
- `POST /api/orders`: request shape changed from Part 2's
  `items: [{category, name, price, ...}]` (client-supplied) to
  `items: [{id, quantity}]` -- see §26 for why. Response now includes
  `totals` (see §25).
- `orders`/`order_items` tables: `order_items` gained `weight_value REAL`,
  `weight_unit TEXT`.

## 24. Files created / changed

```
restopolis/weight.py                    NEW  weight/volume parser
restopolis/models.py                    MenuItem + weight_value/weight_unit
restopolis/parser.py                    wires parse_weight() into item extraction
restopolis/database.py                  + weight columns
restopolis/exporter.py                  + weight fields in JSON export

orderability_engine/menu_service.py     + flatten_menu_items(), get_customer_menu()
orderability_engine/orders.py           + recalculate_order(), aggregate_totals(),
                                         OrderValidationError, MAX_QUANTITY;
                                         + weight columns/fields; + threading.Lock
                                         (see §27)
orderability_engine/cache.py            + threading.Lock (see §27)

app.py                                  /api/restaurants/<slug>/menu/<date> rewritten;
                                         + POST /api/orders/quote; POST /api/orders
                                         rewritten for server-side recalculation;
                                         old Jinja customer routes (/order/...) removed
                                         and replaced by the "/" SPA shell

templates/mobile.html                   NEW  SPA shell (viewport meta, #app mount)
templates/dates.html, menu.html,        REMOVED (Part 2's server-rendered flow,
  confirmation.html, restaurants.html            superseded by the SPA)
templates/admin.html, base.html         unchanged (Part 2's debug page)

static/order-math.js                    NEW  pure calculation functions (see §25)
static/app.js                           NEW  the SPA itself (screens, fetch, state)
static/app.css                          NEW  mobile-first design system

tests/test_weight.py                    NEW
tests/test_app.py                       rewritten for the new API shape
tests/test_orders.py                    + recalculate_order/aggregate_totals tests
tests_js/order-math.test.mjs            NEW  Node test suite (no browser needed)
```

## 25. Weight/price calculation -- client preview vs. backend authority

Both `static/order-math.js` (`computeOrderTotals`) and
`orderability_engine/orders.py` (`aggregate_totals`) implement the exact
same rule, deliberately kept in sync:

- `line_weight = weight_value × quantity` (the task's own example: 250 g
  × 2 = 500 g); `line_price = price × quantity`. Either is `null`/`None`
  if the underlying value is unknown -- **never silently treated as 0**.
- **Weight is summed per unit**, never flattened into one number. A
  caught-in-review bug in this exact task: my first draft summed
  `weight_value` across all selected items regardless of unit, so
  "250 g + 0.2 l" would have silently become a meaningless "250.2". Real
  orders genuinely mix g (food) and ml/l (drinks) in the same basket, so
  totals are `{"g": 600, "ml": 500}`, not a single figure.
- Unknown portions are counted separately (`unknown_weight_portions`,
  `unknown_price_portions`) and surfaced explicitly -- e.g. the summary
  bar/review screen render `"600 g + 2 unknown"`, matching the task's own
  `"650 g + 1 unknown"` example, never a falsely-precise total.

**The frontend calculation is a preview only.** `static/app.js`'s summary
bar and review screen use `order-math.js` purely so the UI feels instant
while the user is still tapping. The moment "Confirm order" is pressed,
the browser sends only `{id, quantity}` pairs -- never a price, weight,
or name -- and `app.py` re-fetches the live menu and calls
`recalculate_order()` server-side (§26), storing and returning *that*
result. The two are expected to agree because both read the same rule,
but if Restopolis's data changed between page-load and confirm, the
server's numbers are what's actually stored.

## 26. Never trust the browser (§27/§28 of the task)

`POST /api/orders`'s request body only ever contains `{id, quantity}`
selections (plus an optional free-text `delivery_location`) -- there is
no price/weight/name field for a client to send even if it wanted to.
`orderability_engine/orders.recalculate_order(menu_items, selection)`:

1. Re-fetches the live menu for that (restaurant, date) server-side.
2. Looks up each selected `id` in that live list (raises
   `OrderValidationError` -> HTTP 400 if the id doesn't exist -- e.g. the
   menu changed, or a stale/tampered id was sent).
3. Validates `1 <= quantity <= MAX_QUANTITY` (10; `OrderValidationError`
   otherwise).
4. Computes every line's price/weight from the **server's** copy of that
   item, never anything the client sent.

`app.py`'s order-creation handler also re-runs `check_orderability` at
confirm time (not just when the menu page first loaded), so a date that
became unavailable in between is caught too (409, not a created order).
Covered directly: `tests/test_orders.py`'s
`test_recalculate_order_ignores_client_supplied_price_uses_server_price`
and `tests/test_app.py`'s `test_create_order_ignores_any_price_client_tries_to_send`.

## 27. A concurrency bug this task's live verification caught

Driving the actual app in a browser (not just the API test suite) reproduced
a real `sqlite3.InterfaceError: bad parameter or other API misuse`: the
restaurant-picker screen fires two parallel `fetch()` calls (one status
check per restaurant), and Flask's dev server dispatched them
concurrently onto two threads that both touched the same
`sqlite3.Connection` object at once. `check_same_thread=False` (added in
Part 2) only relaxes the "created in a different thread" check -- it does
not make one connection safe for *concurrent* use from multiple threads.
Fixed by adding a `threading.RLock()` around every method of
`OrderabilityCache` and `OrderStore` that touches `self._conn`. This is
exactly the kind of bug that only shows up under real concurrent access,
not in sequential API tests -- worth keeping in mind before pointing
anything beyond the dev server at this code.

## 28. Running it / mobile preview

```bash
python app.py   # http://localhost:5050
```

Open on an actual phone, or in a desktop browser's device toolbar at
375/390/430px width. The food grid is 1 column under 640px, 2 from
640px, 3 from 1024px (bounded by the page's own 720px max content width,
so "3 columns" means three ~220px cards, not three huge ones -- a
deliberate readability choice, not a bug).

## 29. Known limitations

- **Portion selection (§11 of the task) is implemented but structurally
  unreachable with real data.** `flatten_menu_items` always returns
  `portions: []` because Restopolis exposes no priced size variants for
  any dish (no price data at all -- see §21). The frontend code path for
  rendering `item.portions` exists and is exercised by nothing but its
  own absence; per the task's explicit "do NOT create portion sizes if
  Restopolis does not provide them," this was not faked to make a demo
  screenshot look more complete.
- **`price` is `null` almost everywhere**, for the same reason. Every
  price-bearing UI element (food card, summary bar, review, confirmation)
  has a tested "Price not available" / "N unpriced" path, since that is
  the actual common case with this data, not an edge case.
- **The date picker's first load can take up to ~1 minute uncached.** It
  checks 10 calendar days individually (so unavailable days show their
  real reason, see §21 of Part 2 and §20 of the task); each uncached day
  in a not-yet-fetched week costs a full Restopolis round trip. Repeat
  visits within the 15-minute cache TTL are fast. A tighter
  `max_days_to_scan` or a batched multi-day endpoint would improve this;
  out of scope for what this task asked for.
- No routing/URL state: the SPA is a single in-memory screen stack (no
  browser back-button support, no shareable/deep-linkable URLs). Adding
  `history.pushState` would be the natural next step.
- Dev server only (Flask `debug=True`), same caveat as Part 2.

## 30. Testing

```bash
pytest tests/test_weight.py tests/test_orders.py tests/test_app.py -v
node --test tests_js/order-math.test.mjs
```

129 Python tests + 22 Node tests, all passing. Split by what each layer
is actually responsible for:
- **`restopolis/weight.py`** (`tests/test_weight.py`): parsing correctness
  against real names, including the "don't guess" cases.
- **`orderability_engine/orders.py`** (`tests/test_orders.py`): the
  authoritative recalculation -- per-unit weight summing, quantity
  multiplication, unknown-portion tracking, id/quantity validation,
  client-price-is-ignored.
- **`static/order-math.js`** (`tests_js/order-math.test.mjs`, plain
  Node, no browser/build step required): the identical local-preview math,
  so a regression here would show up as the summary bar disagreeing with
  the confirmed order.
- **`app.py`** (`tests/test_app.py`, `Flask.test_client()`): the API
  contract -- weight/id fields on the menu response, 409s for
  unavailable dates, 400s for invalid selections, server-side
  recalculation ignoring client data, the SPA shell route.
- **Live browser verification** (not an automated suite, but actually
  driven end-to-end against the real Restopolis-backed server this
  session, screenshots kept in the session transcript): restaurant
  selection with real per-restaurant status, the full day range showing
  disabled days with real reasons, menu loading with real weight/allergen/
  dietary data, select/deselect, quantity +/-, the sticky summary bar's
  live per-unit weight math, the review screen, order confirmation with
  server-recalculated totals, and the empty-state copy for a real
  `no_menu` date. This is also how the §27 concurrency bug and the
  `menuItemId`-vs-`id` field-name mismatch bug (fixed in
  `confirmOrder()`) were actually found -- neither was caught by the
  Python or Node test suites, since both only exercise one side of the
  frontend/backend boundary at a time.

---

# Part 4: Language selector (top 10 languages)

Localizes the app's own UI chrome -- not Restopolis's menu data, which is
never translated, per the same rule Part 1 §5 already established for
category names ("do not translate the raw category names... frontend can
display them exactly as supplied") and now applies equally to the
selector: dish names, categories, allergen names, and service times
always render exactly as the API returned them, in whatever language
Restopolis itself used, regardless of which UI language is selected.

## 31. The 10 languages

English, Mandarin Chinese, Hindi, Spanish, French, Standard Arabic,
Bengali, Portuguese, Russian, Urdu -- the 10 most-spoken languages
worldwide by total speakers (native + second-language), a commonly cited
ranking (Ethnologue/Berlitz-style lists). This is a global ranking, not
one built from this university's actual enrollment mix, since no such
breakdown was available to go on; `static/i18n.js`'s `LANGUAGES` array is
the single place to swap it for a different list if one becomes
available.

## 32. What's localized vs. what never is

| Localized (our own UI) | Never localized (Restopolis data) |
|---|---|
| Screen titles, buttons, labels | Dish names |
| Empty-state titles/messages | Category names (Entrée, Végétarien, ...) |
| Status chips (OPEN / CLOSED / ...) | Allergen names |
| Quantity/selection aria-labels | Service times |
| Weekday/month names (via `Intl.DateTimeFormat`) | Restaurant names (Altius, Brasserie John's) |

The one exception that needs calling out: `weight_display` and the
`"Portion size not specified"` string are formatted **server-side**
(`restopolis/weight.py`'s `format_weight`), always in English, because
the backend has no notion of a UI language. The frontend never trusts
that literal string for the "unspecified" case -- `static/app.js`'s
`weightText()`/`localizedWeightValue()` re-derive it from `tr()` instead,
using the raw `weight_value`/`weight_unit` fields (which stay
language-neutral SI-style abbreviations, e.g. `"80 g"`, in every
language, matching common practice for unit abbreviations).

## 33. Implementation

- `static/i18n.js`: `LANGUAGES` (code, native-script label, BCP-47 locale
  tag, `rtl` flag for Arabic/Urdu), a `translations` dict (~50 keys ×10
  languages), and `t(lang, key, vars)` -- looks up the string, falls back
  to English then to the raw key (so a missing translation is visible,
  never a crash), and does `{placeholder}` substitution plus a simple
  `"singular | plural"` split on a literal count of 1 vs. other (not full
  ICU plural rules -- languages with more than two plural forms, e.g.
  Arabic or Russian, use one general form; a deliberate simplification for
  a handful of counted strings like "N items").
- Preference persisted via `localStorage` (per-viewer convenience,
  wrapped in try/catch for private-mode/blocked-storage), read once at
  startup by `getLanguage()`.
- Weekday/month names use `Intl.DateTimeFormat(locale, {...})` rather
  than hand-maintained name arrays per language -- correctness (and
  correct digit systems, e.g. Arabic-Indic numerals for `ar`) comes from
  the browser's own locale data instead of ten more hand-translated
  arrays that could drift out of sync with the rest of the UI.
- The selector itself (`renderLangBar()`) renders into `#lang-bar`, a
  container that lives in `templates/mobile.html` **outside** `#app`.
  Screen transitions do `app.innerHTML = ""` on every navigation (see
  Part 3's router); putting the selector outside that subtree is what
  keeps it visible and usable on every screen instead of only the
  restaurant-picker.
- RTL (Arabic, Urdu): `document.documentElement.dir` is set to `rtl`/`ltr`
  on every language change, plus a handful of explicit `[dir="rtl"]`
  overrides in `static/app.css` (the back-button glyph swaps `←`/`→` in
  JS rather than via CSS mirroring, since mirroring the character inside
  a circular button visually rotates the whole glyph instead of just
  flipping its direction).

## 34. Verified live (not just unit-tested)

`tests_js/i18n.test.mjs` (10 Node tests, no browser needed) checks the
structural stuff a runtime bug wouldn't be obvious from a screenshot:
every one of the 10 languages has the exact same key set as English (so
switching language can't silently blank out a string), placeholder
substitution, the plural split, and the English/key fallback chain.

What that suite can't check -- actual rendering, RTL layout, and that
Restopolis data really does stay untouched -- was driven live in the
browser at mobile width (375px): switched through English, French, and
Arabic; in Arabic, confirmed the whole screen mirrors correctly (back
arrow points right, the language dropdown moves to the top-left, category
tabs and quantity stepper read right-to-left) while `Entrée`/
`Végétarien`/`Non-végétarien` (Restopolis's own French category names),
the dish names, and the allergen names stay exactly as scraped, in French,
untouched by the Arabic UI around them; selected an item and confirmed
the summary bar ("١ صنف · ١ غير معروف", "١ بدون سعر") and quantity
stepper work correctly under RTL too. Dates rendered with correct
Arabic-Indic numerals and Arabic weekday/month names purely from
`Intl.DateTimeFormat` -- no hand-translated date table to get wrong.

## 35. Files added / changed

```
static/i18n.js              NEW  LANGUAGES, translations (10 langs), t(), getLanguage()/setLanguage()
static/app.js                every hardcoded UI string replaced with tr(...); Intl.DateTimeFormat-based
                              date formatting (replacing hand-written DOW/MONTH arrays); renderLangBar();
                              RTL back-button glyph; localized weight/price summary wrappers that keep
                              order-math.js itself language-neutral
static/app.css               #lang-bar styling; [dir="rtl"] overrides
templates/mobile.html        + #lang-bar container (outside #app)
tests_js/i18n.test.mjs       NEW  10 Node tests
```

## 36. Known limitations

- Not full ICU pluralization (see §33) -- acceptable for the ~6 counted
  strings in this UI, would need a proper plural-rules library for a
  larger app.
- Translations are AI-produced for these ~50 short, standard app-UI
  phrases (not reviewed by native speakers); they were not sourced from
  or verified against Restopolis/university material, since none was
  translated by this project's own scope. Fine for demonstrating the
  selector; a production rollout would want native review, especially
  for Arabic/Urdu/Bengali/Hindi where a subtler phrasing error is harder
  for a non-speaker maintaining this code to catch later.
- No language auto-detection from `navigator.language`; the selector
  always starts at English (or the viewer's last `localStorage` choice).

---

# Part 5: Translating categories and allergens accurately (dish names stay raw)

Follow-up refinement: Part 4 originally left category headers and
allergen names untranslated along with dish names, on the reasoning that
Part 1 §5 said "frontend can display them exactly as supplied." On
reflection (and per explicit direction), that was overly blunt: category
headers and allergen names are not arbitrary Restopolis prose the way a
dish name is -- they're drawn from small, closed, verifiable vocabularies,
so translating them is a real lookup against a checked list, not a guess.
Dish names (and descriptions, and an allergen's dish-specific "detail"
text) remain untranslated, since those genuinely are arbitrary free text
with no fixed vocabulary to check against.

## 37. What changed

- **Categories**: pulled every `.course-name` string out of both real
  fixtures and confirmed they're **the same 25 exact strings for both
  restaurants** (8 daily-formula categories + 17 Constant Products
  categories, e.g. `"Végétarien"`, `"01.1 Sandwiches végétariens"`,
  `"12.2 Emballages et articles à usage unique"`). `static/i18n.js`'s
  `CATEGORY_LABELS` translates exactly those 25, in all 10 languages.
  Any category Restopolis adds later that isn't in the table falls back
  to the raw French string (`categoryLabel()`) rather than disappearing
  or being mistranslated.
- **Allergens**: translated by numeric **code** (1-14), against the same
  EU 1169/2011 Annex II list `restopolis/allergens.py` already uses as
  its French source of truth -- a legally standardized enumeration, not
  a translation guess. `allergenLabel()` falls back to Restopolis's own
  (French) `name` if a code is ever unmapped, then to a bare `"code N"` --
  the same never-drop-data fallback chain the backend already uses.
- **Never translated**: dish names, descriptions, and an allergen's
  dish-specific `detail` text (e.g. "Blé, Orge, Épeautre" -- which
  cereal exactly). These stay exactly as Restopolis wrote them, in
  whatever language Restopolis used, regardless of UI language.

## 38. Verified

- `tests_js/i18n.test.mjs` grew 11 tests: exact counts (25 categories, 14
  allergen codes) so a typo'd/duplicate key would fail loudly, full
  10-language coverage for both tables, correct lookups, the "falls back
  to raw text for anything unmapped" behavior, and an explicit assertion
  that `allergenLabel()` never leaks the free-text `detail` field into
  its translated output. Full suite: 129 Python + 43 Node, all passing.
- Live in the browser, in Chinese: category tabs and section headers
  translated (前菜/素食/纯素食/非素食/...), allergen list translated
  (过敏原：蛋类 · 大豆 · 奶制品 · 芹菜 · 芥末 · 二氧化硫和亚硫酸盐), while
  the dish names on the same cards -- `Salad'bar`, `Soupe de pommes de
  terre`, `Aloo palak au tofu` -- stayed exactly as Restopolis wrote
  them, untouched.

## 39. Files changed

```
static/i18n.js         + CATEGORY_LABELS (25 categories x10), ALLERGEN_LABELS (14 codes x10),
                          categoryLabel(), allergenLabel()
static/app.js           category-nav buttons, category-section headers, and the allergen
                          line now go through categoryLabel()/allergenLabel(); category-nav
                          scroll-highlighting keyed off the raw category (data-cat) again,
                          not the now-translated visible text
tests_js/i18n.test.mjs  + 11 tests (completeness + lookup + fallback + detail-not-leaked)
```

---

# Part 6: Real meal-formula pricing (OUR OWN rule, not Restopolis)

Real, current pricing was supplied directly for the University of
Luxembourg Campus Kirchberg canteen: a **flat-rate meal-formula** scheme,
not per-dish prices --

```
main dish alone                     EUR 3.70
main dish + starter (Entrée)        EUR 4.20
main dish + starter + dessert       EUR 5.20
```

This is exactly the kind of data Part 3 §21 said didn't exist on
Restopolis's public page and would have to come from the university
directly if wanted -- it now has. It's implemented as **our own pricing
rule**, kept structurally separate from Restopolis's own (still always
`null`) per-dish price, the same pattern Part 2 already established for
the 08:30 delivery deadline vs. Restopolis's own (also always-null)
deadline. Restopolis's per-dish `price` field is untouched and still
`None`/`null` everywhere -- this is an additional, clearly-labeled
`formula` total alongside it, never a fabricated per-dish number.

## 40. The rule

- **Main dish categories** (pick one, or more for multiple meals):
  `Non-végétarien`, `Végétarien`, `Végan`.
- **Starter**: `Entrée`. **Dessert**: `Dessert`.
- **Bundled free with any main, never separately priced**: `Féculents`
  (starches), `Légumes` (vegetables) -- their food cards show
  `"Included"` instead of `"Price not available"`, since that's now a
  known fact, not an unknown.
- Constant Products / `Snack à emporter` (sandwiches, drinks, pastries)
  are **not part of the formula** at all and stay unpriced -- no price
  for those was given either.
- Only the 3 given combinations are priced. A combination outside them
  (most notably: main + dessert with **no** starter -- the 3 tiers are
  strictly progressive, main -> +starter -> +starter+dessert, never
  main -> +dessert) is **not guessed** at the nearest tier. It returns a
  `reason` code (`"no_main_dish"` or `"dessert_without_starter"`,
  translated for display, never raw English prose baked into the data)
  instead of a fabricated total -- the same "don't invent it" rule this
  whole project has followed for Restopolis data, now applied to this
  one too.
- Quantity: `formula_count` = total quantity of main-dish items in the
  order; the tier applies uniformly to all of them (documented v1
  simplification -- see §43).

## 41. Where it lives

- **`orderability_engine/pricing.py`** (new): `compute_formula_total()`,
  the single source of truth, called server-side from
  `orderability_engine/orders.py`'s `aggregate_totals()` (so it's in both
  `recalculate_order()`'s response and `get_order()`'s stored-order
  read-back -- i.e. both the POST /api/orders/quote preview and the
  confirmed order use the exact same authoritative calculation).
- **`static/pricing.js`** (new): the identical logic mirrored in JS
  (same tiers, same fallback behavior) for the client-side live preview,
  the same client/server split already used for weight math
  (`static/order-math.js`) and enforced the same way: the browser's copy
  is a preview only, `POST /api/orders` never trusts client-sent prices
  (see Part 3 §26) -- it re-derives the formula from the server's own
  live menu fetch every time.
- **`static/app.js`**: food cards show `"Included"` for bundled sides;
  the summary bar, review screen, and confirmation screen all show the
  formula price as its own line (`"Meal formula (N×): €X.XX"`), with any
  non-formula priced/unpriced items (Constant Products) shown separately
  -- never summed into one number that would misrepresent which part is
  a real per-dish price and which is the flat-rate meal price.
- **`static/i18n.js`**: `mealFormula`, `included`,
  `formulaReasonNoMainDish`, `formulaReasonDessertWithoutStarter` added
  in all 10 languages.

## 42. Verified live

Walked the actual mobile UI end to end (screenshots kept in the session
transcript): selecting just the main dish showed **€3.70** in the summary
bar; adding a starter updated it live to **€4.20**; adding a dessert to
**€5.20** -- all three matching the given prices exactly. The review
screen showed a dedicated `"Meal formula (1×): €5.20"` line. Confirming
the order round-tripped through the real backend
(`POST /api/orders` -> SQLite -> `get_order()`), and the confirmation
screen showed the same **€5.20**, computed independently server-side --
not just echoed back from the client's request body.

## 43. Tests

`tests/test_pricing.py` (11) + `tests/test_orders.py` (+3 integration
tests) + `tests_js/pricing.test.mjs` (10) = 24 new tests, all passing
(full suite: 143 Python + 53 Node). Covers: all 3 real tiers with their
exact prices, Féculents/Légumes never changing the tier, no-main-dish and
dessert-without-starter both correctly refusing to guess (with the right
reason code), Constant Products staying outside the formula, quantity
multiplication, multiple different main dishes summed together, the
per-dish `price` field never leaking into (or being conflated with) the
formula total, and the formula surviving a full create-order ->
store -> read-back round trip unchanged.

## 44. Known limitations (v1 simplifications, documented rather than guessed around)

- **Tier is order-wide, not per-meal, when multiple mains are ordered.**
  Two main dishes + one starter + zero desserts is priced as **2 ×
  main+starter** (`has_starter`/`has_dessert` are order-wide booleans,
  not matched one-for-one against each main). This is _a_ defensible
  reading of "2 plates, both with a starter" but not the only possible
  one; it was not confirmed against a real multi-plate order, so it's
  flagged here rather than silently assumed correct.
- No quantity discount/cap logic (e.g. a per-person daily limit) --
  purely a per-unit tier price times quantity.
- Prices are stored as source-of-truth constants
  (`orderability_engine/pricing.py` / `static/pricing.js`), not fetched
  from anywhere -- if the canteen changes them, both files need updating
  together (there is no single shared config file for this yet).

## 45. Approximate calorie estimates (Part 7)

Restopolis exposes **zero** nutrition/calorie data anywhere on the public
Menu page (verified: zero occurrences of "kcal", "calor", "nutrit",
"energ", "kJ" in the raw HTML, for both restaurants). Per this feature's
own ground rule -- never invent a number with no basis -- calories are
only ever estimated from two real things:

1. A dish's **real, Restopolis-scraped weight** (`weight_value`/
   `weight_unit`, Part 3). Without a known weight there's nothing to
   multiply a density by, so no estimate is produced.
2. A **public nutritional-science reference**: approximate calorie
   density (kcal per 100 g/ml) for common food types, the same kind of
   generic figures a standard calorie-counting app uses for an unbranded
   "grilled chicken" or "boiled potatoes" entry.

The food *type* itself is guessed from the dish's raw French name via
keyword matching against that reference table -- inherently approximate.
Every result is therefore always flagged `is_estimated: true` and
rendered with a **"≈ estimated"** prefix, never as a precise or
Restopolis-sourced fact. Items with no known weight, a "piece"-only
weight (no reliable typical mass), or an unmatched name render **no**
calorie line at all -- unlike weight/price, an absent estimate isn't
called out as "not available" on every card.

### Where it lives

- **`orderability_engine/nutrition.py`** (new): `estimate_calories()` /
  `classify_food_type()`, the single source of truth, wired into
  `orderability_engine/menu_service.py`'s `flatten_menu_items()` so every
  item in the `/api/restaurants/<slug>/menu/<date>` response carries
  `calories` / `calories_food_type` / `calories_estimated`.
- **`static/nutrition.js`** (new): the identical table and matching logic
  mirrored in JS for the client-side card display -- same client/server
  split as weight math and pricing (Parts 25-26, 39-41): the backend
  computes it server-side and the frontend only renders what the API
  already returned, it does not recompute a client-trusted estimate.
- **`static/app.js`**: `caloriesText()` renders `"≈ estimated N
  Calories"` on food cards when present, nothing when absent.
- **`static/i18n.js`**: `calories`, `estimated`, `nutritionNotAvailable`
  added in all 10 languages.

### Matching is whole-word, not substring -- three real bugs caught by validating against live data

An earlier version matched keywords as plain substrings and produced
concrete wrong results once checked against the real fixture
(`tests/fixtures/altius_week0.html`) and the live site:

- **"Cornet Luxlait"** / **"Dame Blanche Luxlait"** (ice cream, brand
  "Luxlait") matched the "lait" (milk) keyword because "lait" is a
  substring of "Luxlait" -- classified as plain milk instead of ice
  cream.
- **"Rosport mat Menthe"** (mint-flavoured water) matched the "the" (tea)
  keyword because "the" is a substring of "Menthe".
- **"Mini fromage frais..."** (fresh cheese, ~90 kcal/100g) matched the
  generic "fromage" (hard cheese, 350 kcal/100g) keyword, overstating
  calories by 4x.

Fixed by matching whole words/phrases only (regex `\b...\b`) instead of
naive substrings, picking the **longest** matching keyword on a tie (so
"fromage frais" beats "fromage", "yaourt" beats "fruit" in "Yaourt aux
fruits"), and -- since ties of equal length are still possible, e.g. a
flavor word like "fraise" next to a dish-type word like "cornet" in
"Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille)" -- listing dish-type
keywords (ice cream, pastry) ahead of generic fruit/vegetable keywords in
the table so the dish's actual type wins that tie. A fourth case, **"Fuze
Tea ... Pêche/Hibiscus"** (iced tea, peach flavor) matching "fruit"/
"peche" instead of tea, was fixed by adding longer, more specific
beverage-brand keywords ("fuze tea", "black tea") that outrank the
shorter flavor word by length alone. All four are regression-tested
(see Tests below) so table edits can't silently reintroduce them.

### Verified live

Ran the live mobile UI (Altius, Thu Sep 24 2026 menu): Coca Cola 0.2l /
0.5l showed **≈ estimated 84 / 210 Calories**; Fuze Tea Pêche/Hibiscus
0.2l showed **≈ estimated 80 Calories** (correctly classified as iced
tea, not fruit); Cornet Luxlait 130ml and Dame Blanche Luxlait 200ml
showed **≈ estimated 260 / 400 Calories** (correctly ice cream, not
milk). Daily-formula dishes (no Restopolis weight data) correctly showed
no calorie line at all. Switched language to French: label read **"≈
estimé N Calories"**, confirming the i18n keys resolve correctly.

### Tests

`tests/test_nutrition.py` (13) + `tests_js/nutrition.test.mjs` (13) = 26
new tests, all passing (full suite: 156 Python + 66 Node). Covers: no
weight -> no estimate, "piece" unit -> no estimate (no reliable typical
mass), unmatched name -> no estimate, a known match's exact kcal value,
liter-to-gram conversion, water at 0 kcal (still flagged estimated), and
regression tests for all four classification bugs above plus the
longest-match tie-break rule in general.

### Known limitations

- Only French dish names are covered by the keyword table (matches
  Restopolis's own source-language text -- Part 6/31 established that
  dish names themselves are never translated).
- The food-type classifier is keyword-based and will miss or misjudge
  unusual/compound dish names it has no keyword for -- it returns no
  estimate rather than a wrong one in that case, but a *matched* estimate
  can still be off for an atypical dish within a matched category (e.g.
  an unusually lean or fatty cut of the same meat type).
- No per-ingredient breakdown or macro (protein/fat/carb) data -- calorie
  count only, and only ever a single point estimate, never a range.

## 46. Persisted cart with backend-verified totals (Part 8)

The existing "review" screen already functioned as a cart (per-line
quantity/remove controls, running totals) -- Part 8 makes it a *real*
one: it survives a page refresh, and its running total is confirmed by
the backend, not just the client's own arithmetic, one step before
confirm rather than only at it.

### Backend recalculation reuses the existing endpoint

`POST /api/orders/quote` already existed (Part 3) for exactly this --
recalculate price/weight server-side from a `{id, quantity}` selection
without creating an order -- but nothing in the frontend called it; the
cart screen only ever showed its own client-side preview
(`static/order-math.js` / `static/pricing.js`) until now. `static/app.js`
now calls it from the cart screen itself (`refreshServerQuote()`,
debounced 400ms so rapid quantity taps collapse into one request), and
renders its response (`buildTotalsBox()`) in place of the local preview
once it resolves -- reusing the exact same rendering helpers
(`serverPriceBreakdown()`/`formatServerPriceTotal()`) already used for
the confirmation screen's authoritative totals, not a second
implementation. No new backend code was needed for this half of the
feature: the endpoint, and its underlying `recalculate_order()`, are
unchanged.

Every selection change (quantity +/-, remove) immediately invalidates
the cached server quote (`state.serverQuote = null`) so a stale
authoritative-looking number is never shown after an edit -- the totals
box instantly falls back to the (clearly marked `is-unverified`, dashed
border, "Verifying…" badge) local preview until the debounced request
resolves and replaces it.

### Cart persistence survives a refresh, safely

There's no auth/account system (out of scope, see README intro), so the
cart is persisted to `localStorage` (`uniresto.cart.v1`) instead of
server-side, updated on every selection/delivery-location change and
cleared once an order is actually confirmed.

The one real design risk here: `menu_service.flatten_menu_items()`'s own
docstring says item `id`s are "stable within one response" **only** --
the backend re-derives them fresh from the live menu on every fetch. A
page refresh triggers exactly that kind of fresh fetch, so persisting
and blindly replaying raw ids across it could silently select the
*wrong* dish (an id reused for a different item after a menu reorder) or
drop a still-valid one. The cart is therefore persisted keyed by
`(category, name)`, not by raw id: on restore, `tryRestoreCart()`
re-fetches the live menu for the saved (restaurant, date), re-validates
each saved line against it by that key, and drops (with a toast
explaining how many) anything no longer on the live menu -- the same
"never trust a stale id, always re-validate against the live menu"
principle the other Phase-1-adjacent features (Reorder, Favorites) are
planned to follow.

### Where it lives

- **`static/app.js`**: `CART_STORAGE_KEY`/`saveCart()`/`loadSavedCart()`/
  `clearSavedCart()`/`tryRestoreCart()` (persistence); `debounce()`/
  `refreshServerQuote()`/`buildTotalsBox()` (backend-verified totals);
  `init()` now checks for a saved cart before falling back to the
  restaurant list.
- **`static/i18n.js`**: `continueBrowsing` (renamed from the old
  `backToMenu` button), `verifyingTotals`, `cartItemsUnavailable` added
  in all 10 languages.
- **`static/app.css`**: `.totals-box.is-unverified` / `.verifying-badge`
  for the local-preview state; a `flex-wrap` fix for `.totals-row.grand`
  (see Verified live below -- a real, previously-latent layout bug this
  work newly exercised).
- No backend changes: `POST /api/orders/quote` and
  `orderability_engine/orders.py` are unchanged, reused as-is.

### Verified live

Added a starter (Salad'bar) and a main (Aloo palak au tofu, ×2) to the
cart on Altius/Thu Sep 24 2026; `read_network_requests` confirmed real
`POST /api/orders/quote` round trips (200 OK) firing on each change, and
the cart correctly showed the server-computed **€8.40** (main+starter
tier ×2). Reloaded the page mid-cart: the cart survived intact (same two
items), confirming the (category, name) re-validation restore path
against a live re-fetched menu. Confirmed the order: the confirmation
screen showed the same €8.40, and `localStorage.getItem("uniresto.cart.v1")`
returned `null` immediately after -- the cart clears on confirm, it
doesn't linger as a stale "ghost" cart for the next visit.

While testing, live data surfaced a genuine (pre-existing, just not
previously exercised this early) layout bug: the grand-total row's
`Total` label and a long unpriced-reason sentence ("Select a main dish
to see the meal price") rendered squeezed together with no visible gap
(`flex-wrap: nowrap` + `justify-content: space-between` degrades to no
spacing at all once content overflows the row). Fixed with `flex-wrap:
wrap` plus a small gap on `.totals-row.grand`; verified the fix directly
against the live squeezed case before adding the second cart item.

### Known limitations

- Single active cart only -- persistence is keyed globally, not per
  restaurant/date, so starting a new selection elsewhere overwrites (via
  `saveCart()`) rather than merges with a previous one. Matches the
  app's existing one-restaurant-at-a-time flow; multi-cart support was
  not requested.
- The debounced server quote can occasionally show a brief `-unverified`
  local-preview flash even for a correct, already-priced selection
  (e.g. right after `renderReview()` mounts, before the first debounced
  request resolves) -- intentional (never show a number as verified
  before it actually is), not a bug.
- A restored cart whose restaurant/date is no longer orderable (closed,
  past the ordering deadline, etc.) is silently dropped rather than
  shown with an explanation -- `tryRestoreCart()` falls back to the
  restaurant list in that case. Flagged rather than fixed here since it
  would need a new UI state this phase didn't otherwise require.

## 47. Food filters (Part 9)

Filters over the already-fetched menu: category, dietary (vegetarian/
vegan), allergens-to-avoid, weight, and calories. Deliberately built as
client-side visibility filtering over the one menu payload the app
already fetches per (restaurant, date) -- not a new backend endpoint --
since the real dataset (a single day's menu at one of two restaurants)
is already delivered whole in that one call, and re-fetching per filter
toggle would add latency for no benefit. Nothing about what's filterABLE
is invented: every filter's OPTIONS (which categories exist, which
allergens are even present today) are derived from that same real
response, never a fixed hardcoded list -- so a filter chip only ever
appears for something actually on today's menu.

### Weight and calories are bucketed, not raw numbers, and only for comparable items

A per-dish price filter was deliberately **not** built: `item.price` is
essentially always `null` on real Restopolis data (Part 3/25 -- there is
no per-dish price, only the order-level meal-formula system from Part
6), so a numeric price filter would be structurally present but
functionally inert on every real menu today, which would misleadingly
imply per-dish pricing exists. Rather than ship a filter that silently
never does anything on real data, it was left out and documented here.

Weight and calories, by contrast, ARE real per-item values (Parts 3 and
7) -- but not universally comparable ones: weight comes in g/ml/l/piece,
and calories are only ever estimated for gram-weighed items with a
matched food-type keyword. Both filters are therefore small fixed
buckets (Under/Over/between, in grams or kcal) rather than a free-form
number range, and -- critically -- an item that ISN'T comparable in that
dimension (a drink measured in ml when a gram-bucket is active, a dish
with no calorie estimate when a calorie-bucket is active) is **excluded
when a specific bucket is selected**, never silently guessed into one.
This is surfaced to the user (a small note under the bucket chips, e.g.
"Only applies to weighed items (grams)"), not just done quietly --
verified live: selecting "Starter" + "Under 100 g" together correctly
dropped to **0 results**, because Altius's two starters that day
(Salad'bar, Soupe de pommes de terre) both have unspecified portion
sizes, not because anything was wrongly excluded.

### Where it lives

- **`static/filters.js`** (new): `itemMatchesFilters()`/`filterItems()`
  (the matching logic), `availableCategories()`/`availableAllergens()`
  (option derivation from the real menu), `activeFilterCount()`. Pure,
  no DOM access -- unit-tested directly under Node
  (`tests_js/filters.test.mjs`), same pattern as pricing.js/nutrition.js.
- **`static/app.js`**: `filterBar()` (the "Filters" button + active-count
  badge), `filterSheet()` (the bottom-sheet panel), wired into
  `renderMenu()` so category nav/sections are built from the *filtered*
  item list -- a category with nothing currently visible doesn't show an
  empty nav button or section (verified live: excluding Milk removed
  both Starter items, and "Starter" disappeared from the category nav
  entirely, not just its cards). Filters reset on every new date
  selection (`selectDate()`), matching the pattern already used for
  `state.selection`.
- **`static/i18n.js`**: `filters`, `categoryFilter`, `dietaryFilter`,
  `allergensToAvoid`, the 8 weight/calorie bucket labels + their 2 notes,
  `clearFilters`, `showResults`, `noResultsTitle`/`noResultsBody` added
  in all 10 languages.
- **`static/app.css`**: `.filter-bar`/`.filter-button`/`.filter-count`,
  `.filter-sheet-overlay`/`.filter-sheet`/`.chip` (the bottom sheet and
  its toggle chips).
- No backend changes: filtering never touches `/api/restaurants/<slug>/
  menu/<date>` or any other endpoint, it only decides what to render
  from the response already in hand.

### Verified live

Opened Altius/Thu Sep 24 2026's menu (114 items): the Filters sheet
listed every real category (Starter, Vegetarian, Vegan, ... 10.1 Cold
drinks, etc.) and every real allergen present that day (Gluten, Eggs,
Peanuts, Soybeans, Milk, Tree nuts, Celery, Mustard, Sesame, Sulphites)
-- nothing hardcoded, all pulled from the live response. Selecting
"Starter" correctly narrowed to 2 results; adding "Under 100 g" on top
correctly went to 0 (an honest result, not a bug -- see above). Excluding
"Milk" narrowed 114 -> 71 results and, once applied, both real Starter
items (which both list Milk) disappeared and the "Starter" chip itself
vanished from the category nav. "Clear all" correctly reset to 114/114
and restored the original category list.

### Known limitations

- Bottom sheet only -- no separate persistent desktop sidebar. This
  app's shell (`#app`) is a single centered column at every viewport
  width (`--max-content-width`, Part 3), so there's no wide-screen
  two-pane layout for a sidebar to attach to yet; that's scoped into the
  later full UI-redesign pass (see the Phase roadmap), not built as a
  one-off here.
- No numeric price filter -- see above; would be structurally present
  but functionally inert on all real data today.
- The filter sheet re-renders fully on every toggle (same pattern
  `renderReview()`'s quantity buttons already use), so its own internal
  scroll position resets to the top on each tap rather than staying put
  -- a minor, pre-existing-pattern UX cost, not unique to this feature.
- Dietary/weight/calories/allergen filter options are computed from
  every item on the day's menu (`state.menu.items`), not just the
  currently-visible (already-filtered) subset -- so, for example, an
  allergen chip stays selectable even after a category filter would
  otherwise hide every item containing it. This is deliberate (letting a
  user widen one dimension without first having to guess which other
  filter is hiding it) but means the sheet's chip list doesn't shrink as
  other filters narrow the results.

## 48. Food search (Part 10)

A persistent search box above the Filters button on the menu screen,
composing (AND) with active filters -- same "narrow what's already
fetched" approach as filters.js, for the same reason (Part 47): the
whole day's menu for one restaurant is already client-side after one
fetch, so search never re-fetches or hits a new endpoint.

Matches against the dish name, its description, and its category --
both the RAW Restopolis category string and its current-language
translated label. This split matters: dish names and descriptions are
never translated (arbitrary free text, no fixed vocabulary -- Part 5),
so they're matched exactly as Restopolis wrote them, in whatever
language that is. Categories, by contrast, ARE a small closed
vocabulary that's already translated everywhere else in the app
(CATEGORY_LABELS, Part 5/31) -- so searching the English word "starter"
correctly finds "Entrée" items via its translated label, without
requiring the user to know or type the raw French category name.
Verified live: typing "starter" in the English UI narrowed Altius's menu
to the Entrée category exactly as "Starter" would via the filter chip.

Normalization (case-insensitive, accent-insensitive) reuses the same
NFKD-decompose-and-strip-combining-marks technique already established
in Part 7's nutrition matching -- verified live: "porc" correctly
matched "Rôti de porc Orloff, jus lié" despite the accent difference.

### Where it lives

- **`static/search.js`** (new): `normalizeText()`, `itemMatchesQuery()`,
  `searchItems()`. Deliberately decoupled from `static/i18n.js` (no
  import of `categoryLabel`), matching `filters.js`'s separation -- the
  caller passes in the already-translated category label per item
  rather than this module reaching for the translation itself. Pure, no
  DOM access -- unit-tested directly under Node
  (`tests_js/search.test.mjs`).
- **`static/app.js`**: `searchBar()` (the input + clear button),
  `rerenderMenuPreservingSearchFocus()` + `debouncedSearchRerender()`
  (250ms debounce reusing the same `debounce()` helper the cart's
  server-quote fetch already uses, Part 46), wired into `renderMenu()`
  alongside `filterItems()` so category nav/sections reflect the
  combined search+filter result. `state.searchQuery` resets on every new
  date selection, same as `state.filters`.
- **`static/i18n.js`**: `searchPlaceholder`, `clearSearch`,
  `noSearchResultsTitle` (`"No dishes match “{query}”"`, with
  each language's own quotation convention -- e.g. `« »` for
  French), `noSearchResultsBody` added in all 10 languages.
- **`static/app.css`**: `.search-bar`/`.search-input`/`.search-clear`.
- No backend changes, same reasoning as Part 47.

### A real UX problem this surfaced: losing focus mid-typing

`renderMenu()` rebuilds the whole screen (`app.innerHTML = ""`) on every
call -- fine for button/chip toggles, but re-running it on every
debounced search keystroke would tear down and recreate the `<input>`
itself, silently dropping keyboard focus and cursor position out from
under the user's typing the moment the debounce fires. Fixed by
explicitly saving whether the search input had focus (and its cursor
position) immediately before the re-render and restoring both right
after (`rerenderMenuPreservingSearchFocus()`) -- verified live: typing
continuously into the search box kept the flashing focus ring and
correct cursor position across the debounced re-renders instead of
dropping out mid-word.

### Verified live

On Altius/Thu Sep 24 2026 (114 items): "porc" narrowed to exactly
"Rôti de porc Orloff, jus lié"; "starter" (translated-category match)
narrowed to the two Entrée items; a gibberish query ("xyzzy123")
correctly showed the search-specific empty state (`No dishes match
"xyzzy123"`) rather than the generic filters one, with a working
"Clear all" that reset both the query and any active filters back to
the full 114-item menu.

### Known limitations

- Search is restricted to the currently selected restaurant/date's
  already-fetched menu, not a cross-restaurant or cross-date search --
  matches this app's existing one-restaurant-at-a-time flow (same scope
  boundary as Cart, Part 46).
- Allergen names are not part of the search index (only name/
  description/category) -- out of the originally scoped fields; adding
  it would be a small, low-risk follow-up (allergenLabel() already
  exists and could be passed in the same way translatedCategory is).

## 49. Favorites (Part 11)

A heart toggle on every food card (top-left, mirrored in RTL) plus a
persistent Favorites entry point -- a heart icon with a live count badge
in the top bar (`#lang-bar`, outside `#app`, so it's reachable from
every screen, not just the restaurant list) -- opening a dedicated
Favorites screen.

### Storage: localStorage now, "designed so it can later move to backend"

Same reasoning as Cart (Part 46): no auth/account system exists to
persist favorites against server-side, so they live in `localStorage`
(`uniresto.favorites.v1`). The "designed so it can later move to
backend" requirement is met structurally, not just claimed: every
caller reads/writes favorites through exactly two functions,
`loadFavorites()`/`saveFavorites()` (plus `toggleFavorite()`/
`isFavorite()` built on top of them) -- nothing else touches
`localStorage` directly. Swapping those two functions for real API calls
later is a localized change, not a rewrite.

Keyed by `(slug, category, name)` -- one field broader than the cart's
`(category, name)` key (Part 46) since favorites span BOTH restaurants,
not just whichever one is currently being browsed.

### Never inventing availability -- checked live, not assumed

The Favorites screen re-checks TODAY's live status for every restaurant
that has at least one favorite before showing anything, exactly like the
"never trust a stale id, re-validate against the live menu" principle
already used for Cart restoration (Part 46) and planned for Order
History's Reorder (Phase 5). Three distinct, honest outcomes per
favorite, never conflated:

1. The restaurant isn't orderable today at all -- shown with the exact
   same status vocabulary as the date picker (`dateStatusLabel()`:
   `ORDERING CLOSED`, `CLOSED`, `NO MENU`, etc.), not a single vague
   "unavailable".
2. The restaurant IS open today, but this specific dish isn't on
   today's menu (rotated out, or a discontinued Constant Product) --
   its own distinct reason, `favoriteNotOnTodayMenu` ("Not on today's
   menu"), not lumped in with case 1.
3. The dish IS on today's live menu -- shown with the same live
   weight/price/calories as its food card, and the row becomes tappable,
   jumping straight to that restaurant's today menu (`goToFavoriteToday()`,
   which just calls `selectDate()` directly, reusing its selection/
   filter/search-reset behavior rather than duplicating it).

### A real bug this caught: a temporal-dead-zone crash swallowed by a defensive `catch`

`state.favorites` is loaded *eagerly* -- `loadFavorites()` runs
synchronously as part of constructing the `state` object itself, so the
top-bar badge is correct from the very first render rather than
appearing a moment later. `FAVORITES_STORAGE_KEY` was originally
declared as a `const` further down the file, next to
`loadFavorites()`/`saveFavorites()`. Since `state = {...}` executes
*before* that later `const` declaration is reached, referencing
`FAVORITES_STORAGE_KEY` from inside `loadFavorites()` at that point hit
JavaScript's temporal dead zone and threw a `ReferenceError` -- which
`loadFavorites()`'s own defensive `catch { return []; }` (written for
"localStorage is unavailable, e.g. private browsing") silently caught,
returning `[]` regardless of what was actually saved. The whole module
still loaded fine (the throw was contained inside that one function), so
nothing looked broken -- the restaurant list rendered normally, just
with an empty favorites badge every single time, no matter how many
favorites were actually saved.

This was caught the same way the Part 7/9 bugs were: by actually
exercising the real flow (seed `localStorage` with a favorite, reload
the page, check whether the badge shows "1") rather than trusting the
code path unverified -- a unit test would only have caught it if that
test happened to construct `state` the same way the real module does
(most wouldn't have, since it's a load-*order* bug, not a logic bug).
Fixed by moving `const FAVORITES_STORAGE_KEY = ...` to the top of the
file, above `state`, and verified live: the badge now shows the correct
count on the very first paint after a fresh reload with a
localStorage-seeded favorite.

### Where it lives

- **`static/app.js`**: `FAVORITES_STORAGE_KEY` (top-level, see above),
  `loadFavorites()`/`saveFavorites()`/`isFavorite()`/`toggleFavorite()`/
  `favoriteKey()` (storage), `openFavorites()`/`goToFavoriteToday()`/
  `renderFavorites()` (the screen and its live-availability check),
  the heart button wired into `foodCard()`, the favorites nav button
  wired into `renderLangBar()`.
- **`static/i18n.js`**: `favorites`, `favoritesEmptyTitle`/Body,
  `addFavorite`/`removeFavorite`, `favoriteNotOnTodayMenu`,
  `viewTodayMenuFor`, `loadingFavorites` added in all 10 languages.
- **`static/app.css`**: `.heart-btn` (food-card corner toggle, RTL
  mirrored), `.favorites-nav-button` (top-bar entry point + badge),
  `.favorite-row` (the screen's list rows). `#lang-bar` changed from
  `justify-content: flex-end` to `space-between` to fit both the new
  favorites button and the language selector.
- No new backend endpoints -- favorites re-check availability via the
  same `/api/restaurants/<slug>/status` and `/menu/<date>` endpoints
  every other screen already uses.

### Verified live

Favorited "Salad'bar" from Altius's Thu Sep 24 2026 menu -- the heart
filled red immediately and the top-bar badge showed "1". Opening
Favorites while Altius's *today* (Wed Sep 23) status was live
`ORDERING_CLOSED` correctly showed that exact status on the row, not a
fabricated "available" -- confirmed via `read_network_requests` that a
real `GET /api/restaurants/altius/status?date=2026-09-23` (200 OK) drove
it. Un-favoriting from the Favorites screen correctly emptied the list
and showed the empty state. Seeded `localStorage` directly with a
favorite and reloaded the page fresh: after the fix above, the badge
showed "1" immediately (before the fix: silently "0" despite the data
being there -- see the bug writeup above).

### Known limitations

- Availability is only ever checked against **today** -- there's no way
  to ask "is this favorite orderable next Tuesday" from the Favorites
  screen itself; the user has to tap through to that restaurant and pick
  a date normally.
- Tapping an available favorite jumps to that restaurant's today menu
  (browsing context) rather than adding it straight to a cart -- kept
  deliberately simple: Cart (Part 46) is scoped to one restaurant/date
  at a time, and auto-adding across that boundary was out of scope here.
- No "optionally favorite whole restaurants" (mentioned as a maybe in
  the original spec) -- only individual dishes are favoritable in this
  phase.

## 50. Order History + Reorder (Part 12)

A dedicated Order History screen (third persistent top-bar icon, next to
Favorites) listing every order this browser has confirmed, each with a
**Reorder** action that re-validates against today's live menu rather
than resubmitting anything stored.

### One new backend endpoint, everything else reused

`GET /api/orders/<id>` (new) re-fetches one previously confirmed order
by id, via the exact same `OrderStore.get_order()` the confirmation
screen (Part 3) already calls right after creation -- no new storage
method, no new query. It's the only backend change this phase needed.

### "My" history without accounts: IDs client-side, records server-side

Same constraint as Cart/Favorites (Parts 46/49): no auth system to scope
"my orders" by. The resolution here is different from Cart and
Favorites' full-content localStorage caching, and deliberately so:
`uniresto.orderHistory.v1` stores **only order IDs**, nothing else.
Every time the History screen opens, each ID is re-fetched fresh via the
new `GET /api/orders/<id>` -- so unlike a cached cart/favorite entry,
there is no stored price/weight/status that could ever go stale,
because nothing but the bare integer id is stored at all.

### Reorder: re-validated, never resubmitted

Reorder does not resend the old order. It re-runs the same
"never trust a stale id, re-validate against the live menu today"
sequence already established for Cart restoration (Part 46) and
Favorites (Part 49):

1. Look up the order's `restaurant_code` against `state.restaurants`
   (fetched from `/api/restaurants`) to recover the URL `slug` -- the
   stored order has Restopolis's raw code, not the frontend's slug.
2. Check **today's** live status for that restaurant. Not available?
   Stop with an explanation (`reorderNotAvailableToday`) rather than a
   silent no-op or a stale-date resubmission -- verified live (see
   below).
3. Fetch today's live menu and match each old line by `(category,
   name)`, exactly like Cart's restore matching (never the old numeric
   id, which `menu_service.flatten_menu_items()` only guarantees stable
   "within one response"). Anything no longer on today's menu is
   dropped, with a toast naming how many (`reorderItemsUnavailable`,
   reusing the exact wording pattern already established for Cart's own
   `cartItemsUnavailable`, just scoped to "this order" instead of "your
   saved cart").
4. Land on the **cart screen** (Part 46) with the freshly matched
   selection -- never directly re-creating an order. The user sees the
   live, server-verifiable total (via the same `/api/orders/quote`
   Part 46 already wired in) before confirming anything, exactly as if
   they'd picked those dishes themselves just now.

### Where it lives

- **`app.py`**: `GET /api/orders/<int:order_id>` (new route).
- **`tests/test_app.py`**: 2 new tests (found by id, 404 for an unknown
  id).
- **`static/app.js`**: `ORDER_HISTORY_STORAGE_KEY`/`loadOrderHistoryIds()`/
  `addToOrderHistory()` (storage -- deliberately NOT loaded eagerly into
  `state` the way favorites are, sidestepping the exact temporal-dead-zone
  hazard Part 49 documents, since there's no persistent badge here that
  would need it on first paint); `openOrderHistory()`/
  `renderOrderHistory()`/`reorderPastOrder()`/`historyWeightSummary()`/
  `orderStatusLabel()`; `addToOrderHistory(order.id)` wired into
  `confirmOrder()`'s success path; the history nav button wired into
  `renderLangBar()`'s new `.nav-icons` wrapper (grouped with the
  favorites button so `#lang-bar`'s `space-between` still only has two
  top-level items to push apart).
- **`static/i18n.js`**: `orderHistory`, `orderHistoryEmptyTitle`/Body,
  `reorder`, `placedOn`, `statusPending`, `reorderNotAvailableToday`,
  `reorderNoneAvailable`, `reorderItemsUnavailable`,
  `loadingOrderHistory` added in all 10 languages.
- **`static/app.css`**: `.nav-icons`, `.history-row`,
  `.history-reorder-btn`.

### Verified live

Confirmed a real order (Salad'bar, Altius, Thu Sep 24 2026) -- it
immediately appeared in Order History showing restaurant/date, item
summary, "Placed Wed, Sep 23 · 18:10 · Pending", weight/price totals
(correctly showing "1 unknown" weight and the formula's own honest
"Select a main dish..." unpriced reason, reusing Part 39's existing
logic unchanged). Tapped **Reorder**: since Altius's *live* status for
today (Wed Sep 23) was genuinely `ORDERING_CLOSED` (confirmed via
`read_network_requests` -- a real `GET .../status?date=2026-09-23`
fired), the app correctly showed **"Altius isn't orderable today"**
rather than silently failing, resubmitting the stale order date, or
pretending it succeeded.

### Known limitations

- History is a flat list of every order this specific browser has ever
  confirmed (via its locally stored id list) -- no pagination, no
  per-restaurant filter, no date range. Given the likely order volume
  for a two-restaurant campus app, this wasn't worth building yet.
- If `localStorage` is cleared (or a different browser/device is used),
  the order history disappears client-side even though the records
  still exist server-side in `orders.db` -- same inherent limitation as
  Cart/Favorites, an unavoidable consequence of having no accounts.
- Reorder only ever checks **today** -- like Favorites (Part 49), there
  is no "reorder this for next Tuesday" shortcut; a `reorderNoneAvailable`
  today doesn't offer to check another date automatically.

## 51. Smart Lunch (Part 13)

A deterministic backend search (`orderability_engine/smart_lunch.py`,
new) over today's live menu for a lunch matching a set of constraints --
never a ranking, never a fabricated combination, and never a "best" or
"healthiest" label anywhere in the algorithm or its output.

### Reuses the real meal-formula system, doesn't invent a second one

Every combination this module can ever produce is one of the 3 real,
already-priced tiers from Part 6/39 (`main` / `main_starter` /
`main_starter_dessert`), computed via `pricing.compute_formula_total()`
directly -- not a separate pricing model. A combination that formula
system can't price (e.g. dessert with no starter) is structurally never
generated in the first place, so there's nothing to filter out after
the fact.

### Two constraint classes, and a fixed, documented relaxation order

- **Hard** (`dietary_preferences`, `excluded_allergens`): never relaxed.
  If they leave zero eligible main dishes, the search fails outright
  with an explanation naming that as the cause (e.g. "no main dishes
  match your dietary/allergen choices today").
- **Soft** (`meal_preference`, `max_calories`, `min_weight`,
  `max_price`): tried together first; if nothing satisfies all of them,
  they're dropped **one at a time**, least-important first (`meal_
  preference` → `max_calories` → `min_weight` → `max_price`, a
  documented v1 design choice, not a derived fact -- price is treated
  as the constraint a student is least likely to want relaxed). Each
  drop is recorded in `unavailable_constraints` with a reason code, and
  the ones that survive are listed in `matched_constraints` -- so a
  successful result can still honestly say "found something, but
  couldn't honor your weight preference" rather than silently ignoring
  it.

### Never treats an unknown weight/calorie value as zero

`min_weight`/`max_calories` can only be confirmed for a combination
whose **every** item has a known value in that dimension (`_combo_
weight`/`_combo_calories`); a combination with even one item of unknown
weight/calories is never claimed to satisfy either constraint, no
matter how much the known portion alone would suggest. Given real
Restopolis data mostly lacks weight/calories for daily-formula dishes
(Parts 3/7), this means min_weight/max_calories routinely get relaxed
on the real menu -- confirmed live (see below), not a hypothetical.

### "Option 1/2/3" is structural, not a ranking

The backend never sends display text -- only structured data (`tier`,
`items`, `total_price`, weight/calorie totals) and reason/constraint
**codes**, the same "codes, not prose" rule Part 6/39's formula-reason
handling already follows. `select_options()` picks up to 3 combinations
with genuine variety through STRUCTURE, never a score:
- No `meal_preference` given: one option per tier (main, then
  main+starter, then main+starter+dessert) -- the natural "simple /
  regular / full" distinction a canteen menu already implies.
- `meal_preference` given: one option per distinct main dish at that
  tier (first-available starter/dessert pairing, in menu order -- a
  documented v1 simplification; it doesn't enumerate every starter x
  dessert pairing).
The frontend builds "Option {n}" purely from the response array's own
position via `static/i18n.js`, never from anything the backend sent.

### Where it lives

- **`orderability_engine/smart_lunch.py`** (new): `find_smart_lunch()`
  (the full algorithm), `select_options()`, `_combo_weight()`/
  `_combo_calories()`, `_relax_reason()`.
- **`tests/test_smart_lunch.py`** (new, 16 tests): tier variety with no
  constraints, hard-filter exhaustion, soft-constraint drop ordering and
  reasons, the "unknown item blocks confirmation even when the known
  portion alone would pass" case, `select_options()`'s two variety
  modes.
- **`app.py`**: `POST /api/smart-lunch` (new route) -- validates input
  shape (dietary values, allergen codes as ints, `meal_preference`
  against `TIER_PRICES`' own keys, numeric fields), re-checks live
  orderability (409 if the date isn't available, same pattern as
  `/api/orders`), then delegates entirely to `find_smart_lunch()`.
  `tests/test_app.py`: 6 new integration tests against the real fixture.
- **`static/app.js`**: the "✨ Smart Lunch" button (added to the same
  row as the Filters button on the menu screen); `renderSmartLunch()` /
  `renderSmartLunchForm()` (constraint form, reusing `chipButton()`/
  `toggleInArray()` from Filters, Part 47) / `renderSmartLunchResult()`;
  `addSmartLunchOptionToSelection()` -- adds a chosen option's items to
  the cart matched by `(category, name)` against the already-loaded
  `state.menu`, the same "never trust an id across a separate fetch"
  principle as Cart restore/Favorites/Reorder (Parts 46/49/50), since
  the option's items came from the backend's OWN separate live-menu
  fetch, not necessarily the identical response object already held
  client-side.
- **`static/i18n.js`**: 33 new keys (form labels, meal-type options,
  constraint names, and one translated string per backend reason code)
  added in all 10 languages.
- **`static/app.css`**: `.smart-lunch-form`, `.smart-lunch-option`,
  `.smart-lunch-items`, `.smart-lunch-summary`, `.constraint-note`,
  `.link-button`.

### Verified live

On Altius/Thu Sep 24 2026 with no constraints: 3 options, exactly one
per tier, priced €3.70 / €4.20 / €5.20 -- matching the real formula
tiers exactly. With `dietary_preferences: ["vegan"]` + `min_weight:
300`: correctly returned exactly **1** option (Altius has only one real
vegan main that day, "Aloo Palak au tofu", so there's no variety to
show -- not a bug), priced €3.70, with the transparency summary reading
**"Matched: Dietary preference"** and **"Couldn't confirm: Min weight
(weight isn't published for today's dishes)"** -- confirmed via
`read_network_requests` that this was a real `POST /api/smart-lunch`
(200 OK), not a canned response. Tapped **Select this option**: landed
on the Cart screen (Part 46) with "Aloo Palak au tofu" already selected
and the server-verified total showing **€3.70**, matching the option
exactly -- confirming the (category, name) re-match against the live
menu worked correctly end to end.

### Known limitations

- `meal_preference`'s "first available starter/dessert" pairing (see
  above) means two options at the same tier always share the same
  starter/dessert even when several exist -- only the main dish varies.
- No cross-restaurant search -- Smart Lunch operates on whichever
  restaurant/date the user is already viewing, same scope boundary as
  Filters/Search (Parts 47/48).
- The soft-constraint drop order is a single fixed priority for
  everyone; it isn't user-configurable (e.g. a user who cares more
  about weight than price than about meal type can't reorder that
  priority in this phase).

## 52. Visual redesign (Part 14)

Adopted the visual language of a supplied reference design (colors,
icon system, bottom tab navigation, card style) across every existing
screen, without changing any underlying logic and -- critically --
without copying data the reference showed that this app doesn't
actually have.

### What was adopted vs. deliberately left out

The reference mockup includes several things this project's real data
can't honestly back: per-dish macros (protein/carbs/fat/salt -- Part 7's
nutrition module only ever estimates calories, never macros), a
"Delivered" order status (Part 3's `OrderStore` only ever has `pending`
-- there's no fulfillment system), literal per-dish prices (Part 6:
Restopolis has none, only the 3-tier meal formula is real), and a full
account "Profile" with delivery addresses/notifications/log-out (no
accounts exist at all, see the README intro). None of these were
copied -- see "Profile" and "Item detail" below for how each was
resolved instead of silently faked.

- **Adopted**: a green primary color + category-accent icon system
  (`--color-cat-meat`/`-veg`/`-drink`/`-other`), a persistent bottom tab
  bar, inline-SVG icons replacing every emoji/Unicode glyph previously
  used, restyled cards/buttons/chips across every screen.
- **No Item Detail screen was built.** The reference's per-dish detail
  screen is mostly macro nutrition this app doesn't have; the existing
  food card already surfaces every real field (weight, formula price
  context, estimated calories, allergens, description) inline, so a
  separate screen would have added a new navigation layer for little
  real new information. Documented here as a deliberate scope cut, not
  an oversight.
- **Profile is a "settings" screen, not an account page.** No fake
  name/avatar/"Student" line was added (there's no identity system to
  attach one to). Its content is exactly three genuinely real things:
  shortcuts to the two other localStorage-backed personal lists
  (Favorites, Order History, each with its real current count), the
  language picker (same control as the persistent top bar, duplicated
  here since the reference itself puts it in Profile), and a one-
  paragraph, honest description of what this project actually is.

### Bottom tab bar: shown only where the reference shows it

`BOTTOM_NAV_TABS` (Home/Favorites/Order History/Profile) renders only on
the 4 screens those tabs actually lead to -- a "drill-down" screen (a
restaurant's menu, the cart, Smart Lunch's form, Filters) hides it in
favor of its own header back button, matching the reference's own
mockups exactly (its Menu/Filters/Item-detail/Cart/Smart-Lunch screens
don't show a tab bar either). This also sidesteps a real layout problem
for free: the menu screen's sticky summary bar and the bottom nav would
otherwise have had to stack/coexist at the bottom of the same screen.

### Icons: one inline-SVG source of truth, RTL handled by a single CSS transform

Every icon (`icon(name, size)` in `static/app.js`) is `currentColor`-
based inline SVG, replacing the emoji/Unicode characters used
throughout the earlier phases (♥/♡/←/→/×/✨/🕐/🍽️/etc.). Directional
icons (the back chevron, the Smart-Lunch-result "back" link) are
mirrored for RTL with a single `transform: scaleX(-1)` CSS rule rather
than swapping glyphs per direction -- one source of truth regardless of
language, verified live in Arabic (see below).

### A real bug this caught: a missing translation key

Verified live immediately after wiring up the bottom nav: the "Home"
tab rendered the literal, untranslated string `home` instead of "Home"
-- a real missing `static/i18n.js` key across all 10 languages (the
`labelKey: "home"` tab definition was written but the key itself was
never added). `t()`'s own designed fallback (README Part 4: fall back to
the key itself so a missing string stays *visible* rather than crashing)
is exactly what surfaced it. Fixed by adding `home` in all 10 languages;
verified the fix by reloading.

### A real layout bug this caught: two icons fighting for the same corner

Also caught by looking at the actual rendered page, not just reading the
CSS: the new leading category icon-avatar (top-left of each food card)
and the existing heart-favorite button (also positioned top-left)
visually overlapped once both were in place -- a collision the CSS
alone didn't make obvious before rendering it. Fixed by moving the heart
button to sit beside the select/quantity indicator in the top-right
corner instead (`right: 46px`, RTL-mirrored to `left: 46px`), with
`.card-head`'s reserved padding widened from 32px to 78px to clear both
icons. Verified live in both English and Arabic that the two no longer
overlap in either direction.

### Where it lives

- **`static/app.css`**: new `:root` tokens (primary green, 4 category-
  accent color pairs), `#bottom-nav`/`.nav-tab`, `.icon-avatar`,
  restyled `.food-card`/`.restaurant-card`/`.select-check`/`.heart-btn`/
  `.quantity-stepper`, `.profile-rows`/`.profile-row`/`.profile-about`.
- **`static/app.js`**: `ICON_PATHS`/`icon()` (the icon system),
  `categoryIconClass()` (derives the icon-avatar's color from real
  fields -- `weight_unit`, `vegetarian`/`vegan`, `MAIN_CATEGORIES` --
  never a new invented classification), `BOTTOM_NAV_TABS`/
  `renderBottomNav()`, `renderProfile()`; `renderLangBar()` simplified
  back down to just the language select (favorites/history navigation
  moved to the bottom tabs).
- **`static/i18n.js`**: `home`, `profile`, `aboutTitle`, `aboutBody`
  added in all 10 languages.
- **`templates/mobile.html`**: added `<nav id="bottom-nav">`.
- No backend changes -- purely a frontend visual/navigation pass.

### Verified live

Walked Home → date picker → menu (card selection, quantity stepper,
Filters sheet, Smart Lunch results) → Cart → Profile in English, then
repeated Home/menu/bottom-nav in Arabic (RTL) -- confirmed correct
mirroring throughout (icon-avatar and heart/select-check swap sides,
back chevron points the correct direction, bottom-nav tab order
reverses, restaurant-card layout mirrors) with zero remaining overlaps
after the two fixes above. Full suite re-confirmed unaffected: 180
Python + 88 Node tests, all passing (this phase touched no business
logic, only markup/CSS/navigation).

### Known limitations

- Favorites and Order History rows don't have the new icon-avatar
  treatment (they're simpler list rows, not full food cards) -- visually
  a little less "on-brand" than the Menu screen, not a functional gap.
- No wide-screen/tablet layout changes -- the redesign inherits the
  existing single-centered-column shell (`--max-content-width`) at every
  viewport width, same limitation already noted for Filters' bottom
  sheet (Part 47).
- Item Detail screen intentionally not built (see above) -- if real
  macro nutrition data ever becomes available, that would be the
  natural point to revisit this decision.

## 53. Device presentation: foldable on desktop, native iPhone on phones (Part 15)

- **Phones (< 1024px wide)**: the app *is* the screen -- no frame. Tuned
  to feel like a native iOS app on a Pro Max-class iPhone: translucent
  "frosted" tab bar, header and category bar; a floating rounded order
  bar above the home indicator; safe-area insets (including landscape,
  where the Dynamic Island sits on a side edge); `100dvh`; 16px form
  fields so iOS Safari doesn't zoom on focus; pressed-state feedback in
  place of the grey tap highlight; home-screen web-app meta tags.
- **Desktop (>= 1024px wide)**: the app is drawn on the inner screen of
  an open, book-style foldable phone -- bezel, fold crease down the
  middle, hinge caps, top-edge buttons, inner-screen camera on the right
  half, and a status bar showing the real local time. The menu shows one
  food column per half. This is a stylized frame, not a replica of any
  specific device, and carries no manufacturer branding.
- **How the frame works**: `.device-screen` is a transformed box, which
  makes it the containing block for every `position: fixed` element
  inside it (tab bar, order bar, toast, Filters sheet), so they sit on
  the phone's screen rather than the browser window; `#scroller` is what
  scrolls. On phones the same wrappers are `display: contents`, so they
  don't affect layout and the page scrolls natively. `FRAMED` in
  `static/app.js` must stay in sync with the CSS breakpoint;
  `scrollToTop()`/`onScroll()` handle whichever surface is scrolling.
- **Real bug fixed along the way**: `overflow-x: hidden` on `html`/`body`
  made `<body>` a scroll container that never scrolls, so on phones the
  sticky header and category bar scrolled away instead of pinning.
  Switched to `overflow-x: clip`, which clips the same way without
  creating a scroll container. Verified by measurement: when scrolled
  700px, the header sits at 0 and the category bar at 60px.
- **Testing note**: the in-app browser pane used for verification draws
  screenshots of a *scrolled* page shifted down by the scroll distance.
  A plain control page with none of this app's code showed the same
  thing, while hit-testing put content in the correct place -- so it's a
  screenshot artifact, not an app bug. Scrolled states were verified by
  measuring element positions; unscrolled states by screenshot.

## 54. Luxembourgish + app-style language picker on the Profile page (Part 16)

- **Luxembourgish (`lb`, Lëtzebuergesch)** is the 11th language, added
  because it's the local language of the campus. It has every UI string
  (154 keys, same set as English), all 25 menu-category labels and all
  14 allergen names. Plural forms work too ("1 Artikel" / "3 Artikelen").
- **Dates fall back to German**: many browsers don't ship Luxembourgish
  date/number data (`Intl.DateTimeFormat.supportedLocalesOf("lb-LU")`
  returned `[]` in the test browser), and would silently fall back to
  English. `intlLocale()` in `static/i18n.js` uses `lb-LU` when the
  browser supports it and otherwise `de-LU` (German as used in
  Luxembourg), which people in Luxembourg read everywhere. The UI text itself
  is always Luxembourgish.
- **Selector moved to Profile only**: the old top-bar `<select>` was
  removed, as requested. Profile > Language opens a bottom sheet in
  the style of the Filters sheet. Each row shows a language code badge,
  the language's own name (e.g. "Русский", in the correct script and
  direction) and its name in the current UI language, from
  `Intl.DisplayNames`. A check mark shows the current language. On the
  desktop foldable frame the sheet stays inside the device screen.
- **Accessibility**: the sheet is a `role="dialog"` with
  `aria-modal`; the list is a `radiogroup` of `role="radio"` rows with
  `aria-checked`. Arrow Up/Down move between rows. Escape, the close
  button or a tap outside closes the sheet and returns focus to the
  Language row. Motion respects `prefers-reduced-motion`.
- **Bugs fixed while building it**: (1) Arabic and Urdu names were pushed
  to the right edge, because each name carries `dir="rtl"` and so
  aligned to its own start inside a stretched flex column. The name
  column now uses `align-items: flex-start`. (2) The list spilled past
  the sheet over the tab bar instead of scrolling: a flex child needs
  `min-height: 0` to shrink below its content height. (3) Toggling a
  favorite still called the removed top bar's render function; it now
  refreshes the tab-bar badge instead.
- **Verified live** on a phone-sized screen (440x956) and the desktop
  frame (1440x900): switching to Luxembourgish translates the tab bar
  ("Doheem", "Favoritten", "Bestellhistorique", "Profil") and the home
  screen ("Wou wëlls du iessen?"), and survives a reload. The Arabic
  layout mirrors correctly. Tests: 90 JS, 180 Python, all passing.

## 55. Search over allergens, restaurant list simplified, kcal unit, hidden scrollbars (Part 17)

- **Search now matches allergens too**, not just name/description/
  category. Restopolis has no separate ingredient list -- allergens
  (`item.allergens`, see `restopolis/allergens.py`) are the closest thing
  to it -- so `static/search.js`'s `itemMatchesQuery`/`searchItems` gained
  an optional translated-allergen argument, matched the same way
  category already was: against both the raw Restopolis name (e.g.
  "Lait") and the current-language label (`allergenLabel()`, e.g.
  "Milk"). Verified live: searching "lait" and "milk" both return the
  same 43 dishes. New tests in `tests_js/search.test.mjs`.
- **The restaurant list no longer shows or fetches "today" status.**
  Previously each card dimmed and showed a pill like "Недоступно
  сегодня" (not available today) based on a live per-restaurant check at
  page load. That duplicated, and could conflict with, the date picker
  one screen deeper, which already shows honest per-day availability
  with a specific reason (closed / no menu / ordering window over /
  etc) and -- per the existing "every day stays tappable" principle --
  never hides a day, just explains it. Restaurants are now always
  reachable from the list; `loadRestaurants()` only fetches
  `/api/restaurants` (no more N extra status calls), and `state`,
  `renderRestaurants()`, and the now-dead `.is-dim`/`.restaurant-card-
  status` CSS were all trimmed to match.
- **Calorie estimates now show "kcal"** instead of the heavier "≈
  estimated 250 Calories" wording. Added a dedicated `kcal` i18n key
  (separate from the existing `calories` key, which stays as-is since
  it's also the Filters sheet's section heading and would've been wrong
  to repurpose) -- `"kcal"` for most languages (the literal abbreviation
  EU and Indian nutrition-label regulations both mandate regardless of
  language), `"千卡"` for Chinese and `"ккал"` for Russian, matching how
  each is actually written on food labels. Used in both the food-card
  calorie line and the Smart Lunch result cards.
- **Hidden the horizontal scrollbar thumb** on the category-jump row and
  the date picker's day scroller. Both already had `scrollbar-width:
  none` (Firefox) but were missing the WebKit/Chrome equivalent
  (`::-webkit-scrollbar { display: none }`), so a gray pill showed under
  the chips in Chrome-based browsers -- now hidden consistently with
  `#scroller`, which already did this correctly.
- Tests: 93 JS (3 new allergen-search cases), 180 Python, all passing.

## 56. Pricing switched from bundled tiers to flat per-course prices (Part 18)

- **Replaced the 3-tier bundle rule with flat per-item course pricing**,
  supplied directly: main dish **€6.00**, starter/salad (Entrée)
  **€2.00**, dessert **€2.00** -- each course priced and summed
  independently, superseding the earlier v1 rule (main €3.70 /
  main+starter €4.20 / main+starter+dessert €5.20, a fixed bundle total
  per combination). Féculents/Légumes sides are still bundled free with
  any main dish, and Constant Products/snacks are still outside this
  pricing entirely -- neither of those changed.
- **Every combination is priceable now.** The old bundle rule only had a
  price for 3 exact shapes and explicitly refused to guess at anything
  else (e.g. a dessert bought alone, or a main + dessert with no
  starter, came back with `reason: "no_main_dish"` /
  `"dessert_without_starter"` and no total). Flat per-item pricing has
  no such gap -- `compute_formula_total()` in
  `orderability_engine/pricing.py` (mirrored in `static/pricing.js`)
  now returns `main_count`/`starter_count`/`dessert_count` and a `total`
  that's simply `main_count*6 + starter_count*2 + dessert_count*2`,
  `None` only when the selection has nothing from any of those 3
  categories at all (an empty cart, or only sides/snacks). `reason` is
  kept in the shape for compatibility but is now always `None`.
- **Smart Lunch (Part 51) needed no logic changes** -- it still
  generates the same 3 structural combo shapes (main alone / +starter /
  +starter+dessert) for genuine "simple / regular / full" variety (an
  intentional v1 design choice, not a pricing limitation), and still
  prices each candidate by calling `compute_formula_total()`; only the
  numbers it gets back changed (tiers now cost €6.00/€8.00/€10.00, not
  €3.70/€4.20/€5.20). `app.py`'s `meal_preference` validation was
  repointed from the removed `TIER_PRICES` to `smart_lunch.TIER_ORDER`,
  since which combinations Smart Lunch can search by was always a
  course-composition concept, not a pricing-table one.
- **Verified live**: adding one main + one starter + one dessert to the
  cart shows €10.00 in both the instant client-side preview and the
  server-verified quote after "View order". Removing the main and
  starter and keeping only the dessert now correctly shows €2.00 --
  a combination the old rule couldn't price at all.
- Updated tests in `tests/test_pricing.py`, `tests/test_orders.py`,
  `tests/test_smart_lunch.py`, `tests/test_app.py`, and
  `tests_js/pricing.test.mjs` for the new numbers and return shape.
  Tests: 93 JS, 180 Python, all passing.

## 57. "Portion size not specified" removed from every item row (Part 19)

- Restopolis publishes a weight for only a small fraction of daily-formula
  dishes (see README.md Part 3/7), so most food cards, cart/review lines,
  confirmation lines, favorites, and Smart Lunch item rows were showing
  the literal phrase "Portion size not specified" on nearly every single
  item -- real clutter, not useful information.
- `weightText()`/`localizedWeightValue()` in `static/app.js` now return
  `null` instead of that phrase when a dish has no published weight, and
  every render site (food card, favorites row, review line, confirmation
  line, Smart Lunch item + option-totals line) omits the weight segment
  entirely in that case -- the same conditional-segment pattern already
  used for the optional calories text, so "Price not available" and any
  known calorie estimate still show normally, just without a dangling
  separator. A now-unreachable `.weight.is-unspecified` CSS rule was
  removed too.
- The two cart/order-history WEIGHT SUMMARY lines
  (`localizedWeightSummary`/`historyWeightSummary`) keep their own
  `portionSizeNotSpecified` fallback in the code, but it's provably dead:
  with at least one item selected, every portion counts toward either a
  known-weight bucket or the "N unknown" count, so the fallback string
  never actually renders. Left as-is (harmless, not user-visible).
- Verified live: a dish with a real weight still shows "80 g · Price not
  available · ≈ estimated 280 kcal"; a dish without one now shows just
  "Price not available" (no leading text at all). Smart Lunch's 3 option
  cards now read "€6.00" / "€8.00" / "€10.00" with no trailing phrase.
  Tests: 93 JS, 180 Python, all still passing (this was a display-only
  change to app.js/app.css, no pure module touched).

## 58. Order deadline switched from "day before" to same-day 08:00 (Part 20)

- **The delivery cutoff is now same-day**, supplied directly: an order
  for date D is possible up until **08:00 Europe/Luxembourg on D
  itself** -- e.g. an order for 2026-09-24 is possible until 08:00 on
  2026-09-24; an order for 2026-09-25 until 08:00 on 2026-09-25; and so
  on for every date. This supersedes the earlier v1 rule (08:30 on the
  day *before* D).
- `orderability_engine/delivery_rules.py`'s `DeliveryRuleConfig` changed
  from `cutoff_time=08:30, days_before=1` to `cutoff_time=08:00,
  days_before=0` -- `compute_our_deadline()` itself didn't need any
  logic change, since it already computed `target_date -
  timedelta(days=days_before)`; `days_before=0` naturally lands the
  cutoff on the target date itself.
- No frontend change was needed: `static/app.js` only ever displays
  whatever ISO deadline the backend's `our_delivery.deadline` field
  gives it (via `fmtDeadline()`), so the date picker and menu screen
  picked up the new same-day wording automatically.
- **Verified live**: the date picker now shows "Order before Thu, Sep 24
  · 08:00" under Thursday's own card (not Wednesday's), "Order before
  Fri, Sep 25 · 08:00" under Friday's, etc -- each date's deadline
  lands on itself, never the neighboring day. The menu screen's header
  for Thursday shows "Order deadline: Thu, Sep 24 · 08:00" too.
- Updated tests in `tests/test_delivery_rules.py` (including a new
  `test_multiple_dates_each_cut_off_the_same_day`, covering exactly the
  24.09/25.09 examples given) and `tests/test_orderability_service.py`'s
  "Restopolis orderable but our deadline passed" scenario, whose `now`
  moved from the day before to the same day, after 08:00. README Parts
  13/14 (and a code comment in `pricing.py`) were updated to stop
  citing the old 08:30/day-before numbers as current; the historical
  worked examples in Parts 17/39 that literally reproduce the original
  task spec's own 08:30 example are left as a record of that spec, not
  live behavior. Tests: 93 JS, 181 Python (1 new), all passing.

## 59. App always launches on the home screen (Part 21)

- **Opening the app now always lands on the restaurant list**, never
  mid-cart. Previously, `init()` checked localStorage for a saved cart
  from any earlier visit and, if found, silently re-fetched that
  restaurant/date's live menu and jumped straight to the "Your order"
  review screen -- bypassing Home entirely. That's gone: `init()` now
  unconditionally calls `goTo("restaurants")`.
- The now-unreachable restore machinery (`loadSavedCart()` re-reading
  the saved cart, and `tryRestoreCart()` re-validating and navigating to
  it) was removed from `static/app.js` rather than left inert -- with
  nothing left to call it, it would only have cost two silent extra API
  requests (`/status` + `/menu`) on every single app load for no
  observable effect.
- Cart persistence itself is untouched: `saveCart()` still writes the
  in-progress cart to `localStorage` on every change (add/remove/
  quantity/delivery-location), and `clearSavedCart()` still clears it
  once an order is confirmed -- that's a same-session safety net, not
  the removed on-load auto-jump.
- **Verified live**: with a cart still saved in `localStorage` from a
  previous visit, reloading the app (twice, for good measure) lands on
  "Where do you want to eat?" both times, never "Your order". Tests: 93
  JS, 181 Python, all still passing (display/navigation-only change,
  no pure module touched).

## 60. Menu now cached in SQLite, refreshed hourly (Part 22)

- **The menu no longer re-fetches from Restopolis on every load.**
  Before this, the raw week HTML the menu is parsed from
  (`OrderabilityService.get_week_html()`) was only ever cached in an
  in-process Python dict -- fine within one running process, but wiped
  by every restart (common in this dev environment), so the very next
  menu load after any restart silently re-hit Restopolis live, however
  recently it had actually been fetched.
- **New `week_html_cache` SQLite table**, in the same `orderability.db`
  file the existing 15-minute orderability-status cache already uses
  (`orderability_engine/cache.py`), keyed by `(restaurant_code,
  weeks_ahead)` -- one row covers every date in that week, same as the
  in-process dict already did. New `OrderabilityCache.get_week_html()`/
  `set_week_html()` methods read/write it.
- **Refreshed every hour**, deliberately longer than the 15-minute
  status cache: the dish list itself changes far less often than
  open/closed signals do. `orderability_engine/service.py`'s new
  `WEEK_HTML_TTL_SECONDS = 3600` constant drives both the in-process
  dict's TTL and the new SQLite table's TTL (previously the in-process
  dict shared the STATUS cache's 15-minute TTL, conflating two
  different kinds of data with different real-world change rates).
  `get_week_html()` now checks, in order: (1) the in-process dict --
  free, no I/O; (2) the persisted SQLite cache -- survives a restart;
  (3) only then a real live Restopolis fetch, which is written back to
  both. `refresh=True` still skips straight to (3), matching
  `check_orderability`'s own `--refresh`.
- **Verified live**: fetched the Altius menu, confirmed a
  `week_html_cache` row appeared in `orderability.db` with a
  `fetched_at`/`expires_at` exactly 1 hour apart, then **fully killed
  and restarted the dev server process** (not just a code-reload -- an
  actual new process, empty in-process dict) and fetched the same menu
  again: `fetched_at` was byte-for-byte identical to before the
  restart, proving the menu was served entirely from SQLite with zero
  live Restopolis fetch.
- New tests in `tests/test_orderability_cache.py` (6, covering
  get/set/overwrite/independence/expiry, plus one constructing a
  second `OrderabilityCache` on the same db file to prove persistence)
  and `tests/test_orderability_service.py` (3, covering a second
  `OrderabilityService` instance reusing the cache without a live
  fetch, `refresh=True` still bypassing it, and the TTL being
  configurable/expiry being honored). Tests: 93 JS, 190 Python (9 new),
  all passing.
