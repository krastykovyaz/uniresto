"""Dietary / origin flag mapping for Restopolis menus.

Each product can carry one or more small icons (``<img class="product-flag">``).
The mapping below was read directly off the menu page's own legend, e.g.:

    <img src=".../images/bio.png"> Produit biologique
    <img src=".../images/transfair.png"> Produit Fairtrade
    <img src=".../images/terroir.png"> Produit du Luxembourg
    <img src=".../images/greater_region.jpg"> Produit de la Grande Région
    <img src=".../images/benelux.jpg"> Produit du Benelux
    <img src=".../images/vegetarian.png"> Produit végétarien
    <img src=".../images/vegan.png"> Produit végan
    <img src=".../images/not_vegetarian.png"> Produit non-végétarien
    <img src=".../images/gluten_free.jpg"> Produit sans gluten
    <img src=".../images/sugar_free.jpg"> Produit sans sucre

This is a direct reading of the page's own legend, not a guess at icon
meaning. If Restopolis adds a new icon filename that isn't in this table,
`parse_flag` returns the filename itself as the code so the item is never
silently dropped (see parser.py logging of unknown flags).
"""

FLAG_LABELS = {
    "bio.png": ("organic", "Produit biologique"),
    "transfair.png": ("fairtrade", "Produit Fairtrade"),
    "terroir.png": ("luxembourg", "Produit du Luxembourg"),
    "greater_region.jpg": ("greater_region", "Produit de la Grande Région"),
    "benelux.jpg": ("benelux", "Produit du Benelux"),
    "vegetarian.png": ("vegetarian", "Produit végétarien"),
    "vegan.png": ("vegan", "Produit végan"),
    "not_vegetarian.png": ("non_vegetarian", "Produit non-végétarien"),
    "gluten_free.jpg": ("gluten_free", "Produit sans gluten"),
    "sugar_free.jpg": ("sugar_free", "Produit sans sucre"),
}


def parse_flag(image_src: str) -> str:
    """Map a `product-flag` image src to a short dietary/origin code."""
    filename = image_src.rsplit("/", 1)[-1]
    code, _label = FLAG_LABELS.get(filename, (filename, filename))
    return code
