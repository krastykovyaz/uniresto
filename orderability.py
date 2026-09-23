#!/usr/bin/env python3
"""CLI for the orderability engine.

Examples:
    python orderability.py --restaurant altius --date 2026-09-24
    python orderability.py --restaurant altius --date 2026-09-24 --refresh
    python orderability.py --restaurant brasserie-johns --date 2026-09-26
    python orderability.py --restaurant altius --next-available
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from orderability_engine.cache import OrderabilityCache
from orderability_engine.models import OrderabilityResult
from orderability_engine.service import OrderabilityService
from restopolis.config import load_restaurants
from scraper import parse_date, slug_for

logger = logging.getLogger("orderability.cli")

_WEEKDAY_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
_MONTH_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _format_date_long(d) -> str:
    return f"{_WEEKDAY_FR[d.weekday()]} {d.day} {_MONTH_FR[d.month]} {d.year}"


def _yes_no(v: bool | None) -> str:
    return {True: "YES", False: "NO", None: "UNKNOWN"}[v]


def print_result(result: OrderabilityResult) -> None:
    print(f"Restaurant:\n{result.restaurant_name}\n")
    print(f"Date:\n{_format_date_long(result.target_date)}\n")
    print("Restopolis:")
    print(f"Menu available: {_yes_no(result.menu_available)}")
    print(f"Restaurant open: {_yes_no(result.restaurant_open)}")
    print(f"Ordering available: {_yes_no(result.ordering_available)}\n")

    if result.service_start and result.service_end:
        print("Service:")
        print(f"{result.service_start}–{result.service_end}\n")

    if result.our_delivery.deadline:
        print("Our delivery deadline:")
        print(f"{_format_date_long(result.our_delivery.deadline.date())} {result.our_delivery.deadline.strftime('%H:%M')}\n")
    print(f"Our delivery orderable: {_yes_no(result.our_delivery.available)}\n")

    print("Status:")
    print(result.status.upper())
    if result.reason:
        print(f"\nReason:\n{result.reason}")
    if result.from_cache:
        print("\n(from cache)")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--restaurant", required=True, choices=["altius", "brasserie-johns"])
    parser.add_argument("--date", type=parse_date, help="Date to check (YYYY-MM-DD)")
    parser.add_argument("--next-available", action="store_true", help="List the next available dates instead")
    parser.add_argument("--count", type=int, default=5, help="How many available dates to find with --next-available")
    parser.add_argument("--refresh", action="store_true", help="Bypass the cache and force a fresh Restopolis check")
    parser.add_argument("--cache-db", default="orderability.db")
    parser.add_argument("--cache-ttl", type=int, default=15 * 60, help="Cache TTL in seconds")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON instead of the formatted view")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stderr,  # keep stdout clean for --json (and the formatted view below it)
    )

    if not args.date and not args.next_available:
        parser.error("Provide --date or --next-available")

    all_restaurants = load_restaurants()
    by_slug = {slug_for(code): cfg for code, cfg in all_restaurants.items()}
    restaurant = by_slug[args.restaurant]

    cache = OrderabilityCache(args.cache_db, ttl_seconds=args.cache_ttl)
    service = OrderabilityService(cache=cache, restaurants=all_restaurants)

    try:
        if args.next_available:
            results = service.get_next_available_dates(restaurant, count=args.count)
            if args.json:
                import json

                print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
            else:
                print(f"Next available dates for {restaurant.name}:\n")
                if not results:
                    print("(none found within the browsable horizon)")
                for r in results:
                    print(f"- {_format_date_long(r.target_date)} ({r.target_date.isoformat()})")
            return 0

        result = service.check_orderability(restaurant, args.date, refresh=args.refresh)
        if args.json:
            import json

            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print_result(result)
        return 0 if result.status not in ("unknown",) else 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
