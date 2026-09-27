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


# Part 76: when an undelivered order stops being a courier's live job and
# moves to the Delivery screen's "Expired" section -- 15:00 on its own
# date, Europe/Luxembourg. OUR rule, same as the 13:00/08:00 cutoffs
# above: Restopolis reports no service hours at all (service_start/
# service_end are always None on the live site), so there's no real
# per-restaurant closing time to anchor this to. Lunch-only canteens,
# ordering closes at 13:00, so 15:00 leaves a full delivery window after
# the last possible order before calling it missed.
DELIVERY_EXPIRY_TIME = time(15, 0)


def is_delivery_expired(order_date: date, now: datetime | None = None) -> bool:
    """True once it's past DELIVERY_EXPIRY_TIME on `order_date` in
    Europe/Luxembourg -- decided server-side from the real local clock,
    never from a courier's phone (whose clock/timezone could be anything,
    and whose UTC date runs up to 2 hours off Luxembourg's)."""
    now = now or datetime.now(TZINFO)
    return now >= datetime.combine(order_date, DELIVERY_EXPIRY_TIME, tzinfo=TZINFO)
