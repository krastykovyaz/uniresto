"""A dish's size lives in its name at Restopolis ("Rosport Blue 0,50 l non
consigné", "Mini salades 150 g", "Cornet Luxlait 130 ml (Chocolat, ...)").
The app shows the title without it and the size on its own line (see
static/i18n.js's dishTitle()/dishSize(), which this mirrors -- keep the two
regexes in step); the link previews built in dish_card.py do the same.
"""

from __future__ import annotations

import re

_UNIT = r"(?:kg|g|ml|cl|l)"
_NUM = r"\d+(?:[.,]\d+)?"
# (500 ml)  |  150 g / 0,25 l btl / 0,50 l non consigné / 0,25 l Tétra Pack (gratuit)  |  0,33 btl
_SIZE_RE = re.compile(
    rf"\s*(?:\(\s*({_NUM}\s*{_UNIT})\s*\)"
    rf"|({_NUM}\s*{_UNIT}\b(?:\s*(?:btl\b|non[ -]consigné|Tétra Pack))?(?:\s*\(gratuit\))?|{_NUM}\s*btl\b))",
    re.IGNORECASE,
)


def split_dish_size(raw_name: str) -> tuple[str, str | None]:
    """("Rosport Blue 0,50 l non consigné") -> ("Rosport Blue", "0,50 l non
    consigné"); a name with no size comes back untouched with None."""
    match = _SIZE_RE.search(raw_name)
    if not match:
        return raw_name, None
    size = (match.group(1) or match.group(2)).strip()
    title = _SIZE_RE.sub("", raw_name, count=1)
    title = re.sub(r"\s{2,}", " ", title)
    title = re.sub(r"\s+([,)])", r"\1", title).strip()
    return title or raw_name, size
