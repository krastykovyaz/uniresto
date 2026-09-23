"""HTTP client for the Restopolis menu website.

Discovered mechanism (see README.md "How restaurant/date selection works"
for the full writeup):

  1. GET  Menu/BtnChangeLanguage?pNewLanguage=fr   -> sets .AspNetCore.Culture cookie
  2. GET  Menu/BtnChangeRestaurant?pRestaurantSelection=<id>
                                                    -> sets CustomerServices.Restopolis.SelectedRestaurant
                                                       and .SelectedService cookies, and starts a
                                                       CustomerServices.Session cookie
  3. GET  Menu/NextWeek / Menu/PreviousWeek         -> shifts a week pointer stored server-side,
                                                       keyed by the CustomerServices.Session cookie.
                                                       PreviousWeek is clamped: it will never go
                                                       earlier than the real-world current week.
  4. GET  Menu                                      -> returns one HTML page with all 7 days of the
                                                       currently selected week already rendered
                                                       (a slick carousel with one slide per day).

There is no JSON/XHR menu API: the full week's menu is server-rendered
HTML. No JavaScript execution or session storage beyond cookies is
required, so plain `requests` is sufficient -- Playwright is not needed.
"""

from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

import requests

from restopolis.models import RestaurantConfig

logger = logging.getLogger("restopolis.client")

BASE_URL = "https://ssl.education.lu/eRestauration/CustomerServices"
USER_AGENT = (
    "uniresto-menu-scraper/0.1 "
    "(University of Luxembourg Campus Kirchberg menu collector; "
    "contact: alexkovyaz@gmail.com)"
)


class RestopolisError(Exception):
    """Base class for all client-level scraping failures."""


class RestopolisHTTPError(RestopolisError):
    """Raised when an HTTP request keeps failing after retries."""


class RestaurantSelectionError(RestopolisError):
    """Raised when selecting a restaurant did not take effect server-side."""


class WeekOutOfRangeError(RestopolisError):
    """Raised when Restopolis silently clamped week navigation to a
    different week than requested (it clamps at both ends: never before
    the real-world current week, and -- discovered empirically, not
    documented anywhere -- capped some number of weeks ahead too)."""


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


@dataclass
class ClientConfig:
    request_delay: float = 1.0  # seconds between requests, to stay polite
    timeout: float = 15.0
    max_retries: int = 4
    backoff_base: float = 1.5  # exponential backoff base, in seconds


class RestopolisClient:
    def __init__(self, config: ClientConfig | None = None):
        self.config = config or ClientConfig()

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        session.headers["Accept-Language"] = "fr-LU,fr;q=0.9,en;q=0.5"
        return session

    def _get(self, session: requests.Session, path: str, params: dict | None = None) -> requests.Response:
        url = f"{BASE_URL}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                resp = session.get(url, params=params, timeout=self.config.timeout)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "[WARN] Request error on %s (attempt %d/%d): %s",
                    url, attempt, self.config.max_retries, exc,
                )
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = RestopolisHTTPError(
                        f"HTTP {resp.status_code} from {url}"
                    )
                    logger.warning(
                        "[WARN] Transient HTTP %d on %s (attempt %d/%d)",
                        resp.status_code, url, attempt, self.config.max_retries,
                    )
                elif resp.status_code >= 400:
                    # Non-transient client error: fail fast, don't retry.
                    raise RestopolisHTTPError(
                        f"HTTP {resp.status_code} from {url}: {resp.text[:200]!r}"
                    )
                else:
                    time.sleep(self.config.request_delay)
                    return resp

            if attempt < self.config.max_retries:
                wait = self.config.backoff_base ** attempt
                time.sleep(wait)

        raise RestopolisHTTPError(
            f"Giving up on {url} after {self.config.max_retries} attempts"
        ) from last_exc

    def fetch_week_html(
        self,
        restaurant: RestaurantConfig,
        weeks_ahead: int,
        lang: str = "fr",
    ) -> str:
        """Fetch the full Menu page HTML for `restaurant`, `weeks_ahead` weeks
        after the real-world current week (0 = current week).

        Raises RestaurantSelectionError if the server did not actually
        switch to the requested restaurant (e.g. the id no longer exists).
        """
        if weeks_ahead < 0:
            raise ValueError(
                f"weeks_ahead must be >= 0 (Restopolis cannot show past weeks), got {weeks_ahead}"
            )

        session = self._new_session()

        logger.info("[INFO] Setting language to %s", lang)
        self._get(session, "/Menu/BtnChangeLanguage", params={"pNewLanguage": lang})

        logger.info(
            "[INFO] Selecting restaurant %s (id=%d)",
            restaurant.name, restaurant.restaurant_id,
        )
        self._get(
            session,
            "/Menu/BtnChangeRestaurant",
            params={"pRestaurantSelection": restaurant.restaurant_id},
        )

        for i in range(weeks_ahead):
            logger.info("[INFO] Advancing to next week (%d/%d)", i + 1, weeks_ahead)
            self._get(session, "/Menu/NextWeek")

        logger.info("[INFO] Loading menu")
        resp = self._get(session, "/Menu")
        page_html = resp.text

        if restaurant.name not in html.unescape(page_html):
            raise RestaurantSelectionError(
                f"Selecting restaurant_id={restaurant.restaurant_id} did not select "
                f"'{restaurant.name}' -- the server returned a different restaurant. "
                "The restaurant id in restaurants.yaml is likely stale; "
                "re-run `python scraper.py discover` to find the current id."
            )

        # Restopolis's NextWeek navigation is clamped at both ends (see
        # WeekOutOfRangeError docstring). If we asked for N weeks ahead but
        # the server actually gave us a different week, silently using that
        # HTML would mislabel its contents as the requested week's data.
        from restopolis.parser import get_week_dates  # local import: avoids a hard import-time cycle

        expected_week_start = _week_start(date.today()) + timedelta(weeks=weeks_ahead)
        actual_dates = get_week_dates(page_html)
        actual_week_start = actual_dates[0] if actual_dates else None
        if actual_week_start != expected_week_start:
            raise WeekOutOfRangeError(
                f"Requested the week starting {expected_week_start} ({weeks_ahead} week(s) "
                f"ahead) but Restopolis returned the week starting {actual_week_start} "
                "instead -- its week navigation clamps at both ends and this request "
                "fell outside the currently browsable range."
            )

        return page_html
