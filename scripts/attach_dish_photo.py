#!/usr/bin/env python3
"""Attach a photo to a dish directly, as the admin -- no student submission,
no review queue, no Luni for anyone (unlike /admin/dish-photos/<id>/replace,
which needs a pending submission to exist first).

    cd /root/uniresto && .venv/bin/python scripts/attach_dish_photo.py \\
        photo.webp altius "Végan" "Potiron farci aux lentilles et coulis de tomates"

The image goes through the same sanitizing as every upload (re-encoded as a
JPEG: no EXIF, at most 1600px), is saved under a fresh admin-<id>.jpg name and
becomes the dish's live photo for that restaurant -- and, because a photo is
shown on every restaurant that serves the same dish (DishPhotoStore.
photos_visible_to), on the others too. A photo the dish had before is
replaced and its file deleted, like any replacement."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orderability_engine.dish_photos import DishPhotoStore  # noqa: E402
from orderability_engine.photo_sanitize import sanitize_dish_photo  # noqa: E402


def attach_dish_photo(image_bytes: bytes, slug: str, category: str, name: str, db_path: Path, photo_dir: Path) -> str:
    """Returns the new photo_path (as served: /static/dish_photos/<file>).
    Raises ValueError for anything that isn't a decodable image."""
    clean = sanitize_dish_photo(image_bytes)
    if clean is None:
        raise ValueError("not a JPEG/PNG/GIF/WEBP image Pillow can read")
    photo_dir.mkdir(parents=True, exist_ok=True)
    filename = f"admin-{uuid.uuid4().hex}.jpg"
    (photo_dir / filename).write_bytes(clean)
    photo_path = f"/static/dish_photos/{filename}"
    previous = DishPhotoStore(db_path).set_photo(slug, category, name, photo_path)
    if previous and previous != photo_path:
        (photo_dir / Path(previous).name).unlink(missing_ok=True)
    return photo_path


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    image, slug, category, name = argv[1:]
    try:
        photo_path = attach_dish_photo(Path(image).read_bytes(), slug, category, name, ROOT / "orders.db", ROOT / "static" / "dish_photos")
    except (OSError, ValueError) as exc:
        print("FAILED:", exc)
        return 1
    print(f"attached: {photo_path}  ->  {slug} | {category} | {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
