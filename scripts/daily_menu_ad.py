"""Every weekday morning: build today's menu advert (scripts/menu_ad.py) in that day's language and send both PDFs
(QR version and web-address-only version) to the admin on Telegram.

    /root/menu-ads-venv/bin/python scripts/daily_menu_ad.py [--date 2026-10-26] [--no-send]

Run by scripts/systemd/uniresto-daily-ad.timer. The language changes every day: English until 23 Oct, then
French, Spanish, Portuguese, Russian, Arabic, Chinese, Hindi, Bengali, Urdu, Luxembourgish, English and round again.
Saturdays and Sundays are skipped; a weekday with no menu (a holiday) gets one short note instead."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

import menu_ad  # noqa: E402

TZ = ZoneInfo("Europe/Luxembourg")
ROTATION = ["fr", "es", "pt", "ru", "ar", "zh", "hi", "bn", "ur", "lb", "en"]
ROTATION_START = date(2026, 10, 24)  # the day after tomorrow, when this was set up; before it: English
OUT_DIR = Path("/root/exports/adv")
KEEP_DAYS = 14


def language_for(day: date) -> str:
    if day < ROTATION_START:
        return "en"
    return ROTATION[(day - ROTATION_START).days % len(ROTATION)]


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def multipart(fields: dict, file_field: str, path: Path) -> tuple[bytes, str]:
    """A multipart/form-data body with the text `fields` and one file -- no extra libraries needed."""
    boundary = uuid.uuid4().hex
    out = b""
    for key, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    out += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


def telegram(method: str, body: bytes, content_type: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not os.environ.get("TELEGRAM_CHAT_ID"):
        print("Telegram is not configured -- nothing sent")
        return False
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=body, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return bool(json.load(resp).get("ok"))
    except Exception as exc:  # noqa: BLE001 -- never print the URL: it holds the token
        print(f"Telegram request failed: {type(exc).__name__}")
        return False


def send_text(text: str) -> bool:
    body = json.dumps({"chat_id": os.environ.get("TELEGRAM_CHAT_ID"), "text": text}).encode()
    return telegram("sendMessage", body, "application/json")


def send_pdf(path: Path, caption: str) -> bool:
    body, ctype = multipart({"chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""), "caption": caption}, "document", path)
    return telegram("sendDocument", body, ctype)


def gaps_message(day: date, gaps: dict) -> str | None:
    """A note for the admin: which of the day's dishes still need a photo. None when every dish has one."""
    if not gaps:
        return None
    lines = [f"Dishes without a photo on {day.strftime('%A %-d %B')} (send a photo of any of them and it is attached for every day the dish returns):"]
    for restaurant, names in gaps.items():
        lines.append(f"\n{restaurant}")
        lines += [f"  • {name}" for name in names]
    return "\n".join(lines)


def prune(directory: Path) -> None:
    cutoff = datetime.now().timestamp() - KEEP_DAYS * 86400
    for old in directory.glob("uniresto-menu-*.pdf"):
        if old.stat().st_mtime < cutoff:
            old.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="build for this day instead of today (YYYY-MM-DD)")
    ap.add_argument("--no-send", action="store_true", help="build the PDFs but do not send them")
    args = ap.parse_args()
    day = date.fromisoformat(args.date) if args.date else datetime.now(TZ).date()

    if is_weekend(day):
        print(f"{day}: weekend -- no advert")
        return 0
    if not menu_ad.has_menu(day.isoformat()):
        print(f"{day}: no menu published")
        if not args.no_send:
            send_text(f"No menu advert for {day.strftime('%A %-d %B')}: no daily menu is published for that day.")
        return 0

    lang = language_for(day)
    made = asyncio.run(menu_ad.build(day.isoformat(), lang, OUT_DIR))
    prune(OUT_DIR)
    print(f"{day}: built {', '.join(p.name for p in made)}")
    note = gaps_message(day, menu_ad.photo_gaps(day.isoformat()))
    if note:
        print(note)
    if args.no_send:
        return 0
    label = f"{day.strftime('%A %-d %B')} · {menu_ad.LANG_NAMES[lang]}"
    ok = all(
        send_pdf(path, f"{label} · {'with QR codes' if path.name.endswith('-qr.pdf') else 'web address only (no QR)'}")
        for path in made
    )
    if note:
        send_text(note)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
