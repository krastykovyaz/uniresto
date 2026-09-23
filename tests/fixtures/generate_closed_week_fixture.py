"""Generates tests/fixtures/altius_closed_week.html: a SYNTHETIC week where
every day has no menu AND reservation is closed (the one signal
combination -- menu_available=False, ordering_available=False -- that
wasn't observed in the live capture used for the other fixtures, since
Restopolis's real reservation window happened to keep ordering "open" on
every no-menu day it showed us). Built from the same real selectors/markup
skeleton as the live fixtures (course-name, product-name, formulaeContainer,
action-buttons, date-selector, menu-slider, etc.) -- only the specific
per-day *content* is fabricated, not the structure. Run this script to
regenerate the fixture if the real markup skeleton ever changes.
"""

from pathlib import Path

DAYS = [
    ("28.09.2026", "lun., 28.09."),
    ("29.09.2026", "mar., 29.09."),
    ("30.09.2026", "mer., 30.09."),
    ("01.10.2026", "jeu., 01.10."),
    ("02.10.2026", "ven., 02.10."),
    ("03.10.2026", "sam., 03.10."),
    ("04.10.2026", "dim., 04.10."),
]

DAY_BLOCK = """
<div>
    <div class="action-buttons">
        <div>
            <button disabled="disabled" style="font-size:35px;">Réservation clôturée</button>
        </div>
        <div>
            <button onclick="window.open('/eRestauration/CustomerServices/Menu/BtnPrintDay')">
                <i class="fas fa-print"></i> Imprimer
            </button>
        </div>
    </div>
    <div class="formulaeContainer no-products" style="padding: 64px; text-align: center;">
        <img src="/eRestauration/CustomerServices/images/no_products.png" alt="No products" />
        <div>Aucun plat programmé à cette date.</div>
    </div>
    <div class="constantProductContainer no-products" style="display:none">
        <div>Aucun plat programmé à cette date.</div>
    </div>
</div>
"""

date_links = "".join(
    f'<a class="day" data-date="{date}" href="#" onclick="moveToDateWithIndex({i}, true)">{label}</a>'
    for i, (date, label) in enumerate(DAYS)
)
slides = "".join(DAY_BLOCK for _ in DAYS)

html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><title>Menu</title></head>
<body>
<div class="restaurant-selector">
    <div class="restaurant-selector-value">
        <div class="restaurant-selector-value-inner">
            <span class="">UDL-CKB - Altius - Restaurant</span>
        </div>
    </div>
</div>
<div id="date-selector">
    <a href="/eRestauration/CustomerServices/Menu/PreviousWeek"><i class="fas fa-chevron-left"></i></a>
    {date_links}
    <a href="/eRestauration/CustomerServices/Menu/NextWeek"><i class="fas fa-chevron-right"></i></a>
</div>
<div class="wrapper">
    <a href="#" data-role="formula-products" data-service-id="1183" class="active">Service 11:00 - 14:30</a>
    <a href="#" data-role="constant-products">Produits constants</a>
</div>
<div class="menu-slider daily-menu">
    {slides}
</div>
</body>
</html>
"""

out = Path(__file__).parent / "altius_closed_week.html"
out.write_text(html, encoding="utf-8")
print(f"Wrote {out} ({len(html)} bytes)")
