"""Restopolis Availability Detector.

Reads, per (restaurant, date), exactly what Restopolis's own Menu page
signals -- nothing inferred beyond that. Two independent signals exist on
the page, and they are genuinely independent (verified live, 2026-09-23):

1. **Menu content**: `.formulaeContainer` either has `.course-name` /
   `.product-name` items, or carries a `no-products` class and shows
   "Aucun plat programmé à cette date." This is `menu_available`.

2. **Reservation button**, inside `.action-buttons`:
   - `<button disabled>Réservation clôturée</button>` -> ordering closed
   - `<button onclick="...saml/login...RedirectToReservationView...">
      Réserver</button>` -> ordering open (leads to a SAML-login-gated
      reservation form we cannot complete anonymously, but its mere
      presence/enabled-state is the public signal)
   This is `ordering_available`. It was observed to be OPEN even on days
   with NO menu (e.g. a weekend) and CLOSED on days WITH a menu (e.g.
   today, once its service window has passed) -- the two signals really
   are independent, which is exactly why the task asks for them
   separately.

No cutoff *time* is exposed anywhere in the public HTML (no title/
aria/data attribute near the button carries one) -- only this binary
open/closed state. `restopolis_order_deadline` is therefore always
`None`; see README.md for how this was verified.

Empirically (live, 2026-09-23), Restopolis's own reservation window was a
rolling ~5-calendar-day-ahead window, and NextWeek browsing was capped at
6 weeks ahead -- but this module does NOT hardcode either number. It
re-derives "is this date within Restopolis's browsable range" from
`WeekOutOfRangeError` on every call, and "is ordering open" from the
button on every call.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from bs4 import BeautifulSoup

from restopolis.client import RestopolisClient, WeekOutOfRangeError
from restopolis.models import RestaurantConfig
from restopolis.parser import (
    MenuParseError,
    align_day_blocks,
    extract_service_time,
)
from orderability_engine.models import RestopolisDayStatus, hash_menu_signature

logger = logging.getLogger("orderability.detector")

MENU_SOURCE_URL = "https://ssl.education.lu/eRestauration/CustomerServices/Menu"


class PastDateError(Exception):
    """Raised when target_date is before the current (real-world) week --
    Restopolis's own PreviousWeek navigation is clamped there, so there is
    structurally no way to ask it about a past date."""


class HorizonExceededError(Exception):
    """Raised when target_date is beyond Restopolis's currently browsable
    horizon (an upper clamp, discovered dynamically -- see WeekOutOfRangeError)."""

    def __init__(self, message: str, discovered_weeks_ahead: int | None = None):
        super().__init__(message)
        self.discovered_weeks_ahead = discovered_weeks_ahead


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _read_reservation_signal(day_div) -> tuple[bool | None, str | None]:
    """Returns (ordering_available, raw_button_text)."""
    action_buttons = day_div.select_one(".action-buttons")
    if action_buttons is None:
        return None, None
    button = action_buttons.select_one("button")
    if button is None:
        return None, None
    text = button.get_text(strip=True)
    is_disabled = button.has_attr("disabled")
    return (not is_disabled), text


def weeks_ahead_for(target_date: date, today: date | None = None) -> int:
    """Raises PastDateError if target_date is before the current week."""
    today = today or date.today()
    expected_week_start = _week_start(target_date)
    if expected_week_start < _week_start(today):
        raise PastDateError(
            f"{target_date} falls in a week before the current week ({_week_start(today)}); "
            "Restopolis's PreviousWeek navigation is clamped at today's week, so past dates "
            "cannot be checked."
        )
    return (expected_week_start - _week_start(today)).days // 7


def fetch_week_html_for_date(
    client: RestopolisClient,
    restaurant: RestaurantConfig,
    target_date: date,
    today: date | None = None,
) -> str:
    """Fetch the raw week HTML covering target_date. Raises PastDateError /
    HorizonExceededError when that's not possible. Callers that need
    several dates in the same week (e.g. get_next_available_dates) should
    cache this result themselves and call parse_day_status_from_html
    directly instead of re-fetching per date -- see orderability/service.py."""
    weeks_ahead = weeks_ahead_for(target_date, today)
    try:
        return client.fetch_week_html(restaurant, weeks_ahead)
    except WeekOutOfRangeError as exc:
        raise HorizonExceededError(str(exc)) from exc


def parse_day_status_from_html(html: str, restaurant: RestaurantConfig, target_date: date) -> RestopolisDayStatus:
    """Pure parsing: read Restopolis's signals for one date out of an
    already-fetched week HTML. Raises MenuParseError on structural changes."""
    soup = BeautifulSoup(html, "html.parser")
    aligned_days = align_day_blocks(soup)  # raises MenuParseError on structural change

    day_div = next((div for d, div in aligned_days if d == target_date), None)
    if day_div is None:
        raise MenuParseError(
            f"{target_date} not found among the {len(aligned_days)} days Restopolis "
            "returned for that week -- unexpected server response."
        )

    formulae = day_div.select_one(".formulaeContainer")
    if formulae is None:
        menu_available = None
        item_count = 0
    else:
        is_no_products = "no-products" in formulae.get("class", [])
        menu_available = not is_no_products
        item_count = 0 if is_no_products else len(formulae.select(".product-name"))

    ordering_available, reservation_text = _read_reservation_signal(day_div)

    service_tab = soup.select_one('[data-role="formula-products"]')
    service_time = extract_service_time(service_tab.get_text(" ", strip=True)) if service_tab else None
    service_start, service_end = (None, None)
    if service_time and "-" in service_time:
        service_start, service_end = service_time.split("-", 1)

    menu_hash = hash_menu_signature(item_count, service_start, service_end, ordering_available)

    return RestopolisDayStatus(
        restaurant_code=restaurant.code,
        restaurant_name=restaurant.name,
        target_date=target_date,
        menu_available=menu_available,
        ordering_available=ordering_available,
        reservation_signal_text=reservation_text,
        service_start=service_start,
        service_end=service_end,
        restopolis_order_deadline=None,  # never exposed publicly -- see module docstring
        item_count=item_count,
        menu_hash=menu_hash,
        source_url=MENU_SOURCE_URL,
    )


def get_restopolis_day_status(
    client: RestopolisClient,
    restaurant: RestaurantConfig,
    target_date: date,
    today: date | None = None,
) -> RestopolisDayStatus:
    """Convenience one-shot: fetch + parse a single (restaurant, date).
    For checking several dates that may share a week, fetch once with
    fetch_week_html_for_date and call parse_day_status_from_html per date
    instead (this is what OrderabilityService does)."""
    html = fetch_week_html_for_date(client, restaurant, target_date, today)
    return parse_day_status_from_html(html, restaurant, target_date)
