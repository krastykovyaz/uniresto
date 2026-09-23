"""Parses a Restopolis Menu page (one week) into structured DailyMenu objects.

Markup reference (see tests/fixtures/*.html for full real examples):

    <div id="date-selector">
        <a class="day" data-date="21.09.2026" ...>lun., 21.09.</a>   <!-- x7, Mon..Sun -->
        ...
    </div>

    <div class="menu-slider daily-menu">
        <div>                                    <!-- one per day, SAME ORDER as date-selector -->
            <div class="formulaeContainer">       <!-- or class="formulaeContainer no-products" -->
                <div class="course-name">Entrée</div>
                <div class="product-name">Minestrone</div>
                <span class="product-allergens">6, 7, 9, 12</span>
                <img class="product-flag" src="/.../vegetarian.png" />
                <img class="product-flag" src="/.../gluten_free.jpg" />
                <div class="product-description"></div>
                ... more products ...
                <div class="course-name">Végétarien</div>
                ...
            </div>
            <div class="constantProductContainer" style="display:none">
                <!-- same course-name/product-name/... structure -->
            </div>
        </div>
        ... 6 more day divs ...
    </div>

IMPORTANT: the per-day `<div>` inside `.menu-slider` carries no date
attribute of its own in the server-rendered HTML (slick.js only adds
data-slick-index client-side, after the fact). The only reliable link
between a day's content and its calendar date is POSITION: the Nth day
div corresponds to the Nth `#date-selector a.day` (both are always
Monday..Sunday, 7 entries). This function verifies the two lists have
matching lengths and raises rather than silently misaligning them.
"""

from __future__ import annotations

import html as html_module
import logging
from datetime import date, datetime

from bs4 import BeautifulSoup
from bs4.element import Tag

from restopolis.allergens import parse_allergens
from restopolis.flags import parse_flag
from restopolis.models import DailyMenu, MenuItem
from restopolis.weight import parse_weight

logger = logging.getLogger("restopolis.parser")

SERVICE_NAME_MENU = "Menu"
SERVICE_NAME_CONSTANT = "Constant products"

_ITEM_SELECTOR = ".course-name, .product-name, .product-allergens, .product-flag, .product-description"


class MenuParseError(Exception):
    """Raised when the page structure doesn't match what this parser expects."""


def _parse_date_ddmmyyyy(text: str) -> date:
    return datetime.strptime(text.strip(), "%d.%m.%Y").date()


def extract_service_time(label_text: str) -> str | None:
    import re

    match = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", label_text)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


def _parse_container_items(container: Tag) -> list[MenuItem]:
    items: list[MenuItem] = []
    current_category: str | None = None
    current: MenuItem | None = None
    sort_order = 0

    for el in container.select(_ITEM_SELECTOR):
        classes = el.get("class", [])
        if "course-name" in classes:
            current_category = el.get_text(strip=True)
        elif "product-name" in classes:
            if current is not None:
                items.append(current)
            if current_category is None:
                logger.warning(
                    "[WARN] Product '%s' has no preceding category; using 'Unknown'",
                    el.get_text(strip=True),
                )
            item_name = el.get_text(strip=True)
            weight_value, weight_unit = parse_weight(item_name)
            current = MenuItem(
                category=current_category or "Unknown",
                name=item_name,
                description=None,
                weight_value=weight_value,
                weight_unit=weight_unit,
                price=None,
                sort_order=sort_order,
            )
            sort_order += 1
        elif "product-allergens" in classes:
            raw = el.get_text(strip=True)
            if current is not None:
                current.allergens = parse_allergens(raw)
                current.raw_text = raw
            else:
                logger.warning("[WARN] Allergens span found with no active product: %r", raw)
        elif "product-flag" in classes:
            src = el.get("src", "")
            if current is not None and src:
                current.dietary.append(parse_flag(src))
        elif "product-description" in classes:
            text = el.get_text(strip=True)
            if current is not None:
                current.description = text or None

    if current is not None:
        items.append(current)

    return items


def align_day_blocks(soup: BeautifulSoup) -> list[tuple[date, Tag]]:
    """Pair each #date-selector day with its .menu-slider day block, in
    order. Shared by parse_week_html and orderability/detector.py (which
    also needs the raw per-day block to read the reservation button, not
    just the parsed menu items). Raises MenuParseError if the two lists
    can't be safely aligned -- see the module docstring for why alignment
    is positional rather than attribute-based."""
    day_links = soup.select("#date-selector a.day")
    if not day_links:
        raise MenuParseError(
            "No #date-selector a.day elements found -- Restopolis may have "
            "changed the date selector markup. Cannot determine which "
            "calendar dates the menu slides correspond to."
        )

    slider = soup.select_one(".menu-slider")
    if slider is None:
        raise MenuParseError(
            "No .menu-slider element found -- Restopolis may have changed "
            "the menu page markup."
        )
    day_divs = slider.find_all("div", recursive=False)

    if len(day_divs) != len(day_links):
        raise MenuParseError(
            f"Mismatch between {len(day_links)} date-selector days and "
            f"{len(day_divs)} menu-slider day blocks -- cannot safely map "
            "menu content to calendar dates. Restopolis markup may have changed."
        )

    return [(_parse_date_ddmmyyyy(link["data-date"]), div) for link, div in zip(day_links, day_divs)]


def parse_week_html(
    html: str,
    restaurant_code: str,
    restaurant_name: str,
    source_url: str,
    include_constant_products: bool = True,
) -> list[DailyMenu]:
    """Parse one full week's Menu page into a list of DailyMenu (one per
    date x service_name, e.g. 7 dates x 2 services = up to 14 entries)."""
    soup = BeautifulSoup(html, "html.parser")

    if restaurant_name not in html_module.unescape(html):
        raise MenuParseError(
            f"Page does not mention restaurant name {restaurant_name!r}; "
            "the wrong restaurant may have been loaded."
        )

    aligned_days = align_day_blocks(soup)

    service_tab = soup.select_one('[data-role="formula-products"]')
    service_time = extract_service_time(service_tab.get_text(" ", strip=True)) if service_tab else None

    results: list[DailyMenu] = []

    for menu_date, day_div in aligned_days:
        formulae = day_div.select_one(".formulaeContainer")
        if formulae is not None:
            is_empty = "no-products" in formulae.get("class", [])
            items = [] if is_empty else _parse_container_items(formulae)
            if not items and not is_empty:
                logger.warning(
                    "[WARN] %s %s: formulaeContainer present but no items parsed",
                    restaurant_code, menu_date,
                )
            results.append(
                DailyMenu(
                    restaurant_code=restaurant_code,
                    restaurant_name=restaurant_name,
                    menu_date=menu_date,
                    service_name=SERVICE_NAME_MENU,
                    service_time=service_time,
                    source_url=source_url,
                    items=items,
                    is_no_products=is_empty,
                )
            )
        else:
            logger.warning(
                "[WARN] %s %s: no .formulaeContainer found for this day",
                restaurant_code, menu_date,
            )

        if include_constant_products:
            constant = day_div.select_one(".constantProductContainer")
            if constant is not None:
                is_empty = "no-products" in constant.get("class", [])
                items = [] if is_empty else _parse_container_items(constant)
                results.append(
                    DailyMenu(
                        restaurant_code=restaurant_code,
                        restaurant_name=restaurant_name,
                        menu_date=menu_date,
                        service_name=SERVICE_NAME_CONSTANT,
                        service_time=None,
                        source_url=source_url,
                        items=items,
                        is_no_products=is_empty,
                    )
                )

    return results


def get_week_dates(html: str) -> list[date]:
    """Return the 7 calendar dates (Mon..Sun) this week's page covers."""
    soup = BeautifulSoup(html, "html.parser")
    day_links = soup.select("#date-selector a.day")
    return [_parse_date_ddmmyyyy(a["data-date"]) for a in day_links]
