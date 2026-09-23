#!/usr/bin/env python3
"""CLI for the Restopolis menu collector (UDL Campus Kirchberg: Altius,
Brasserie John's). See README.md for the full mechanism writeup.

Examples:
    python scraper.py --date 2026-09-24
    python scraper.py --restaurant altius --date 2026-09-24
    python scraper.py --restaurant brasserie-johns --date 2026-09-24
    python scraper.py --from 2026-09-21 --to 2026-09-25
    python scraper.py --date 2026-09-24 --format json
    python scraper.py discover
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from restopolis.client import RestopolisClient, RestopolisError
from restopolis.config import load_restaurants
from restopolis.database import RestopolisDatabase
from restopolis.exporter import export_json_from_menus
from restopolis.models import RestaurantConfig
from restopolis.parser import MenuParseError, parse_week_html

logger = logging.getLogger("restopolis.scraper")


def slug_for(code: str) -> str:
    """UDL-CKB-ALTIUS -> altius, UDL-CKB-BRASSERIE-JOHNS -> brasserie-johns."""
    return code.split("-", 2)[-1].lower()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date {s!r}, expected YYYY-MM-DD") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("discover", help="Re-verify restaurant ids against the live Restopolis site")

    parser.add_argument("--date", type=parse_date, help="Single date to scrape (YYYY-MM-DD)")
    parser.add_argument("--from", dest="date_from", type=parse_date, help="Start of a date range (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", type=parse_date, help="End of a date range, inclusive (YYYY-MM-DD)")
    parser.add_argument(
        "--restaurant",
        action="append",
        choices=["altius", "brasserie-johns"],
        help="Restaurant slug to scrape (repeatable). Default: both.",
    )
    parser.add_argument(
        "--format",
        choices=["both", "json", "sqlite"],
        default="both",
        help="Which outputs to write. Default: both DB and JSON.",
    )
    parser.add_argument("--db", default="restopolis.db", help="SQLite database path")
    parser.add_argument("--json-out", default="data/menus.json", help="JSON export path")
    parser.add_argument("--raw-dir", default="data/raw", help="Directory to save raw HTML for debugging")
    parser.add_argument("--config", default="restaurants.yaml", help="Path to restaurants.yaml")
    parser.add_argument(
        "--no-constant-products",
        action="store_true",
        help="Skip the 'Constant products' (permanent sandwich/snack) list, keep only the daily Menu formula",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def resolve_target_dates(args: argparse.Namespace) -> list[date]:
    if args.date and (args.date_from or args.date_to):
        raise SystemExit("Use either --date or --from/--to, not both.")

    if args.date:
        return [args.date]

    if args.date_from or args.date_to:
        if not (args.date_from and args.date_to):
            raise SystemExit("--from and --to must be given together.")
        if args.date_to < args.date_from:
            raise SystemExit("--to must not be before --from.")
        days = (args.date_to - args.date_from).days
        return [args.date_from + timedelta(days=i) for i in range(days + 1)]

    return [date.today()]


def resolve_restaurants(args: argparse.Namespace, all_restaurants: dict[str, RestaurantConfig]) -> list[RestaurantConfig]:
    by_slug = {slug_for(code): cfg for code, cfg in all_restaurants.items()}
    if not args.restaurant:
        return list(by_slug.values())
    return [by_slug[slug] for slug in args.restaurant]


def cmd_discover(args: argparse.Namespace) -> int:
    from restopolis.discovery import fetch_restaurant_list_html, find_by_name, parse_restaurant_list

    restaurants = load_restaurants(args.config)
    logger.info("[INFO] Discovering restaurants")
    html = fetch_restaurant_list_html()
    discovered = parse_restaurant_list(html)
    logger.info("[INFO] Found %d restaurants listed on Restopolis", len(discovered))

    ok = True
    for cfg in restaurants.values():
        match = find_by_name(discovered, cfg.name)
        if match is None:
            print(f"[MISMATCH] {cfg.name!r} not found on the live site anymore!")
            ok = False
        elif match.restaurant_id != cfg.restaurant_id:
            print(
                f"[MISMATCH] {cfg.name}: restaurants.yaml has restaurant_id={cfg.restaurant_id}, "
                f"live site has {match.restaurant_id}"
            )
            ok = False
        else:
            print(f"[OK] {cfg.name}: restaurant_id={cfg.restaurant_id} (site={match.site_name})")
    return 0 if ok else 1


def run_scrape(args: argparse.Namespace) -> int:
    all_restaurants = load_restaurants(args.config)
    restaurants = resolve_restaurants(args, all_restaurants)
    target_dates = resolve_target_dates(args)
    today = date.today()

    client = RestopolisClient()
    db = RestopolisDatabase(args.db) if args.format in ("both", "sqlite") else None

    had_error = False
    total_items_by_restaurant: dict[str, int] = defaultdict(int)
    all_scraped_menus: list = []

    for restaurant in restaurants:
        logger.info("[INFO] === %s ===", restaurant.name)
        restaurant_db_id = db.upsert_restaurant(restaurant) if db else None

        dates_by_week: dict[date, list[date]] = defaultdict(list)
        for d in target_dates:
            dates_by_week[week_start(d)].append(d)

        for monday, dates_in_week in sorted(dates_by_week.items()):
            weeks_ahead = (monday - week_start(today)).days // 7

            if weeks_ahead < 0:
                for d in dates_in_week:
                    logger.error(
                        "[ERROR] Cannot fetch %s for %s: %s is before the current week "
                        "(%s). Restopolis only exposes the current week onward "
                        "(its 'previous week' navigation is clamped at today's week); "
                        "past menus are not retrievable from this site.",
                        restaurant.code, d, d, week_start(today),
                    )
                had_error = True
                continue

            logger.info(
                "[INFO] Selecting date range %s (week starting %s, %d week(s) ahead)",
                ", ".join(d.isoformat() for d in dates_in_week), monday, weeks_ahead,
            )
            try:
                html = client.fetch_week_html(restaurant, weeks_ahead)
            except RestopolisError as exc:
                logger.error("[ERROR] Failed to fetch %s week %s: %s", restaurant.code, monday, exc)
                had_error = True
                continue

            save_raw_html(args.raw_dir, dates_in_week, restaurant, html)

            logger.info("[INFO] Parsing menu")
            try:
                week_menus = parse_week_html(
                    html,
                    restaurant.code,
                    restaurant.name,
                    "https://ssl.education.lu/eRestauration/CustomerServices/Menu",
                    include_constant_products=not args.no_constant_products,
                )
            except MenuParseError as exc:
                logger.error("[ERROR] Failed to parse menu for %s week %s: %s", restaurant.code, monday, exc)
                had_error = True
                continue

            wanted = set(dates_in_week)
            relevant_menus = [m for m in week_menus if m.menu_date in wanted]

            for menu in relevant_menus:
                item_count = len(menu.items)
                if menu.is_no_products:
                    logger.info(
                        "[INFO] %s %s (%s): no products scheduled at this date",
                        restaurant.code, menu.menu_date, menu.service_name,
                    )
                else:
                    logger.info(
                        "[INFO] Found %d menu items (%s, %s)",
                        item_count, menu.menu_date, menu.service_name,
                    )

                if db:
                    db.upsert_daily_menu(restaurant_db_id, menu)
                    logger.info("[INFO] Saved %d items", item_count)

                all_scraped_menus.append(menu)
                total_items_by_restaurant[restaurant.code] += item_count

    if args.format in ("both", "json"):
        restaurant_names = {r.code: r.name for r in restaurants}
        export_json_from_menus(all_scraped_menus, restaurant_names, args.json_out)

    if db:
        db.close()

    print("\n=== Summary ===")
    for restaurant in restaurants:
        print(f"{restaurant.name}: {total_items_by_restaurant.get(restaurant.code, 0)} items scraped")

    return 1 if had_error else 0


def save_raw_html(raw_dir: str, dates_in_week: list[date], restaurant: RestaurantConfig, html: str) -> None:
    slug = slug_for(restaurant.code)
    for d in dates_in_week:
        day_dir = Path(raw_dir) / d.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / f"{slug}.html").write_text(html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    if args.command == "discover":
        return cmd_discover(args)

    return run_scrape(args)


if __name__ == "__main__":
    raise SystemExit(main())
