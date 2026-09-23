"""Exports scraped menus to data/menus.json.

Two entry points:
  - export_json_from_menus: builds the JSON straight from the DailyMenu
    objects produced by this run's scrape (used by scraper.py so that
    `--format json` reflects exactly what was just scraped, regardless of
    whether it was also persisted to SQLite).
  - export_json: builds the JSON by reading back from an existing
    RestopolisDatabase (useful to re-export without re-scraping).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from restopolis.database import RestopolisDatabase
from restopolis.models import DailyMenu

logger = logging.getLogger("restopolis.exporter")


def _write_payload(by_restaurant: dict[str, dict], out_path: str | Path) -> Path:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "restaurants": list(by_restaurant.values()),
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("[INFO] Wrote %s (%d restaurants)", out_path, len(by_restaurant))
    return out_path


def export_json_from_menus(
    menus: list[DailyMenu],
    restaurant_names: dict[str, str],
    out_path: str | Path = "data/menus.json",
) -> Path:
    """Build data/menus.json directly from freshly scraped DailyMenu objects,
    without touching SQLite."""
    by_restaurant: dict[str, dict] = {}
    for m in menus:
        if m.restaurant_code not in by_restaurant:
            by_restaurant[m.restaurant_code] = {
                "code": m.restaurant_code,
                "name": restaurant_names.get(m.restaurant_code, m.restaurant_name),
                "menus": [],
            }
        by_restaurant[m.restaurant_code]["menus"].append(
            {
                "date": m.menu_date.isoformat(),
                "service": m.service_name,
                "service_time": m.service_time,
                "source_url": m.source_url,
                "items": [
                    {
                        "category": it.category,
                        "name": it.name,
                        "description": it.description,
                        "price": it.price,
                        "weight_value": it.weight_value,
                        "weight_unit": it.weight_unit,
                        "allergens": it.allergens,
                        "dietary": it.dietary,
                        "source": "Restopolis",
                    }
                    for it in m.items
                ],
            }
        )
    return _write_payload(by_restaurant, out_path)


def export_json(
    db: RestopolisDatabase,
    out_path: str | Path = "data/menus.json",
    restaurant_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Path:
    menus = db.fetch_menus(restaurant_code=restaurant_code, start_date=start_date, end_date=end_date)

    by_restaurant: dict[str, dict] = {}
    for m in menus:
        code = m["restaurant_code"]
        if code not in by_restaurant:
            by_restaurant[code] = {
                "code": code,
                "name": m["restaurant_name"],
                "menus": [],
            }
        by_restaurant[code]["menus"].append(
            {
                "date": m["date"],
                "service": m["service"],
                "service_time": m["service_time"],
                "source_url": m["source_url"],
                "scraped_at": m["scraped_at"],
                "items": [
                    {
                        "category": it["category"],
                        "name": it["name"],
                        "description": it["description"],
                        "price": it["price"],
                        "weight_value": it["weight_value"],
                        "weight_unit": it["weight_unit"],
                        "allergens": it["allergens"],
                        "dietary": it["dietary"],
                        "source": "Restopolis",
                    }
                    for it in m["items"]
                ],
            }
        )

    return _write_payload(by_restaurant, out_path)
