"""Shared test doubles for orderability tests. Not a test_*.py file itself
(pytest won't collect it), imported by the ones that need it."""

from __future__ import annotations

from restopolis.client import RestopolisError, WeekOutOfRangeError


class FakeRestopolisClient:
    """Stands in for RestopolisClient: no network. `week_html_by_offset`
    maps weeks_ahead -> HTML string. `max_weeks_ahead` simulates the real
    site's upper clamp (raises WeekOutOfRangeError beyond it, exactly like
    the real client does when it detects clamping)."""

    def __init__(self, week_html_by_offset: dict[int, str], max_weeks_ahead: int = 6, fail: bool = False):
        self.week_html_by_offset = week_html_by_offset
        self.max_weeks_ahead = max_weeks_ahead
        self.fail = fail
        self.calls: list[int] = []

    def fetch_week_html(self, restaurant, weeks_ahead, lang="fr"):
        self.calls.append(weeks_ahead)
        if self.fail:
            raise RestopolisError("simulated network failure")
        if weeks_ahead > self.max_weeks_ahead:
            raise WeekOutOfRangeError(
                f"Requested {weeks_ahead} weeks ahead but Restopolis clamps at {self.max_weeks_ahead}"
            )
        html = self.week_html_by_offset.get(weeks_ahead)
        if html is None:
            raise RestopolisError(f"no fixture registered for weeks_ahead={weeks_ahead}")
        return html
