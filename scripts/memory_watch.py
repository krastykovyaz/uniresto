"""Every 10 minutes: warn the admin on Telegram when the server is short of memory (swap nearly full and little RAM
left to use), which is what makes pages slow and ends in 504s; say so again when it is over. It names the programs
holding the most swap, so the cause is visible. One message per episode, not one per check.

    /root/menu-ads-venv/bin/python scripts/memory_watch.py [--no-send]

Run by scripts/systemd/uniresto-memory-watch.timer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import daily_menu_ad  # noqa: E402  (its Telegram helpers)

STATE = Path("/var/tmp/uniresto-memory-watch.state")
SWAP_FULL_PERCENT = 95  # swap this full ...
AVAILABLE_LOW_MB = 200  # ... and less than this much RAM available: trouble
TOP = 5


def meminfo(text: str | None = None) -> dict[str, int]:
    """/proc/meminfo as {name: kB}."""
    text = Path("/proc/meminfo").read_text() if text is None else text
    out = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if rest.split():
            out[key] = int(rest.split()[0])
    return out


def is_short(info: dict[str, int]) -> bool:
    swap_total = info.get("SwapTotal", 0)
    swap_used_percent = 100 * (swap_total - info.get("SwapFree", 0)) / swap_total if swap_total else 0
    return swap_used_percent >= SWAP_FULL_PERCENT and info.get("MemAvailable", 0) < AVAILABLE_LOW_MB * 1024


def top_swap_users(limit: int = TOP) -> list[tuple[int, str]]:
    """(kB of swap, a short description) for the programs holding the most swap."""
    rows = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            swap = next((int(l.split()[1]) for l in (proc / "status").read_text().splitlines() if l.startswith("VmSwap:")), 0)
            cmd = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            continue
        if swap:
            rows.append((swap, cmd))
    return sorted(rows, reverse=True)[:limit]


def describe(cmd: str) -> str:
    """Enough of a command line to recognise the project, without arguments that may hold secrets."""
    words = cmd.split()
    return " ".join(w for w in words[:3] if "=" not in w)[:80] or "?"


def message(info: dict[str, int], users: list[tuple[int, str]]) -> str:
    swap_total = info["SwapTotal"] // 1024
    lines = [
        f"Server memory is short: swap {swap_total - info['SwapFree'] // 1024} of {swap_total} MB used, "
        f"{info['MemAvailable'] // 1024} MB of RAM available. Pages may be slow or time out.",
        "Most swap held by:",
    ]
    lines += [f"  {kb // 1024} MB  {describe(cmd)}" for kb, cmd in users]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-send", action="store_true", help="print instead of sending")
    args = ap.parse_args()
    info = meminfo()
    short = is_short(info)
    was_short = STATE.exists()
    if short and not was_short:
        text = message(info, top_swap_users())
        print(text)
        if not args.no_send:
            daily_menu_ad.send_text(text)
            STATE.write_text("short\n")
    elif not short and was_short:
        text = f"Server memory is back to normal: {info['MemAvailable'] // 1024} MB of RAM available."
        print(text)
        if not args.no_send:
            daily_menu_ad.send_text(text)
            STATE.unlink(missing_ok=True)
    else:
        print("short" if short else "ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
