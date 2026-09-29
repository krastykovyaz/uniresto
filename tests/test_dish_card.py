import io

import pytest
from PIL import Image

from orderability_engine.dish_card import HEIGHT, WIDTH, render_dish_card
from orderability_engine.dish_names import split_dish_size


def _render(**overrides):
    args = dict(title="Mini salads", size="150 g", category="04. Vitamines à emporter", price_text="€3.50", badge=None, footer="Altius · Tue 29 Sep · UniResto")
    args.update(overrides)
    return Image.open(io.BytesIO(render_dish_card(**args)))


def test_a_card_is_a_1200_by_630_jpeg():
    image = _render()
    assert image.format == "JPEG" and image.size == (WIDTH, HEIGHT) == (1200, 630)


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "Cornet Luxlait (Chocolat, Fraise, Vanille, Praliné, Mocca-vanille)", "size": "130 ml"},
        {"title": "x" * 300},
        {"title": "Pneumonoultramicroscopicsilicovolcanoconiosis" * 3},
        {"category": "10.1 Boissons froides - Eau minérale et pétillante", "badge": "VEGETARIAN"},
        {"price_text": "Included with a main dish", "size": None},
        {"footer": "Brasserie John's · Wednesday 30 September 2026 · UniResto · a very long footer indeed"},
        {"title": "Crème brûlée à l'orange — Straße €", "badge": "VEGAN"},
    ],
)
def test_awkward_content_still_renders(overrides):
    assert _render(**overrides).size == (1200, 630)


def test_a_missing_or_broken_photo_falls_back_to_the_placeholder(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    assert _render(photo_path=tmp_path / "missing.jpg").getpixel((200, 300)) == _render().getpixel((200, 300))
    assert _render(photo_path=broken).getpixel((200, 300)) == _render().getpixel((200, 300))


def test_a_card_with_a_busy_photo_stays_under_whatsapps_300_kb(tmp_path):
    import random

    random.seed(1)
    noisy = Image.effect_noise((1600, 1200), 90).convert("RGB")  # worst case for compression
    photo = tmp_path / "noisy.png"
    noisy.save(photo)
    assert len(render_dish_card(title="Noisy", size=None, category="x", price_text="€1.00", badge=None, footer="f", photo_path=photo)) < 300_000


def test_the_photo_fills_the_left_panel(tmp_path):
    photo = tmp_path / "red.png"
    Image.new("RGB", (80, 60), (200, 30, 30)).save(photo)
    r, g, b = _render(photo_path=photo).convert("RGB").getpixel((200, 300))
    assert r > 150 and g < 90 and b < 90


@pytest.mark.parametrize(
    "raw, title, size",
    [
        ("Mini salades 150 g", "Mini salades", "150 g"),
        ("Rosport Blue 0,50 l non consigné", "Rosport Blue", "0,50 l non consigné"),
        ("Lët'z kola 0,33 btl", "Lët'z kola", "0,33 btl"),
        ("Lait Luxlait BIO 0,25 l Tétra Pack (gratuit)", "Lait Luxlait BIO", "0,25 l Tétra Pack (gratuit)"),
        ("Consigne ECOBOX (500 ml)", "Consigne ECOBOX", "500 ml"),
        ("Cornet Luxlait 130 ml (Chocolat, Fraise)", "Cornet Luxlait (Chocolat, Fraise)", "130 ml"),
        ("Salad'bar", "Salad'bar", None),
        ("1/2 Levain jambon cuit", "1/2 Levain jambon cuit", None),
        ('Banane "commerce équitable"', 'Banane "commerce équitable"', None),
    ],
)
def test_split_dish_size_matches_the_apps_own_split(raw, title, size):
    # Same cases as tests_js/i18n.test.mjs's dishTitle/dishSize -- the two must agree.
    assert split_dish_size(raw) == (title, size)
