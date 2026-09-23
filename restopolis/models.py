"""Plain data structures shared across the scraper modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RestaurantConfig:
    code: str
    name: str
    restaurant_id: int
    service_id: int
    site_name: str | None = None
    site_id: int | None = None


@dataclass
class MenuItem:
    category: str
    name: str
    description: str | None
    price: float | None
    allergens: list[dict] = field(default_factory=list)
    dietary: list[str] = field(default_factory=list)
    raw_text: str = ""
    sort_order: int = 0
    # Parsed from the product name (see restopolis/weight.py) -- Restopolis
    # has no dedicated weight field. None/None when the name doesn't state
    # one; never invented. See restopolis/weight.py's module docstring.
    weight_value: float | None = None
    weight_unit: str | None = None

    @property
    def is_vegetarian(self) -> bool:
        return "vegetarian" in self.dietary or "vegan" in self.dietary

    @property
    def is_vegan(self) -> bool:
        return "vegan" in self.dietary


@dataclass
class DailyMenu:
    restaurant_code: str
    restaurant_name: str
    menu_date: date
    service_name: str
    service_time: str | None
    source_url: str
    items: list[MenuItem] = field(default_factory=list)
    is_no_products: bool = False
