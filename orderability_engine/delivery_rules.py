"""OUR delivery business rule -- deliberately separate from Restopolis.

This is a UniResto rule, not something Restopolis exposes or enforces.
Restopolis's own ordering window (read live by orderability/detector.py)
and this deadline can disagree, and the orderability service reports both
independently rather than letting one overwrite the other (see task spec
§7/§12 and orderability/models.py's OrderabilityResult).

Current rule: orders for date D must be placed by 08:00 Europe/Luxembourg
on D itself, the SAME day -- e.g. an order for 2026-09-24 is possible up
until 08:00 on 2026-09-24; an order for 2026-09-25 up until 08:00 on
2026-09-25. (An earlier v1 rule required ordering by 08:30 the day
*before* D; this supersedes it -- see README.md Part 20.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from orderability_engine.models import OurDeliveryRule, TZINFO


@dataclass
class DeliveryRuleConfig:
    cutoff_time: time = time(8, 0)
    days_before: int = 0  # cutoff falls on target_date - days_before (0 = same day)


DEFAULT_RULE_CONFIG = DeliveryRuleConfig()


def compute_our_deadline(target_date: date, config: DeliveryRuleConfig = DEFAULT_RULE_CONFIG) -> datetime:
    deadline_date = target_date - timedelta(days=config.days_before)
    return datetime.combine(deadline_date, config.cutoff_time, tzinfo=TZINFO)


def evaluate_our_delivery(
    target_date: date,
    restopolis_ordering_available: bool | None,
    restopolis_menu_available: bool | None,
    now: datetime | None = None,
    config: DeliveryRuleConfig = DEFAULT_RULE_CONFIG,
) -> OurDeliveryRule:
    """Our delivery is only offered when Restopolis itself confirms both a
    menu and open ordering AND our own cutoff hasn't passed yet. We never
    promise delivery Restopolis itself wouldn't allow."""
    now = now or datetime.now(TZINFO)
    deadline = compute_our_deadline(target_date, config)

    restopolis_ok = restopolis_ordering_available is True and restopolis_menu_available is True
    within_deadline = now <= deadline

    return OurDeliveryRule(deadline=deadline, available=bool(restopolis_ok and within_deadline))
