import datetime

from orderability import _format_date_long, _yes_no


def test_format_date_long():
    assert _format_date_long(datetime.date(2026, 9, 24)) == "Jeudi 24 septembre 2026"


def test_format_date_long_handles_all_weekdays():
    week = [datetime.date(2026, 9, 21) + datetime.timedelta(days=i) for i in range(7)]
    formatted = [_format_date_long(d) for d in week]
    assert formatted[0].startswith("Lundi")
    assert formatted[6].startswith("Dimanche")


def test_yes_no_tri_state():
    assert _yes_no(True) == "YES"
    assert _yes_no(False) == "NO"
    assert _yes_no(None) == "UNKNOWN"
