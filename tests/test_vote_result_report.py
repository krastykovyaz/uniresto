import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("vote_result_report", Path(__file__).resolve().parent.parent / "scripts" / "vote_result_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def _results(votes, winner=None, closed=True):
    names = ["A", "B", "C"]
    total = sum(votes)
    return {
        "options": [{"location": n, "votes": v, "percent": round(v * 100 / total) if total else 0} for n, v in zip(names, votes)],
        "total": total, "opens_on": "2026-11-01", "closed": closed, "winner": winner,
    }


def test_a_clear_winner_gets_a_ready_to_post_text():
    text = report.format_report(_results([10, 30, 5], winner="B"))
    assert "Winner: B" in text and "2026-11-01" in text and "Ready to post" in text
    assert text.index("B (30)") < text.index("A (10)")


def test_a_tie_says_so_and_names_no_winner():
    text = report.format_report(_results([20, 20, 5]))
    assert "TIE between A, B" in text and "Ready to post" not in text


def test_no_votes_at_all_is_said_plainly():
    assert "Nobody voted" in report.format_report(_results([0, 0, 0]))
