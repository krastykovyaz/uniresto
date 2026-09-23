"""Loads restaurant configuration from restaurants.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from restopolis.models import RestaurantConfig

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "restaurants.yaml"


def load_restaurants(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, RestaurantConfig]:
    """Load restaurants.yaml into a {code: RestaurantConfig} mapping."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    restaurants = {}
    for entry in raw.get("restaurants", []):
        cfg = RestaurantConfig(
            code=entry["code"],
            name=entry["name"],
            restaurant_id=int(entry["restaurant_id"]),
            service_id=int(entry["service_id"]),
            site_name=entry.get("site_name"),
            site_id=entry.get("site_id"),
            building=entry.get("building"),
        )
        restaurants[cfg.code] = cfg
    return restaurants
