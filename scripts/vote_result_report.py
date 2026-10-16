"""One-off: once the "which restaurant opens first" vote is over, tell the admin the final result on
Telegram, with a short text ready to post.

    python scripts/vote_result_report.py [--dry-run]

Run by scripts/systemd/uniresto-vote-report.timer the morning after voting ends. Reads the app's own
public results (counts only -- the vote holds no addresses or devices, so there is nobody to message
individually) and sends nothing while voting is still open."""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orderability_engine.telegram_notify import send_admin_text  # noqa: E402

RESULTS_URL = os.environ.get("VOTE_RESULTS_URL", "http://127.0.0.1:5050/api/coming-soon/results")


def format_report(results: dict) -> str:
    options = sorted(results["options"], key=lambda o: (-o["votes"], o["location"]))
    lines = [f"Vote closed -- {results['total']} votes:"]
    lines += [f"  {o['percent']}%  {o['location']} ({o['votes']})" for o in options]
    winner = results.get("winner")
    if results["total"] == 0:
        lines.append("\nNobody voted. Nothing to announce -- decide yourself or extend the vote.")
    elif winner:
        lines += [
            f"\nWinner: {winner}, opening {results['opens_on']}.",
            "\nReady to post:",
            f"You voted, {winner} won ({next(o['percent'] for o in options if o['location'] == winner)}%)! "
            f"It opens on UniResto on {results['opens_on']}. Thanks to everyone who voted -- https://resto.unilu.space",
        ]
    else:
        tied = [o["location"] for o in options if o["votes"] == options[0]["votes"]]
        lines.append(f"\nTIE between {', '.join(tied)}. The app announces no winner -- you decide, then post.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the message instead of sending it")
    args = ap.parse_args()
    with urllib.request.urlopen(RESULTS_URL, timeout=15) as resp:
        results = json.load(resp)
    if not results["closed"]:
        print("voting is still open -- nothing sent")
        return 1
    text = format_report(results)
    if args.dry_run:
        print(text)
        return 0
    ok, error = send_admin_text(text)
    print("sent" if ok else f"not sent: {error}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
