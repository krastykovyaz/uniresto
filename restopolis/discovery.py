"""Discovers the full list of restaurants Restopolis knows about.

The Menu page always embeds a complete restaurant picker (a searchable
dropdown), regardless of which restaurant is currently selected:

    <h3 class="site" data-site="30354">Université de Luxembourg Campus Kirchberg</h3>
    <a class="restaurant-name" data-site="30354"
       href="/eRestauration/CustomerServices/Menu/BtnChangeRestaurant?pRestaurantSelection=164">
       UDL-CKB - Altius - Restaurant</a>

This module parses that picker so restaurant ids in restaurants.yaml can
be independently re-verified against the live site.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from restopolis.client import BASE_URL, USER_AGENT

logger = logging.getLogger("restopolis.discovery")

_RESTAURANT_ID_RE = re.compile(r"pRestaurantSelection=(\d+)")


@dataclass
class DiscoveredRestaurant:
    name: str
    restaurant_id: int
    site_id: int | None
    site_name: str | None


def fetch_restaurant_list_html(timeout: float = 15.0) -> str:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    resp = session.get(f"{BASE_URL}/Menu", timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_restaurant_list(html: str) -> list[DiscoveredRestaurant]:
    soup = BeautifulSoup(html, "html.parser")
    picker = soup.select_one(".restaurant-selector-list")
    if picker is None:
        raise RuntimeError(
            "Could not find .restaurant-selector-list in the Menu page HTML -- "
            "Restopolis may have changed its restaurant picker markup."
        )

    results: list[DiscoveredRestaurant] = []
    current_site_name: str | None = None
    for el in picker.find_all(["h3", "a"], recursive=True):
        if el.name == "h3" and "site" in el.get("class", []):
            current_site_name = el.get_text(strip=True)
        elif el.name == "a" and "restaurant-name" in el.get("class", []):
            href = el.get("href", "")
            match = _RESTAURANT_ID_RE.search(href)
            if not match:
                logger.warning("[WARN] Restaurant link without a parseable id: %r", href)
                continue
            site_id_raw = el.get("data-site")
            results.append(
                DiscoveredRestaurant(
                    name=el.get_text(strip=True),
                    restaurant_id=int(match.group(1)),
                    site_id=int(site_id_raw) if site_id_raw and site_id_raw.isdigit() else None,
                    site_name=current_site_name,
                )
            )
    return results


def find_by_name(restaurants: list[DiscoveredRestaurant], name: str) -> DiscoveredRestaurant | None:
    for r in restaurants:
        if r.name == name:
            return r
    return None
