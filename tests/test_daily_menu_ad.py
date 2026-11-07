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


def test_a_closed_restaurant_does_not_empty_the_advert(monkeypatch):
    # Brasserie John's had no menu for a whole week: the pastries sold at Altius must still fill the page.
    croissant = {"category": "02. Viennoiseries", "name": "Croissant 50 g"}
    soup = {"category": "Entrée", "name": "Velouté aux épinards"}

    def fake_get(path):
        if "/dish-photos" in path:
            return {"photos": {"02. Viennoiseries": {"Croissant 50 g": "c.jpg"}} if "/altius/" in path else {}}
        if "/altius/menu/" in path:
            return {"items": [croissant, soup]}
        raise OSError("409")  # the closed restaurant

    monkeypatch.setattr(menu_ad, "_get", fake_get)
    monkeypatch.setattr(menu_ad, "_photos", {})
    assert list(menu_ad.day_menus("2026-11-06")) == ["altius"]
    assert menu_ad.picks_for("2026-11-06", menu_ad.TEXT["en"]) == [("altius", "02. Viennoiseries", "Croissant 50 g", "Altius")]

    # Both open: only what both sell, labelled with both names.
    monkeypatch.setattr(menu_ad, "_get", lambda path: {"photos": {"02. Viennoiseries": {"Croissant 50 g": "c.jpg"}}} if "/dish-photos" in path else {"items": [croissant] if "/altius/" in path else [croissant, soup]})
    monkeypatch.setattr(menu_ad, "_photos", {})
    assert menu_ad.picks_for("2026-11-06", menu_ad.TEXT["en"]) == [("altius", "02. Viennoiseries", "Croissant 50 g", "Altius & Brasserie John's")]


def test_memory_watch_warns_only_when_swap_is_full_and_ram_is_low():
    mw = _load("memory_watch")
    info = lambda swap_free, avail: {"SwapTotal": 2048 * 1024, "SwapFree": swap_free * 1024, "MemAvailable": avail * 1024}  # noqa: E731
    assert mw.is_short(info(swap_free=40, avail=100))
    assert not mw.is_short(info(swap_free=40, avail=900))  # swap full but plenty of RAM: fine
    assert not mw.is_short(info(swap_free=1500, avail=100))  # RAM low but swap has room: fine
    assert not mw.is_short({"SwapTotal": 0, "SwapFree": 0, "MemAvailable": 10})  # no swap configured
    assert mw.meminfo("SwapTotal:  2048 kB\nSwapFree:  1024 kB\n") == {"SwapTotal": 2048, "SwapFree": 1024}
    text = mw.message(info(40, 100), [(300 * 1024, "/opt/x/python3 main.py")])
    assert "2008 of 2048 MB" in text and "300 MB  /opt/x/python3 main.py" in text
    assert mw.describe("/usr/bin/python run.py --token=abc SECRET=1") == "/usr/bin/python run.py"
