"""Approximate nutrition for the dishes that have a photo.

A cooked dish has no label, so these are ESTIMATES made once, by hand, for each photographed dish: what the dish is
(from its name and what its photo shows), a typical canteen portion of it, and generic reference values for those
ingredients. They were not measured, they are not Restopolis data, and they are no medical or dietary advice -- so
they are always shown as a range (+/- SPREAD) and labelled approximate.

Only the dish as NAMED is estimated: a photo often shows a whole plate with sides (chips, rice, peas) that are
separate items on the menu, and those are not counted here. Keyed by the exact dish name, so a renamed dish simply
has no entry (it falls back to the generic typical-portion range) instead of getting another dish's numbers.
"""

from __future__ import annotations

from orderability_engine.nutrition import _normalize

SPREAD = 0.20

# name: (portion in g, kcal, fat g, carbs g, protein g) -- central values for one portion as served
_DISHES: dict[str, tuple[int, int, int, int, int]] = {
    # sandwiches
    "1/2 Levain Green Sandwich": (190, 380, 14, 45, 16),
    "Petit pain blanc fromage": (150, 400, 17, 42, 18),
    "1/2 Levain Humi (houmous aux légumes locaux grillés)": (190, 360, 12, 50, 11),
    'Petit pain blanc "Schockelasbotter végan"': (100, 340, 12, 50, 6),
    '1/2 Levain "Great César"': (200, 430, 17, 45, 22),
    '1/2 Levain "Pastrami"': (200, 420, 14, 44, 27),
    "Petit pain blanc jambon cuit": (160, 380, 11, 42, 22),
    "Petit pain blanc salami": (150, 430, 20, 42, 17),
    "Mini baguette sans gluten jambon cuit": (140, 360, 12, 38, 18),
    # viennoiseries and house cakes
    "Croissant 50 g": (50, 230, 12, 26, 5),
    "Croissant fourré 70 g": (70, 310, 17, 32, 6),
    "Huit 80 g": (80, 300, 15, 35, 5),
    "Pain au chocolat 70 g": (70, 290, 16, 31, 5),
    "Poche aux pommes 80 g": (80, 250, 12, 33, 3),
    "Crispy Apple": (100, 380, 18, 48, 5),
    "Nutchy": (80, 400, 24, 38, 7),
    "Tasty Crunchy": (80, 350, 15, 46, 6),
    # small salad, soup, desserts
    "Mini salades 150 g": (150, 110, 7, 6, 5),
    "Soupe à l'oignon": (300, 180, 7, 20, 6),
    "Cheesecake": (120, 380, 25, 32, 7),
    "Cheesecake au Spéculoos": (120, 400, 25, 36, 7),
    "Crumble aux abricots": (150, 330, 12, 52, 4),
    "Mousse légère au fromage blanc et citron, financier aux amandes": (150, 290, 14, 32, 8),
    "Tarte aux poires, chantilly": (130, 340, 16, 43, 5),
    "Yaourt grec fouetté, compotée d'oranges": (130, 180, 8, 20, 6),
    # meat and fish
    "Boulettes de viande, sauce tomate": (200, 330, 21, 12, 22),
    "Chicken Burger": (230, 520, 22, 50, 28),
    "Chipolatas rôties, jus réduit": (150, 430, 35, 3, 20),
    "Faux-filet de boeuf grillé sauce Béarnaise": (180, 450, 30, 1, 40),
    "Filet de colin, sauce au beurre blanc citronnée": (190, 280, 17, 3, 28),
    "Fish and chips, quartier de citron, sauce rémoulade maison": (350, 750, 40, 70, 28),
    "Mixed grill de poulet, sauce Raïta": (200, 280, 12, 4, 36),
    "Omelette au fromage, jambon cuit et herbes fraîches": (210, 360, 27, 2, 27),
    # take-away salads and wraps
    "Buddha bowl végétarien": (350, 480, 22, 55, 15),
    "Salade aux mezzés variés": (300, 430, 20, 48, 13),
    "Salade de couscous et falafels, sauce tahini citronnée": (380, 650, 30, 72, 22),
    "Salade de pommes de terre et saucisse viennoise": (350, 560, 32, 40, 24),
    "Salade de quinoa aux lamelles de saumon": (330, 520, 28, 30, 30),
    "Salade kebab de poulet, sauce Tzatziki": (350, 520, 24, 38, 38),
    'Wrap "Great Cesar"': (250, 560, 24, 52, 28),
    "Wrap aux mini boulettes": (260, 580, 24, 60, 24),
    "Wrap façon Wiener schnitzel": (260, 640, 30, 58, 30),
    # vegetarian and vegan mains
    "Boulettes de lentilles tomatées, dip au yaourt végan citronné": (180, 280, 11, 32, 13),
    "Boulettes de lentilles tomatées, dip au yaourt citronné": (180, 290, 12, 32, 14),
    "Chakalaka au tofu": (300, 330, 14, 32, 18),
    "Potiron farci aux lentilles et coulis de tomates": (350, 360, 10, 52, 15),
    "Samossas aux lentilles et carottes, chutney de tomates": (180, 430, 20, 50, 12),
    "Strudel au potiron et blettes, tartinade de betteraves": (200, 420, 22, 45, 10),
    "Strudel au potiron et blettes, dip yaourt grec au persil": (200, 430, 23, 45, 11),
    "Tajine de pois chiches et butternut": (320, 340, 8, 52, 14),
    "Wok au tempeh, carottes et brocolis": (300, 380, 17, 28, 25),
    "Riz sauté à l'omelette, brocolis, oignons fanes et carottes": (350, 520, 17, 70, 17),
}
_BY_NAME = {_normalize(name): vals for name, vals in _DISHES.items()}


def dish_estimate(name: str) -> dict | None:
    """The approximate per-portion nutrition of a photographed dish, in the same shape as a fixed product's
    "nutrition" (basis "dish"; `serving` holds the CENTRAL values, `spread` the +/- fraction), or None."""
    found = _BY_NAME.get(_normalize(name))
    if found is None:
        return None
    grams, kcal, fat, carbs, protein = found
    return {
        "per100": None,
        "unit": "g",
        "serving": {"kcal": kcal, "fat": fat, "saturates": None, "carbs": carbs, "sugars": None,
                    "protein": protein, "salt": None},
        "serving_amount": grams,
        "basis": "dish",
        "spread": SPREAD,
        "source": "approximate estimate from the dish name, its photo and a typical recipe",
    }
