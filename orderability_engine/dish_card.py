"""The picture behind a shared dish's link preview.

When someone shares a dish from the app, Telegram / WhatsApp / iMessage ...
build the preview from the link's Open Graph tags, and og:image has to be a
real image. This draws one that looks like the dish's own card in the app --
the photo on the left (or a soft placeholder when nobody has added one yet),
then category, title, size, diet badge and the price in green -- so the
preview is that exact dish, not the generic app banner.

Pure Pillow, no network. Returns JPEG bytes (small enough for WhatsApp). The font is bundled (assets/fonts, DejaVu, free
licence): Pillow's built-in one has no accented letters or "€".
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH, HEIGHT = 1200, 630  # the size og:image asks for, what crawlers expect
_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_BACKGROUND = (247, 248, 250)
_CARD = (255, 255, 255)
_BORDER = (226, 230, 235)
_INK = (20, 23, 26)
_MUTED = (107, 114, 128)
_GREEN = (30, 126, 52)
_GREEN_BG = (226, 244, 232)
_PLACEHOLDER = (233, 244, 252)
_PLACEHOLDER_INK = (120, 170, 215)

_PHOTO_W = 520
_MARGIN = 36
_PAD = 44


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def _wrap_words(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy word wrap, never dropping anything -- a word wider than the
    box just gets a line to itself (and overflows it)."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list[str]:
    """Greedy word wrap to `max_width` pixels, ending the last line with an
    ellipsis when the text doesn't fit in `max_lines`."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    # A single very long word can still overflow -- clip it rather than draw past the card.
    clipped = []
    for line in lines:
        while len(line) > 1 and draw.textlength(line, font=font) > max_width:
            line = line[:-2] + "…"
        clipped.append(line)
    return clipped


def _rounded_mask(size: tuple[int, int], radius: int, corners: tuple[bool, bool, bool, bool]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255, corners=corners)
    return mask


def _photo_panel(photo_path: Path | None, size: tuple[int, int]) -> Image.Image:
    if photo_path is not None:
        try:
            with Image.open(photo_path) as img:
                return ImageOps.fit(img.convert("RGB"), size, method=Image.LANCZOS, centering=(0.5, 0.5))
        except (OSError, ValueError):
            pass  # a missing/corrupt file just falls back to the placeholder
    panel = Image.new("RGB", size, _PLACEHOLDER)
    draw = ImageDraw.Draw(panel)
    cx, cy = size[0] // 2, size[1] // 2 - 30
    draw.ellipse((cx - 120, cy - 120, cx + 120, cy + 120), outline=_PLACEHOLDER_INK, width=10)
    draw.ellipse((cx - 68, cy - 68, cx + 68, cy + 68), outline=_PLACEHOLDER_INK, width=6)
    note = "Add dish pic here!"
    font = _font(True, 30)
    draw.text((cx - draw.textlength(note, font=font) / 2, cy + 160), note, font=font, fill=_PLACEHOLDER_INK)
    return panel


def render_dish_card(
    *,
    title: str,
    size: str | None,
    category: str,
    price_text: str,
    badge: str | None,
    footer: str,
    photo_path: Path | None = None,
) -> bytes:
    """A 1200x630 JPEG of one dish's card. `badge` is e.g. "VEGAN" or None;
    `footer` the small line under it (restaurant · date)."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), _BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    card_box = (_MARGIN, _MARGIN, WIDTH - _MARGIN, HEIGHT - _MARGIN)
    draw.rounded_rectangle(card_box, radius=36, fill=_CARD, outline=_BORDER, width=3)

    # photo (or placeholder), rounded on the card's left corners only
    panel_size = (_PHOTO_W, card_box[3] - card_box[1] - 6)
    panel = _photo_panel(photo_path, panel_size)
    mask = _rounded_mask(panel_size, 33, (True, False, False, True))
    canvas.paste(panel, (card_box[0] + 3, card_box[1] + 3), mask)

    x = card_box[0] + _PHOTO_W + _PAD
    text_width = card_box[2] - _PAD - x
    y = card_box[1] + 48

    label_font = _font(True, 24)
    label = category.upper()
    badge_font = _font(True, 22)
    badge_w = draw.textlength(badge, font=badge_font) + 32 if badge else 0
    room = text_width - (badge_w + 20 if badge else 0)
    while len(label) > 1 and draw.textlength(label, font=label_font) > room:
        label = label[:-2].rstrip() + "…"
    draw.text((x, y), label, font=label_font, fill=_MUTED)
    if badge:
        # the diet badge rides on the category row, so a long title can't push it into the price
        bx = x + draw.textlength(label, font=label_font) + 20
        draw.rounded_rectangle((bx, y - 8, bx + badge_w, y + 34), radius=21, fill=_GREEN_BG)
        draw.text((bx + 16, y - 1), badge, font=badge_font, fill=_GREEN)
    y += 54

    # Biggest title that fits in the space above the price: 60px in two
    # lines, else smaller in three -- and only if no single word is wider
    # than the box either ("mélangés/non-mélangés" gets a smaller font, not
    # an ellipsis, when that's enough). The last resort clips with "…".
    for font_size, max_lines in ((60, 2), (50, 3), (42, 3), (36, 3)):
        title_font = _font(True, font_size)
        raw = _wrap_words(draw, title, title_font, text_width)
        if len(raw) <= max_lines and all(draw.textlength(line, font=title_font) <= text_width for line in raw):
            break
    lines = _wrap(draw, title, title_font, text_width, max_lines=max_lines)
    line_height = int(font_size * 1.22)
    for line in lines:
        draw.text((x, y), line, font=title_font, fill=_INK)
        y += line_height
    y += 8

    if size:
        draw.text((x, y), size, font=_font(False, 34), fill=_MUTED)
        y += 52

    price_font = _font(True, 84 if len(price_text) <= 8 else 44)
    draw.text((x, card_box[3] - 200), price_text, font=price_font, fill=_GREEN)

    footer_size = 26
    footer_font = _font(False, footer_size)
    while footer_size > 19 and draw.textlength(footer, font=footer_font) > text_width:
        footer_size -= 1
        footer_font = _font(False, footer_size)
    while len(footer) > 1 and draw.textlength(footer, font=footer_font) > text_width:
        footer = footer[:-2].rstrip() + "…"
    draw.text((x, card_box[3] - 82), footer, font=footer_font, fill=_MUTED)

    # JPEG, not PNG: with a real photo on it a PNG runs to ~500 KB, and
    # WhatsApp drops link-preview images much over 300 KB. This is ~60-120 KB.
    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()
