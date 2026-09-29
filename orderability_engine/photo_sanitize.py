"""The one way a dish photo gets onto disk: decoded and re-encoded as a fresh
JPEG, which keeps only the pixels.

Phone photos carry EXIF -- GPS coordinates of wherever the shot was taken
(often someone's room), device model, timestamps -- and every approved photo
is published at a public URL. So nothing a client sent is ever written as-is.
Used by the upload and admin-replace routes in app.py, and by
scripts/attach_dish_photo.py when the admin attaches a photo directly."""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_DISH_PHOTO_PIXELS = 40_000_000  # decompression-bomb guard
MAX_DISH_PHOTO_SIDE = 1600


def sanitize_dish_photo(data: bytes) -> bytes | None:
    """JPEG bytes (EXIF gone, orientation baked in, at most 1600px on the
    long side), or None when `data` isn't a JPEG/PNG/GIF/WEBP image Pillow
    can decode within the pixel limit."""
    try:
        with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "GIF", "WEBP"]) as img:
            width, height = img.size
            if width * height > MAX_DISH_PHOTO_PIXELS:
                return None
            img.draft("RGB", (MAX_DISH_PHOTO_SIDE, MAX_DISH_PHOTO_SIDE))
            # Bake EXIF orientation into the pixels before dropping the tag,
            # or portrait phone shots would show up sideways.
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            img.thumbnail((MAX_DISH_PHOTO_SIDE, MAX_DISH_PHOTO_SIDE))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return None
