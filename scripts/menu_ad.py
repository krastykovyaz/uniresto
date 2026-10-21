"""One-page A4 advert of a day's menu, as a PDF: a grid of dishes that have photos, plus a box with one QR code per
restaurant. Each QR opens that restaurant's menu for the current day (the next day it can still be ordered) in the
advert's own language, so the same image works whichever day it is scanned.

    /root/menu-ads-venv/bin/python scripts/menu_ad.py 2026-10-24 fr [out_dir]

Writes <out_dir>/uniresto-menu-<date>-<lang>-qr.pdf and ...-link.pdf (the web address instead of QR codes, for places
where QR codes are not allowed). Needs the live app on 127.0.0.1:5050, Pillow, segno and Playwright (the venv above).
scripts/daily_menu_ad.py runs this every morning and sends the result to the admin on Telegram."""

from __future__ import annotations

import asyncio
import base64
import html
import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orderability_engine.dish_name_labels import dish_name_label  # noqa: E402

APP = "http://127.0.0.1:5050"
# The photos are the live app's data (not in git), so always read them from the live checkout.
PHOTO_DIR = Path("/root/uniresto/static/dish_photos")
CHROME = "/root/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell"
RESTAURANTS = [("altius", "Altius", "adv-altius"), ("brasserie-johns", "Brasserie John's", "adv-brasserie")]
BOTH = "Altius & Brasserie John's"
DAILY = ("Entrée", "Végétarien", "Végan", "Pasta", "Non-végétarien", "Féculents", "Légumes", "Dessert")
RTL = {"ar", "ur"}
LANG_NAMES = {
    "en": "English", "fr": "Français", "es": "Español", "pt": "Português", "ru": "Русский", "zh": "中文",
    "hi": "हिन्दी", "ar": "العربية", "bn": "বাংলা", "ur": "اردو", "lb": "Lëtzebuergesch",
}
# Always-available foods, used after the day's own photographed dishes to fill the page.
ALWAYS = [
    ("Snack à emporter", 'Wrap "Great Cesar"'),
    ("01.3 Sandwiches non-végétariens", '1/2 Levain "Great César"'),
    ("01.3 Sandwiches non-végétariens", '1/2 Levain "Pastrami"'),
    ("01.2 Sandwiches végans", "1/2 Levain Humi (houmous aux légumes locaux grillés)"),
    ("01.3 Sandwiches non-végétariens", "Petit pain blanc jambon cuit"),
    ("02. Viennoiseries", "Croissant 50 g"),
    ("02. Viennoiseries", "Croissant fourré 70 g"),
    ("02. Viennoiseries", "Poche aux pommes 80 g"),
    ("02. Viennoiseries", "Huit 80 g"),
    ("04. Vitamines à emporter", "Mini salades 150 g"),
    ("05. Laitages", 'Mini muesli maison "Douceur d\'automne" 150 g'),
    ("03. Gâteaux et cookies maison", "Crispy Apple"),
    ("03. Gâteaux et cookies maison", "Nutchy"),
]
SHORTER_EN = {"1/2 Levain Humi (houmous aux légumes locaux grillés)": "1/2 sourdough Humi: hummus & grilled veg"}

# The advert's own words. Drafted for this project -- worth a native speaker's look.
TEXT = {
    "en": dict(title="Today's menu", ad="Skip the queue — order ahead",
               body="Choose your dish on your phone, no account needed, just your university email. Order before 13:00 and a fellow student can bring it to your building.",
               fine="UniResto is an independent student project. It is not an official service of the University of Luxembourg.",
               scan="Scan to see today's menu and order", link="Type this address in your phone's browser", hot="Hot dish"),
    "fr": dict(title="Menu du jour", ad="Évitez la file — commandez à l'avance",
               body="Choisissez votre plat sur votre téléphone, sans compte, seulement avec votre e-mail universitaire. Commandez avant 13h00 et un autre étudiant peut vous l'apporter dans votre bâtiment.",
               fine="UniResto est un projet étudiant indépendant. Ce n'est pas un service officiel de l'Université du Luxembourg.",
               scan="Scannez pour voir le menu du jour et commander", link="Saisissez cette adresse dans le navigateur de votre téléphone", hot="Plat du jour"),
    "es": dict(title="Menú de hoy", ad="Sáltate la cola: pide con antelación",
               body="Elige tu plato desde el móvil, sin cuenta, solo con tu correo universitario. Pide antes de las 13:00 y un compañero puede llevártelo a tu edificio.",
               fine="UniResto es un proyecto estudiantil independiente. No es un servicio oficial de la Universidad de Luxemburgo.",
               scan="Escanea para ver el menú de hoy y pedir", link="Escribe esta dirección en el navegador de tu móvil", hot="Plato del día"),
    "pt": dict(title="Menu de hoje", ad="Evite a fila — peça com antecedência",
               body="Escolha o seu prato no telemóvel, sem conta, só com o seu e-mail universitário. Peça antes das 13:00 e um colega pode levá-lo ao seu edifício.",
               fine="O UniResto é um projeto estudantil independente. Não é um serviço oficial da Universidade do Luxemburgo.",
               scan="Leia o código para ver o menu de hoje e pedir", link="Escreva este endereço no navegador do telemóvel", hot="Prato do dia"),
    "ru": dict(title="Меню на сегодня", ad="Не стойте в очереди — заказывайте заранее",
               body="Выберите блюдо на телефоне — без регистрации, только с университетской почтой. Закажите до 13:00, и другой студент принесёт заказ в ваше здание.",
               fine="UniResto — независимый студенческий проект. Это не официальный сервис Университета Люксембурга.",
               scan="Отсканируйте, чтобы увидеть меню на сегодня и заказать", link="Введите этот адрес в браузере телефона", hot="Горячее блюдо"),
    "zh": dict(title="今日菜单", ad="免排队——提前点餐",
               body="用手机选菜，无需注册，只需大学邮箱。13:00前下单，另一位同学可将餐点送到你所在的楼。",
               fine="UniResto 是独立的学生项目，并非卢森堡大学的官方服务。",
               scan="扫码查看今日菜单并点餐", link="在手机浏览器中输入此网址", hot="热菜"),
    "hi": dict(title="आज का मेनू", ad="कतार से बचें — पहले से ऑर्डर करें",
               body="अपने फ़ोन पर पकवान चुनें, किसी खाते की ज़रूरत नहीं, बस आपका विश्वविद्यालय ईमेल। 13:00 से पहले ऑर्डर करें और कोई साथी छात्र उसे आपकी इमारत तक पहुँचा सकता है।",
               fine="UniResto एक स्वतंत्र छात्र परियोजना है। यह लक्ज़मबर्ग विश्वविद्यालय की आधिकारिक सेवा नहीं है।",
               scan="आज का मेनू देखने और ऑर्डर करने के लिए स्कैन करें", link="इस पते को अपने फ़ोन के ब्राउज़र में लिखें", hot="गरम व्यंजन"),
    "ar": dict(title="قائمة اليوم", ad="تجنّب الطابور — اطلب مسبقًا",
               body="اختر طبقك من هاتفك، دون حساب، فقط ببريدك الجامعي. اطلب قبل الساعة 13:00 ويمكن لزميل طالب إيصاله إلى مبناك.",
               fine="UniResto مشروع طلابي مستقل، وليس خدمة رسمية لجامعة لوكسمبورغ.",
               scan="امسح الرمز لعرض قائمة اليوم والطلب", link="اكتب هذا العنوان في متصفح هاتفك", hot="طبق ساخن"),
    "bn": dict(title="আজকের মেনু", ad="লাইন এড়ান — আগেই অর্ডার করুন",
               body="আপনার ফোনে খাবার বেছে নিন, কোনো অ্যাকাউন্ট লাগবে না, শুধু বিশ্ববিদ্যালয়ের ইমেল। ১৩:০০-এর আগে অর্ডার করুন, আর একজন সহপাঠী আপনার ভবনে পৌঁছে দিতে পারবে।",
               fine="UniResto একটি স্বাধীন ছাত্র প্রকল্প। এটি লুক্সেমবার্গ বিশ্ববিদ্যালয়ের অফিসিয়াল সেবা নয়।",
               scan="আজকের মেনু দেখতে ও অর্ডার করতে স্ক্যান করুন", link="আপনার ফোনের ব্রাউজারে এই ঠিকানা লিখুন", hot="গরম খাবার"),
    "ur": dict(title="آج کا مینو", ad="قطار سے بچیں — پہلے سے آرڈر کریں",
               body="اپنے فون پر ڈش چنیں، اکاؤنٹ کی ضرورت نہیں، صرف آپ کی یونیورسٹی کی ای میل۔ 13:00 سے پہلے آرڈر کریں اور کوئی ساتھی طالب علم اسے آپ کی عمارت تک پہنچا سکتا ہے۔",
               fine="UniResto ایک آزاد طلبہ منصوبہ ہے۔ یہ لکسمبرگ یونیورسٹی کی سرکاری سروس نہیں ہے۔",
               scan="آج کا مینو دیکھنے اور آرڈر کرنے کے لیے اسکین کریں", link="یہ پتہ اپنے فون کے براؤزر میں لکھیں", hot="گرم کھانا"),
    "lb": dict(title="Menü vum Dag", ad="Spuert d'Schlaang — bestellt am Viraus",
               body="Wielt Äert Iessen um Handy, ouni Kont, nëmmen mat Ärer Uni-E-Mail. Bestellt virun 13:00 an e Matstudent kann et bei Äert Gebai bréngen.",
               fine="UniResto ass e onofhängegt Studenteprojet. Et ass keen offiziellen Déngscht vun der Universitéit Lëtzebuerg.",
               scan="Scannt fir de Menü vum Dag ze gesinn a ze bestellen", link="Gitt dës Adress am Browser vum Handy an", hot="Waarmt Geriicht"),
}


def _get(path: str):
    return json.load(urllib.request.urlopen(APP + path, timeout=30))


_photos: dict[str, dict] = {}


def photos(slug: str) -> dict:
    if slug not in _photos:
        data = _get(f"/api/restaurants/{slug}/dish-photos")
        _photos[slug] = data.get("photos", data)
    return _photos[slug]


def photo_uri(slug: str, category: str, name: str) -> str:
    from PIL import Image

    im = Image.open(PHOTO_DIR / Path(photos(slug)[category][name]).name).convert("RGB")
    w, h = im.size
    cw, ch = (w, int(w * 3 / 4)) if w * 3 <= h * 4 else (int(h * 4 / 3), h)
    im = im.crop(((w - cw) // 2, (h - ch) // 2, (w + cw) // 2, (h + ch) // 2)).resize((520, 390))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def qr_uri(slug: str, src: str, lang: str) -> str:
    import segno

    buf = io.BytesIO()
    segno.make(f"https://resto.unilu.space/?src={src}&r={slug}&lang={lang}", error="m").save(buf, kind="png", scale=10, border=2)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def has_menu(date: str) -> bool:
    """True when at least one restaurant has a daily menu for `date` (a weekend or a holiday has none)."""
    for slug, _, _ in RESTAURANTS:
        try:
            items = _get(f"/api/restaurants/{slug}/menu/{date}")["items"]
        except Exception:  # noqa: BLE001 -- a restaurant with no data that day simply has no menu
            continue
        if any(it["category"] in DAILY for it in items):
            return True
    return False


def picks_for(date: str, text: dict) -> list[tuple]:
    """12 cards: the day's photographed hot dishes first, then the always-available foods."""
    names = {slug: label for slug, label, _ in RESTAURANTS}
    seen: dict = {}
    picks: list = []
    for slug, _, _ in RESTAURANTS:
        try:
            items = _get(f"/api/restaurants/{slug}/menu/{date}")["items"]
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            if it["category"] in DAILY and photos(slug).get(it["category"], {}).get(it["name"]):
                key = (it["category"], it["name"])
                if key in seen:
                    seen[key][3].append(names[slug])
                else:
                    seen[key] = [slug, it["category"], it["name"], [names[slug]]]
                    picks.append(seen[key])
    out = [(s, c, n, f"{text['hot']} · " + " & ".join(w)) for s, c, n, w in picks][:6]
    for cat, name in ALWAYS:
        if len(out) >= 12:
            break
        out.append(("altius", cat, name, BOTH))
    return out


def page_html(date: str, lang: str, with_qr: bool) -> str:
    text = TEXT[lang]
    cards = ""
    for slug, cat, name, where in picks_for(date, text):
        label = SHORTER_EN.get(name) if lang == "en" and name in SHORTER_EN else dish_name_label(name, lang)
        cards += (
            f'<div class="card"><img src="{photo_uri(slug, cat, name)}"><div class="nm">{html.escape(label)}</div>'
            f'<div class="wh">{html.escape(where)}</div></div>'
        )
    if with_qr:
        boxes = "".join(
            f'<div class="qrbox"><img class="qr" src="{qr_uri(slug, src, lang)}"><div class="scan">{html.escape(label)}</div></div>'
            for slug, label, src in RESTAURANTS
        )
        action, hint = f'<div class="qrs">{boxes}</div>', text["scan"]
    else:
        action, hint = '<div class="url-big">resto.unilu.space</div>', text["link"]
    direction = "rtl" if lang in RTL else "ltr"
    return f"""<!doctype html><html lang="{lang}" dir="{direction}"><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 0 }} * {{ box-sizing: border-box; }}
body {{ margin:0; width:210mm; height:297mm; display:flex; flex-direction:column; color:#14171a; background:#f7f8fa;
  font-family:"Noto Sans","Noto Sans CJK SC","Noto Sans Devanagari","Noto Sans Bengali","Noto Sans Arabic","DejaVu Sans",-apple-system,"Helvetica Neue",Arial,sans-serif; }}
.top {{ background:#1aa860; color:#fff; padding:9mm 14mm 6mm; border-radius:0 0 8mm 8mm; }}
.brand {{ font-size:10.5pt; letter-spacing:.14em; text-transform:uppercase; opacity:.9; font-weight:700 }}
h1 {{ margin:2mm 0 1mm; font-size:27pt; line-height:1.15 }} .date {{ font-size:13pt; opacity:.95 }}
.grid {{ flex:1; min-height:0; display:grid; grid-template-columns:repeat(3,1fr); grid-template-rows:repeat(4,1fr); gap:5mm; padding:6mm 14mm 0; }}
.card {{ background:#fff; border:1px solid #edeef1; border-radius:5mm; padding:2.5mm; display:flex; flex-direction:column; min-height:0; overflow:hidden }}
.card img {{ width:100%; flex:1; min-height:0; object-fit:cover; border-radius:3.2mm; display:block }}
.nm {{ margin:2mm 1mm 0; font-size:9.6pt; font-weight:700; line-height:1.25; max-height:2.6em; overflow:hidden }}
.wh {{ margin:.6mm 1mm .4mm; font-size:7.4pt; color:#128248; font-weight:600 }}
.ad {{ margin:5mm 14mm 10mm; background:#e6f7ee; border:1px solid #bfe8d1; border-radius:6mm; padding:5mm 7mm; display:flex; gap:7mm; align-items:center }}
.ad h3 {{ margin:0 0 1.6mm; font-size:15pt; color:#128248; line-height:1.25 }} .ad p {{ margin:0 0 1.4mm; font-size:9.4pt; line-height:1.4 }} .ad .fine {{ font-size:7.6pt; color:#6b7280 }}
.qrs {{ display:flex; gap:4mm }} .qrbox {{ text-align:center }}
.qr {{ width:27mm; height:27mm; display:block; background:#fff; padding:1.6mm; border-radius:3mm }}
.scan {{ margin-top:1.4mm; font-size:8pt; font-weight:700; color:#128248 }} .hint {{ margin-top:1.6mm; text-align:center; font-size:7.6pt; font-weight:600; color:#128248; max-width:62mm }}
.url-big {{ width:60mm; padding:5mm 2mm; background:#fff; border-radius:3mm; font-size:15pt; font-weight:800; color:#128248; text-align:center; direction:ltr }}
.right {{ flex:none }}
</style></head><body>
<div class="top"><div class="brand">UniResto · Kirchberg</div><h1>{html.escape(text['title'])}</h1><div class="date" id="d"></div></div>
<div class="grid">{cards}</div>
<div class="ad"><div style="flex:1"><h3>{html.escape(text['ad'])}</h3><p>{html.escape(text['body'])}</p><p class="fine">{html.escape(text['fine'])}</p></div>
<div class="right">{action}<div class="hint">{html.escape(hint)}</div></div></div>
<script>document.getElementById('d').textContent = new Intl.DateTimeFormat('{lang}', {{weekday:'long', day:'numeric', month:'long', year:'numeric'}}).format(new Date('{date}T12:00:00'));</script>
</body></html>"""


async def build(date: str, lang: str, out_dir: Path) -> list[Path]:
    from playwright.async_api import async_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        for suffix, with_qr in (("qr", True), ("link", False)):
            page = await browser.new_page()
            await page.set_content(page_html(date, lang, with_qr))
            await page.wait_for_timeout(400)
            path = out_dir / f"uniresto-menu-{date}-{lang}-{suffix}.pdf"
            await page.pdf(path=str(path), format="A4", print_background=True, prefer_css_page_size=True)
            await page.close()
            made.append(path)
        await browser.close()
    return made


if __name__ == "__main__":
    day, language = sys.argv[1], sys.argv[2]
    target = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/root/exports/adv")
    for made_path in asyncio.run(build(day, language, target)):
        print(made_path)
