"""Allergen code mapping for Restopolis menus.

Restopolis marks each product with a comma-separated list of allergen
codes, e.g. ``1 (Blé, Orge, Épeautre), 3, 7, 10``. The codes 1-14 are not
Restopolis-specific: they are the 14 major allergens defined by EU
regulation 1169/2011 Annex II, which is also the list Restopolis links to
from the "allergens and intolerances" footnote on the menu page
(http://edulink.lu/kpq0). The optional parenthesised text after a code is
Restopolis's own free-text detail for that dish (e.g. which cereal exactly
contains the gluten), not part of the regulation.

This mapping is therefore documented from the EU regulation, not guessed.
"""

import re

# EU 1169/2011 Annex II, in the French wording Restopolis itself uses
# (the site is scraped in French, see client.py).
ALLERGEN_NAMES = {
    1: "Céréales contenant du gluten",
    2: "Crustacés",
    3: "Œufs",
    4: "Poissons",
    5: "Arachides",
    6: "Soja",
    7: "Lait",
    8: "Fruits à coque",
    9: "Céleri",
    10: "Moutarde",
    11: "Graines de sésame",
    12: "Anhydride sulfureux et sulfites",
    13: "Lupin",
    14: "Mollusques",
}

# Matches an allergen code optionally followed by a parenthesised detail,
# e.g. "1 (Blé, Orge, Épeautre)" or "12". A plain split on "," would break
# because the parenthesised detail itself may contain commas.
_ALLERGEN_RE = re.compile(r"(\d+)\s*(?:\(([^)]*)\))?")


def parse_allergens(raw_text: str | None) -> list[dict]:
    """Parse a Restopolis `.product-allergens` text into structured entries.

    Returns a list of {"code": int, "name": str | None, "detail": str | None}.
    Unknown codes keep name=None rather than being dropped, so no data is
    silently discarded.
    """
    if not raw_text:
        return []

    entries = []
    for code_str, detail in _ALLERGEN_RE.findall(raw_text):
        if not code_str:
            continue
        code = int(code_str)
        entries.append(
            {
                "code": code,
                "name": ALLERGEN_NAMES.get(code),
                "detail": detail.strip() or None if detail else None,
            }
        )
    return entries
