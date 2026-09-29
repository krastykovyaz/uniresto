"""The stats the admin gets on request (the "📊 Stats" button in the bot, see
telegram_notify.py and app.py's /telegram/webhook): the same numbers as the
evening report (daily_report.py) -- app opens with their per-QR-source split,
menu views, orders placed, Delivery-screen visits -- for today so far plus the
STATS_PREVIOUS_DAYS full days before it, and a total across all of them.

Every QR / ?src= label that shows up in the window is listed, in EVERY day's
block (0 where it wasn't scanned that day), busiest first over the whole
window: nothing is registered in advance, so a QR added tomorrow simply
appears the first time someone scans it (page_views.py groups by whatever
labels it has actually seen)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from orderability_engine.daily_report import local_day_bounds
from orderability_engine.models import TZINFO
from orderability_engine.orders import OrderStore
from orderability_engine.page_views import PageViewStore

STATS_PREVIOUS_DAYS = 3  # "last 3 days" -- plus today, which is still in progress


def _day_label(day: date, today: date) -> str:
    text = day.strftime("%a %d %b")
    if day == today:
        return f"{text} (today, so far)"
    if day == today - timedelta(days=1):
        return f"{text} (yesterday)"
    return text


def collect_stats(page_views: PageViewStore, order_store: OrderStore, today: date, previous_days: int = STATS_PREVIOUS_DAYS) -> list[dict]:
    """One dict per day, newest first: {"day", "home", "by_source": {label: n},
    "menu", "orders", "delivery"}."""
    days = []
    for offset in range(previous_days + 1):
        day = today - timedelta(days=offset)
        start, end = local_day_bounds(day)
        days.append(
            {
                "day": day,
                "home": page_views.count_between("home", start, end),
                "by_source": dict(page_views.source_counts_between("home", start, end)),
                "menu": page_views.count_between("menu", start, end),
                "orders": order_store.count_created_between(start, end),
                "delivery": page_views.count_between("delivery", start, end),
            }
        )
    return days


def _block(title: str, home: int, by_source: dict, order: list[str], menu: int, orders: int, delivery: int) -> list[str]:
    lines = [title, f"Opened the app: {home}"]
    lines += [f"  {label}: {by_source.get(label, 0)}" for label in order]
    lines += [f"Viewed a menu: {menu}", f"Orders placed: {orders}", f"Opened deliveries: {delivery}"]
    return lines


def build_stats_message(page_views: PageViewStore, order_store: OrderStore, now: datetime | None = None) -> str:
    now = (now or datetime.now(TZINFO)).astimezone(TZINFO)
    today = now.date()
    days = collect_stats(page_views, order_store, today)

    totals_by_source: dict[str, int] = {}
    for d in days:
        for label, n in d["by_source"].items():
            totals_by_source[label] = totals_by_source.get(label, 0) + n
    # busiest over the whole window first, then alphabetically
    order = [label for label, _ in sorted(totals_by_source.items(), key=lambda kv: (-kv[1], kv[0]))]

    lines = [f"UniResto stats -- {now.strftime('%a %d %b, %H:%M')}", ""]
    for d in days:
        lines += _block(_day_label(d["day"], today), d["home"], d["by_source"], order, d["menu"], d["orders"], d["delivery"])
        lines.append("")
    lines += _block(
        f"Total, last {len(days)} days",
        sum(d["home"] for d in days),
        totals_by_source,
        order,
        sum(d["menu"] for d in days),
        sum(d["orders"] for d in days),
        sum(d["delivery"] for d in days),
    )
    return "\n".join(lines)
