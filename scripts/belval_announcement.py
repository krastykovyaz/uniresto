"""The "Food House opens in Belval on 1 November 2026" announcement, as an A4 PDF: a poster with a QR code to UniResto's
main page, and a twin without the QR code (the web address instead) for places where QR codes are not allowed.

    /root/menu-ads-venv/bin/python scripts/belval_announcement.py [en|fr] [out_dir]

Writes <out_dir>/uniresto-belval-opening-<lang>-qr.pdf and ...-link.pdf. Needs the live app on 127.0.0.1:5050."""

from __future__ import annotations

import asyncio
import html
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import menu_ad  # noqa: E402

LINK = "https://resto.unilu.space/?src=adv-belval"
# Photos shown on the poster: everyday foods the new restaurant sells too (same products as the others).
PHOTOS = [
    ("altius", "Snack à emporter", 'Wrap "Great Cesar"'),
    ("altius", "02. Viennoiseries", "Croissant fourré 70 g"),
    ("altius", "04. Vitamines à emporter", "Mini salades 150 g"),
    ("altius", "02. Viennoiseries", "Poche aux pommes 80 g"),
]

TEXT = {
    "en": dict(
        brand="UniResto · Campus Belval", eyebrow="The restaurant you voted for", h1="Food House opens in Belval",
        date="From 1 November 2026", sub="Order your lunch from the new Campus Belval restaurant, right in the app.",
        where_h="Where", where="Food House · Maison du Savoir", hours_h="Service", hours="11:00–16:00", order_h="Order", order="Before 13:00 on the day",
        s1="Pick the day and your dishes", s2="Order before 13:00 — no account, just your university email",
        s3="A fellow student can bring it to your building: Maison du Savoir, Maison des Sciences Humaines or Maison de l'Innovation",
        photos="A daily hot menu, sandwiches, pastries, salads and more", first="First menu day: Monday 2 November.",
        scan="Scan to open UniResto", link="Open this address in your phone's browser",
        fine="UniResto is an independent student project. It is not an official service of the University of Luxembourg.",
    ),
    "fr": dict(
        brand="UniResto · Campus Belval", eyebrow="Le restaurant pour lequel vous avez voté", h1="Food House ouvre à Belval",
        date="À partir du 1er novembre 2026", sub="Commandez votre déjeuner au nouveau restaurant du Campus Belval, directement dans l'appli.",
        where_h="Où", where="Food House · Maison du Savoir", hours_h="Service", hours="11h00–16h00", order_h="Commande", order="Avant 13h00 le jour même",
        s1="Choisissez le jour et vos plats", s2="Commandez avant 13h00 — sans compte, seulement avec votre e-mail universitaire",
        s3="Un autre étudiant peut vous l'apporter dans votre bâtiment : Maison du Savoir, Maison des Sciences Humaines ou Maison de l'Innovation",
        photos="Un menu chaud du jour, sandwichs, viennoiseries, salades et plus encore", first="Premier jour de menu : lundi 2 novembre.",
        scan="Scannez pour ouvrir UniResto", link="Ouvrez cette adresse dans le navigateur de votre téléphone",
        fine="UniResto est un projet étudiant indépendant. Ce n'est pas un service officiel de l'Université du Luxembourg.",
    ),
}


def page_html(lang: str, with_qr: bool) -> str:
    t = TEXT[lang]
    photos = "".join(f'<img src="{menu_ad.photo_uri(*p)}">' for p in PHOTOS)
    if with_qr:
        action = f'<div class="qrbox"><img class="qr" src="{menu_ad.qr_uri_for(LINK, lang)}"><div class="scan">{html.escape(t["scan"])}</div></div>'
    else:
        action = f'<div class="qrbox"><div class="url-big">resto.unilu.space</div><div class="scan">{html.escape(t["link"])}</div></div>'
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 0 }} * {{ box-sizing: border-box; }}
body {{ margin:0; width:210mm; height:297mm; display:flex; flex-direction:column; color:#14171a; background:#f7f8fa;
  font-family:"Noto Sans","DejaVu Sans",-apple-system,"Helvetica Neue",Arial,sans-serif; }}
.top {{ background:#1aa860; color:#fff; padding:12mm 16mm 12mm; border-radius:0 0 10mm 10mm; }}
.brand {{ font-size:11pt; letter-spacing:.14em; text-transform:uppercase; opacity:.92; font-weight:700 }}
.eyebrow {{ margin-top:9mm; font-size:13pt; font-weight:600; opacity:.95 }}
h1 {{ margin:2mm 0 4mm; font-size:36pt; line-height:1.1 }}
.chip {{ display:inline-block; background:#fff; color:#128248; font-weight:800; font-size:15pt; padding:2.2mm 6mm; border-radius:999px }}
.sub {{ margin:5mm 0 0; font-size:12pt; line-height:1.4; opacity:.97 }}
.mid {{ padding:8mm 16mm 0; display:flex; flex-direction:column; gap:6mm }}
.info {{ display:flex; gap:5mm }}
.box {{ flex:1; background:#fff; border:1px solid #edeef1; border-radius:5mm; padding:4mm 5mm }}
.box .h {{ font-size:8.5pt; font-weight:800; letter-spacing:.08em; text-transform:uppercase; color:#128248 }}
.box .v {{ margin-top:1.4mm; font-size:11.5pt; font-weight:700; line-height:1.3 }}
.steps {{ background:#fff; border:1px solid #edeef1; border-radius:5mm; padding:5mm 6mm; display:flex; flex-direction:column; gap:3.2mm }}
.step {{ display:flex; gap:4mm; align-items:flex-start; font-size:11pt; line-height:1.35 }}
.n {{ flex:none; width:7mm; height:7mm; border-radius:50%; background:#1aa860; color:#fff; font-weight:800; display:flex; align-items:center; justify-content:center; font-size:10pt }}
.photos {{ display:flex; gap:4mm }}
.photos img {{ flex:1; min-width:0; height:40mm; object-fit:cover; border-radius:4mm }}
.cap {{ margin-top:-3mm; font-size:9pt; color:#6b7280; font-weight:600 }}
.bottom {{ margin:auto 16mm 12mm; background:#e6f7ee; border:1px solid #bfe8d1; border-radius:6mm; padding:6mm 7mm; display:flex; align-items:center; gap:8mm }}
.bottom .txt {{ flex:1 }} .first {{ font-size:12pt; font-weight:800; color:#128248 }} .fine {{ margin-top:2mm; font-size:7.8pt; color:#6b7280; line-height:1.35 }}
.qrbox {{ text-align:center; flex:none }} .qr {{ width:38mm; height:38mm; display:block; background:#fff; padding:2mm; border-radius:3mm }}
.scan {{ margin-top:1.8mm; font-size:8.6pt; font-weight:700; color:#128248; max-width:60mm }}
.url-big {{ width:62mm; padding:6mm 2mm; background:#fff; border-radius:3mm; font-size:15pt; font-weight:800; color:#128248; text-align:center }}
</style></head><body>
<div class="top"><div class="brand">{html.escape(t['brand'])}</div><div class="eyebrow">{html.escape(t['eyebrow'])}</div>
<h1>{html.escape(t['h1'])}</h1><div class="chip">{html.escape(t['date'])}</div><p class="sub">{html.escape(t['sub'])}</p></div>
<div class="mid">
<div class="info"><div class="box"><div class="h">{html.escape(t['where_h'])}</div><div class="v">{html.escape(t['where'])}</div></div>
<div class="box"><div class="h">{html.escape(t['hours_h'])}</div><div class="v">{html.escape(t['hours'])}</div></div>
<div class="box"><div class="h">{html.escape(t['order_h'])}</div><div class="v">{html.escape(t['order'])}</div></div></div>
<div class="steps"><div class="step"><span class="n">1</span><span>{html.escape(t['s1'])}</span></div>
<div class="step"><span class="n">2</span><span>{html.escape(t['s2'])}</span></div>
<div class="step"><span class="n">3</span><span>{html.escape(t['s3'])}</span></div></div>
<div class="photos">{photos}</div><div class="cap">{html.escape(t['photos'])}</div></div>
<div class="bottom"><div class="txt"><div class="first">{html.escape(t['first'])}</div><div class="fine">{html.escape(t['fine'])}</div></div>{action}</div>
</body></html>"""


async def build(lang: str, out_dir: Path) -> list[Path]:
    from playwright.async_api import async_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=menu_ad.CHROME, args=["--no-sandbox"])
        for suffix, with_qr in (("qr", True), ("link", False)):
            page = await browser.new_page()
            await page.set_content(page_html(lang, with_qr))
            await page.wait_for_timeout(400)
            path = out_dir / f"uniresto-belval-opening-{lang}-{suffix}.pdf"
            await page.pdf(path=str(path), format="A4", print_background=True, prefer_css_page_size=True)
            await page.close()
            made.append(path)
        await browser.close()
    return made


if __name__ == "__main__":
    language = sys.argv[1] if len(sys.argv) > 1 else "en"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/root/exports/adv")
    for made_path in asyncio.run(build(language, target)):
        print(made_path)
