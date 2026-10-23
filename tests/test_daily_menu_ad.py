import importlib.util
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


daily = _load("daily_menu_ad")
menu_ad = _load("menu_ad")


def test_english_until_the_rotation_starts_then_a_new_language_every_day():
    assert daily.language_for(date(2026, 10, 22)) == "en"
    assert daily.language_for(date(2026, 10, 23)) == "en"
    assert daily.language_for(date(2026, 10, 24)) == "fr"
    assert daily.language_for(date(2026, 10, 25)) == "es"
    assert [daily.language_for(date(2026, 10, 24) + timedelta(days=i)) for i in range(11)] == daily.ROTATION  # a full cycle
    assert daily.language_for(date(2026, 11, 4)) == "fr"  # then round again


def test_two_days_in_a_row_never_share_a_language():
    langs = [daily.language_for(date(2026, 10, 24) + timedelta(days=i)) for i in range(60)]
    assert all(a != b for a, b in zip(langs, langs[1:]))


def test_weekends_are_skipped():
    assert daily.is_weekend(date(2026, 10, 24)) and daily.is_weekend(date(2026, 10, 25))
    assert not daily.is_weekend(date(2026, 10, 26))


def test_every_rotation_language_has_the_whole_advert_text_and_a_name():
    keys = {"title", "ad", "body", "fine", "scan", "link", "hot"}
    for lang in daily.ROTATION:
        assert set(menu_ad.TEXT[lang]) == keys, lang
        assert lang in menu_ad.LANG_NAMES
    assert menu_ad.RTL == {"ar", "ur"}


def test_the_multipart_body_carries_the_fields_and_the_file(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    body, ctype = daily.multipart({"chat_id": "1", "caption": "hi"}, "document", pdf)
    boundary = ctype.split("boundary=")[1]
    assert body.count(f"--{boundary}".encode()) == 4  # two fields, the file, and the closing line
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="chat_id"' in body and b'filename="a.pdf"' in body and b"%PDF-1.4 test" in body


def test_the_photo_note_lists_the_dishes_still_without_a_photo():
    note = daily.gaps_message(date(2026, 10, 26), {"Altius": ["Soupe aux poireaux"], "Brasserie John's": ["Curry de poulet", "Soupe aux poireaux"]})
    assert "Monday 26 October" in note and "Altius" in note and "• Curry de poulet" in note
    assert daily.gaps_message(date(2026, 10, 26), {}) is None  # nothing to say when every dish has a photo
