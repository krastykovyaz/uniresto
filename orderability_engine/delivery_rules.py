"""OUR delivery business rule -- deliberately separate from Restopolis.

This is a UniResto rule, not something Restopolis exposes or enforces.
Restopolis's own ordering window (read live by orderability/detector.py)
and this deadline can disagree, and the orderability service reports both
independently rather than letting one overwrite the other (see task spec
§7/§12 and orderability/models.py's OrderabilityResult).

Current rule: orders for date D must be placed by 13:00 Europe/Luxembourg
on D itself, the SAME day -- e.g. an order for 2026-09-24 is possible up
until 13:00 on 2026-09-24; an order for 2026-09-25 up until 13:00 on
2026-09-25. (An earlier v1 rule required ordering by 08:30 the day
*before* D, then a v2 rule tightened the same-day cutoff to 08:00;
this supersedes both -- see README.md Part 20/59.)

Part 59 adds a SECOND, earlier same-day cutoff (EARLY_CUTOFF_CONFIG,
08:00) for specific dishes that need to be pre-ordered well before
service because they're prepared to order (grill/BBQ mains, salmon) --
confirmed by the admin as real campus-kitchen practice, not something
Restopolis exposes either. Which dishes that applies to is decided by
menu_service.requires_early_order(), never here -- this module only
knows about TIMES, not which items they apply to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from orderability_engine.models import OurDeliveryRule, TZINFO


@dataclass
class DeliveryRuleConfig:
    cutoff_time: time = time(13, 0)
    days_before: int = 0  # cutoff falls on target_date - days_before (0 = same day)


DEFAULT_RULE_CONFIG = DeliveryRuleConfig()
EARLY_CUTOFF_CONFIG = DeliveryRuleConfig(cutoff_time=time(8, 0))


def compute_our_deadline(target_date: date, config: DeliveryRuleConfig = DEFAULT_RULE_CONFIG) -> datetime:
    deadline_date = target_date - timedelta(days=config.days_before)
    return datetime.combine(deadline_date, config.cutoff_time, tzinfo=TZINFO)


def evaluate_our_delivery(
    target_date: date,
    restopolis_menu_available: bool | None,
    now: datetime | None = None,
    config: DeliveryRuleConfig = DEFAULT_RULE_CONFIG,
) -> OurDeliveryRule:
    """Our delivery is offered whenever Restopolis confirms a menu exists
    AND our own cutoff hasn't passed yet -- deliberately NOT gated on
    Restopolis's own reservation-button signal (restopolis_ordering_available).
    Our courier buys the food in person at the canteen counter rather than
    through Restopolis's online reservation flow, so that button being
    disabled doesn't stop us: the canteen is still physically serving for
    as long as its menu is up and service is running (confirmed live,
    2026-09-28 -- Restopolis closes its own reservation button hours
    before service even starts some days, while the canteen keeps serving
    walk-ins all through its stated service window)."""
    now = now or datetime.now(TZINFO)
    deadline = compute_our_deadline(target_date, config)

    restopolis_ok = restopolis_menu_available is True
    within_deadline = now <= deadline

    return OurDeliveryRule(deadline=deadline, available=bool(restopolis_ok and within_deadline))


# Part 76: when an undelivered order stops being a courier's live job and
# moves to the Delivery screen's "Expired" section -- 13:30 on its own
# date, Europe/Luxembourg. Confirmed against real Restopolis data
# (restaurants/status DOES report a real service_start/service_end, e.g.
# 11:00-14:30 for Altius) that campus lunch service is realistically
# over by then; a fixed, explicitly-chosen time rather than each
# restaurant's own service_end so it doesn't vary day to day.
DELIVERY_EXPIRY_TIME = time(13, 30)


def is_delivery_expired(order_date: date, now: datetime | None = None) -> bool:
    """True once it's past DELIVERY_EXPIRY_TIME on `order_date` in
    Europe/Luxembourg -- decided server-side from the real local clock,
    never from a courier's phone (whose clock/timezone could be anything,
    and whose UTC date runs up to 2 hours off Luxembourg's)."""
    now = now or datetime.now(TZINFO)
    return now >= datetime.combine(order_date, DELIVERY_EXPIRY_TIME, tzinfo=TZINFO)
