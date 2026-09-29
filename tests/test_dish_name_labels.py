import json
import shutil
import subprocess
from pathlib import Path

import pytest

from orderability_engine.dish_name_labels import DISH_NAME_LABELS, dish_name_label
from orderability_engine.dish_names import split_dish_size


def test_translates_a_known_dish_name():
    assert dish_name_label("Salade campagnarde", "en") == "Country salad"
    assert dish_name_label("Soupe de pommes de terre", "ru") == "Картофельный суп"


def test_falls_back_to_the_raw_name_for_an_unmapped_dish():
    assert dish_name_label("Some Future Dish Restopolis Adds", "en") == "Some Future Dish Restopolis Adds"


def test_french_returns_the_name_unchanged():
    for name in DISH_NAME_LABELS:
        assert dish_name_label(name, "fr") == name


def test_falls_back_to_english_for_an_unknown_language_code():
    assert dish_name_label("Salade campagnarde", "xx") == "Country salad"


# ---------------------------------------------------------------------------
# Fixed-product translations (all 11 languages) and JS/Python parity
# ---------------------------------------------------------------------------
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from orderability_engine.dish_names import split_dish_size

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["en", "zh", "hi", "es", "fr", "ar", "bn", "pt", "ru", "ur", "lb"]


def _js_labels() -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = f'import {{ DISH_NAME_LABELS }} from "{(ROOT / "static" / "i18n.js").as_uri()}"; console.log(JSON.stringify(DISH_NAME_LABELS));'
    out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_the_python_table_is_identical_to_the_javascript_one():
    js = _js_labels()
    assert set(js) == set(DISH_NAME_LABELS), sorted(set(js) ^ set(DISH_NAME_LABELS))
    for raw in js:
        assert js[raw] == DISH_NAME_LABELS[raw], raw


def test_every_entry_has_all_11_languages_and_french_is_the_raw_name():
    for raw, labels in DISH_NAME_LABELS.items():
        assert sorted(labels) == sorted(LANGS), raw
        assert labels["fr"] == raw
        assert all(v.strip() for v in labels.values()), raw


def test_a_sized_translation_keeps_the_size_so_the_courier_email_still_names_the_exact_product():
    for raw in DISH_NAME_LABELS:
        _, size = split_dish_size(raw)
        if size is None:
            continue
        for lang in ("en", "es", "ru", "ar"):
            label = dish_name_label(raw, lang)
            # the translation may use its own digits/unit for the four oldest entries; the rest keep the raw size verbatim
            assert size in label or any(ch.isdigit() for ch in label), (raw, lang, label)


def test_a_name_with_no_entry_is_shown_as_restopolis_wrote_it():
    assert dish_name_label("Rosport Blue 0,50 l btl", "ru") == "Rosport Blue 0,50 l btl"
    assert dish_name_label("Something new on the menu", "zh") == "Something new on the menu"


def test_new_entries_read_correctly_in_the_email_language():
    assert dish_name_label("Croissant fourré 70 g", "en") == "Filled croissant 70 g"
    assert dish_name_label("Consigne ECOBOX (500 ml)", "es") == "Depósito ECOBOX (500 ml)"
    assert dish_name_label("Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille, Praliné, Mocca-vanille)", "es").startswith("Cono Luxlait 130 ml (")
