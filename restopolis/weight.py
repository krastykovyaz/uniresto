"""Extracts portion weight/volume from a Restopolis product name.

Restopolis does not expose a dedicated weight/portion field anywhere in
the Menu page markup (verified: no `product-weight` class, no
`data-weight` attribute, nothing in `.product-description` beyond date
ranges like "(01 avril - 30 juin)"). Where a portion size exists at all,
it is embedded directly in the product NAME text, and only for
"Constant products" (the permanent sandwich/drink/snack list) -- e.g.
"Bretzel salé 80 g", "Coca Cola 0,20 l btl", "Yaourt aux fruits Luxlait
125 g". Checked against the live fixture: 0 of 62 daily "Menu" formula
items (Entrée/Végétarien/...) have any such pattern; 350 of 714 Constant
products items do.

This module only ever extracts a value that is literally present in the
name text -- it never estimates or defaults a weight for a dish that
doesn't state one. The name itself is never modified/stripped: the raw
name from restopolis/parser.py is preserved unchanged (see MenuItem.name)
so nothing is lost if this parser is ever wrong.
"""

from __future__ import annotations

import re

# Matches "150 g", "0,20 l", "1.5kg", "80g" etc. -- number (with optional
# comma/dot decimal, French style) + unit, at a word boundary so it
# doesn't match inside an unrelated word.
_WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|cl|ml|l)\b", re.IGNORECASE)

# "1 pièce", "2 pièces", "1 pc" -- not observed in the live data at all,
# but supported since Restopolis's own unit list (per the task) includes it.
_PIECE_RE = re.compile(r"(\d+)\s*(?:pi[eè]ces?|pcs?)\b", re.IGNORECASE)

# Units the frontend understands, per the task's spec. "cl" is converted
# to "ml" (a plain unit conversion of a value that IS present in the
# text, not an invented one) since "cl" isn't in that list.
_UNIT_NORMALIZE = {
    "g": "g",
    "kg": "kg",
    "ml": "ml",
    "l": "l",
    "cl": "ml",
}


def parse_weight(name: str) -> tuple[float | None, str | None]:
    """Returns (weight_value, weight_unit) parsed from a product name, or
    (None, None) if the name doesn't state one. Picks the right-most
    match when a name contains more than one number+unit (observed e.g.
    in "Cornet Luxlait 130 ml (Chocolat, Fraise, Vanille, ...)")."""
    piece_matches = list(_PIECE_RE.finditer(name))
    weight_matches = list(_WEIGHT_RE.finditer(name))

    # Prefer whichever pattern's last match is right-most in the string.
    last_piece = piece_matches[-1] if piece_matches else None
    last_weight = weight_matches[-1] if weight_matches else None

    if last_piece and (not last_weight or last_piece.start() > last_weight.start()):
        return float(last_piece.group(1)), "piece"

    if last_weight:
        raw_value, raw_unit = last_weight.groups()
        value = float(raw_value.replace(",", "."))
        unit = _UNIT_NORMALIZE[raw_unit.lower()]
        if raw_unit.lower() == "cl":
            value *= 10  # cl -> ml
        return value, unit

    return None, None


def format_weight(value: float | None, unit: str | None) -> str:
    """Human-readable weight string, e.g. "150 g", "0.2 l", "1 pc"."""
    if value is None or unit is None:
        return "Portion size not specified"
    display_value = int(value) if value == int(value) else value
    if unit == "piece":
        return f"{display_value} pc" if display_value != 1 else "1 pc"
    return f"{display_value} {unit}"
