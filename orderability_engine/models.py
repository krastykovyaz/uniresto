"""Data structures for the orderability engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

TIMEZONE_NAME = "Europe/Luxembourg"
TZINFO = ZoneInfo(TIMEZONE_NAME)

# Every value this detector can actually justify from a real Restopolis
# signal, plus the two "we don't/can't know" values. See
# orderability/detector.py and README.md ("Status decision table") for
# exactly which signals produce which status -- nothing here is guessed.
STATUS_VALUES = (
    "available",
    "closed",
    "no_menu",
    "ordering_closed",
    "past_date",
    "not_yet_published",
    "unknown",
)


@dataclass
class RestopolisDayStatus:
    """What Restopolis's own page says about one (restaurant, date)."""

    restaurant_code: str
    restaurant_name: str
    target_date: date

    # None means "we could not determine this from Restopolis" -- never
    # guessed as True/False.
    menu_available: bool | None
    ordering_available: bool | None
    reservation_signal_text: str | None  # raw button text, e.g. "Réserver" / "Réservation clôturée"

    service_start: str | None
    service_end: str | None
    restopolis_order_deadline: str | None  # always None today: not exposed publicly, see README

    item_count: int
    menu_hash: str  # for change detection between checks
    source_url: str

    fetch_error: str | None = None  # set when Restopolis could not be reached/parsed at all


@dataclass
class OurDeliveryRule:
    deadline: datetime | None  # tz-aware, Europe/Luxembourg
    available: bool


@dataclass
class OrderabilityResult:
    restaurant_code: str
    restaurant_name: str
    target_date: date
    timezone: str

    restaurant_open: bool | None
    menu_available: bool | None
    ordering_available: bool | None
    order_deadline: str | None  # Restopolis's own deadline, if ever exposed (currently always null)

    service_start: str | None
    service_end: str | None

    status: str
    reason: str | None

    our_delivery: OurDeliveryRule

    source: str = "Restopolis"
    checked_at: datetime = field(default_factory=lambda: datetime.now())
    from_cache: bool = False
    # Internal-only (not in to_dict/to_api_dict): lets get_next_available_dates
    # recognize "we've scanned past Restopolis's browsable horizon" without
    # string-matching `reason`, which is for humans/logs, not control flow.
    horizon_exceeded: bool = False

    def to_dict(self) -> dict:
        """Flat shape, matching the CLI/spec example in the task's §3."""
        return {
            "restaurant": self.restaurant_name,
            "date": self.target_date.isoformat(),
            "timezone": self.timezone,
            "restaurant_open": self.restaurant_open,
            "menu_available": self.menu_available,
            "ordering_available": self.ordering_available,
            "order_deadline": self.order_deadline,
            "service_start": self.service_start,
            "service_end": self.service_end,
            "status": self.status,
            "reason": self.reason,
            "our_order_deadline": self.our_delivery.deadline.isoformat() if self.our_delivery.deadline else None,
            "our_delivery_orderable": self.our_delivery.available,
            "source": self.source,
            "checked_at": self.checked_at.isoformat(),
            "from_cache": self.from_cache,
        }

    def to_api_dict(self) -> dict:
        """Nested shape, matching the task's §20 API example."""
        return {
            "restaurant": self.restaurant_name,
            "date": self.target_date.isoformat(),
            "restopolis": {
                "open": self.restaurant_open,
                "menu_available": self.menu_available,
                "ordering_available": self.ordering_available,
                "service_start": self.service_start,
                "service_end": self.service_end,
                "order_deadline": self.order_deadline,
            },
            "our_delivery": {
                "deadline": self.our_delivery.deadline.isoformat() if self.our_delivery.deadline else None,
                "available": self.our_delivery.available,
            },
            "status": self.status,
            "reason": self.reason,
            "checked_at": self.checked_at.isoformat(),
            "from_cache": self.from_cache,
        }


def hash_menu_signature(item_count: int, service_start: str | None, service_end: str | None, ordering_available: bool | None) -> str:
    raw = f"{item_count}|{service_start}|{service_end}|{ordering_available}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
