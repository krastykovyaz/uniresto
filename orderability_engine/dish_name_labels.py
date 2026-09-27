"""Dish-name translations for the delivery notification email (Part 72).

MANUAL COPY of static/i18n.js's own DISH_NAME_LABELS -- kept here rather
than loaded from one shared source because i18n.js is loaded synchronously
by every render in the browser (see dishNameLabel()'s callers throughout
static/app.js) while this module only needs it for the one place Python
ever has to show a dish name in a language other than French: building
the courier's delivery-notification email (see mailer.py's
_triple_dish_names()). Same closed-vocabulary rule as the JS original --
only real, human-checked translations go in this table; a name not
covered here is shown as Restopolis itself wrote it, never guessed.

Whenever a name is added to static/i18n.js's DISH_NAME_LABELS, add the
same entry here too (or regenerate this file -- see the git history of
this file for the one-off script that built it from i18n.js).
"""

from __future__ import annotations

DEFAULT_LANG = "en"

DISH_NAME_LABELS: dict[str, dict[str, str]] = {
    "Banane \"commerce équitable\"": {
        "en": "Fair trade banana",
        "zh": "公平贸易香蕉",
        "hi": "फेयर ट्रेड केला",
        "es": "Plátano de comercio justo",
        "fr": "Banane \"commerce équitable\"",
        "ar": "موز تجارة عادلة",
        "bn": "ফেয়ার ট্রেড কলা",
        "pt": "Banana de comércio justo",
        "ru": "Банан справедливой торговли",
        "ur": "فیئر ٹریڈ کیلا",
        "lb": "Fair-Trade Banann"
    },
    "Barquette pour pâtes/salades à emporter": {
        "en": "Takeaway container for pasta/salads",
        "zh": "意面/沙拉外带餐盒",
        "hi": "पास्ता/सलाद टेकअवे कंटेनर",
        "es": "Envase para llevar de pasta/ensaladas",
        "fr": "Barquette pour pâtes/salades à emporter",
        "ar": "علبة للطلب الخارجي للمعكرونة/السلطات",
        "bn": "পাস্তা/সালাদ টেকঅ্যাওয়ে বাক্স",
        "pt": "Embalagem para levar de massa/saladas",
        "ru": "Контейнер навынос для пасты/салатов",
        "ur": "پاستا/سلاد ٹیک اوے کنٹینر",
        "lb": "Matnehm-Këscht fir Zalot/Nuddelen"
    },
    "Café \"commerce équitable\"": {
        "en": "Fair trade coffee",
        "zh": "公平贸易咖啡",
        "hi": "फेयर ट्रेड कॉफ़ी",
        "es": "Café de comercio justo",
        "fr": "Café \"commerce équitable\"",
        "ar": "قهوة تجارة عادلة",
        "bn": "ফেয়ার ট্রেড কফি",
        "pt": "Café de comércio justo",
        "ru": "Кофе справедливой торговли",
        "ur": "فیئر ٹریڈ کافی",
        "lb": "Fair-Trade Kaffi"
    },
    "Carottes persillées": {
        "en": "Parsleyed carrots",
        "zh": "欧芹胡萝卜",
        "hi": "अजमोद के साथ गाजर",
        "es": "Zanahorias al perejil",
        "fr": "Carottes persillées",
        "ar": "جزر بالبقدونس",
        "bn": "পার্সলে গাজর",
        "pt": "Cenouras com salsa",
        "ru": "Морковь с петрушкой",
        "ur": "اجمود کے ساتھ گاجر",
        "lb": "Muert mat Peitercili"
    },
    "Chocolat chaud \"Commerce équitable\"": {
        "en": "Fair trade hot chocolate",
        "zh": "公平贸易热巧克力",
        "hi": "फेयर ट्रेड हॉट चॉकलेट",
        "es": "Chocolate caliente de comercio justo",
        "fr": "Chocolat chaud \"Commerce équitable\"",
        "ar": "شوكولاتة ساخنة تجارة عادلة",
        "bn": "ফেয়ার ট্রেড হট চকোলেট",
        "pt": "Chocolate quente de comércio justo",
        "ru": "Горячий шоколад справедливой торговли",
        "ur": "فیئر ٹریڈ ہاٹ چاکلیٹ",
        "lb": "Fair-Trade waarme Kakao"
    },
    "Couvercle pour barquette à emporter": {
        "en": "Lid for takeaway container",
        "zh": "外带餐盒盖",
        "hi": "टेकअवे कंटेनर का ढक्कन",
        "es": "Tapa para envase para llevar",
        "fr": "Couvercle pour barquette à emporter",
        "ar": "غطاء لعلبة الطلب الخارجي",
        "bn": "টেকঅ্যাওয়ে বাক্সের ঢাকনা",
        "pt": "Tampa para embalagem para levar",
        "ru": "Крышка для контейнера навынос",
        "ur": "ٹیک اوے کنٹینر کا ڈھکن",
        "lb": "Deckel fir Matnehm-Këscht"
    },
    "Cuillère comestible": {
        "en": "Edible spoon",
        "zh": "可食用勺子",
        "hi": "खाने योग्य चम्मच",
        "es": "Cuchara comestible",
        "fr": "Cuillère comestible",
        "ar": "ملعقة صالحة للأكل",
        "bn": "ভোজ্য চামচ",
        "pt": "Colher comestível",
        "ru": "Съедобная ложка",
        "ur": "کھانے کے قابل چمچ",
        "lb": "Iessbar Läffel"
    },
    "Dessert du Jour": {
        "en": "Dessert of the day",
        "zh": "今日甜点",
        "hi": "आज का मिठाई",
        "es": "Postre del día",
        "fr": "Dessert du Jour",
        "ar": "حلوى اليوم",
        "bn": "আজকের ডেজার্ট",
        "pt": "Sobremesa do dia",
        "ru": "Десерт дня",
        "ur": "آج کا میٹھا",
        "lb": "Dessert vum Dag"
    },
    "Faux-filet de boeuf grillé sauce Béarnaise": {
        "en": "Grilled beef sirloin with Béarnaise sauce",
        "zh": "烤牛排配贝亚恩酱",
        "hi": "बियर्नेज़ सॉस के साथ ग्रिल्ड बीफ़ सिरलॉइन",
        "es": "Solomillo de ternera a la parrilla con salsa bearnesa",
        "fr": "Faux-filet de boeuf grillé sauce Béarnaise",
        "ar": "شريحة لحم بقري مشوية بصلصة البيارنيز",
        "bn": "বেয়ারনেজ সসসহ গ্রিলড বিফ সিরলোইন",
        "pt": "Lombo de vaca grelhado com molho bearnaise",
        "ru": "Жареный говяжий стейк с соусом беарнез",
        "ur": "بیئرنیز ساس کے ساتھ گرل بیف سرلوئن",
        "lb": "Gegrillten Rëndsentrecote mat Bearnaise-Zooss"
    },
    "Fourchette en bois": {
        "en": "Wooden fork",
        "zh": "木叉",
        "hi": "लकड़ी का काँटा",
        "es": "Tenedor de madera",
        "fr": "Fourchette en bois",
        "ar": "شوكة خشبية",
        "bn": "কাঠের কাঁটাচামচ",
        "pt": "Garfo de madeira",
        "ru": "Деревянная вилка",
        "ur": "لکڑی کا کانٹا",
        "lb": "Holzgabel"
    },
    "Fruit frais entier": {
        "en": "Whole fresh fruit",
        "zh": "新鲜水果（整个）",
        "hi": "साबुत ताज़ा फल",
        "es": "Fruta fresca entera",
        "fr": "Fruit frais entier",
        "ar": "فاكهة طازجة كاملة",
        "bn": "গোটা তাজা ফল",
        "pt": "Fruta fresca inteira",
        "ru": "Целый свежий фрукт",
        "ur": "پورا تازہ پھل",
        "lb": "Ganz frësch Uebst"
    },
    "Gobelet comestible 220 ml": {
        "en": "Edible cup 220 ml",
        "zh": "可食用杯 220 毫升",
        "hi": "खाने योग्य कप 220 मिली",
        "es": "Vaso comestible 220 ml",
        "fr": "Gobelet comestible 220 ml",
        "ar": "كوب صالح للأكل 220 مل",
        "bn": "ভোজ্য কাপ ২২০ মিলি",
        "pt": "Copo comestível 220 ml",
        "ru": "Съедобный стакан 220 мл",
        "ur": "کھانے کے قابل کپ 220 ملی",
        "lb": "Iessbar Becher 220 ml"
    },
    "Mini fruits découpés mélangés/non-mélangés 150 g": {
        "en": "Mini cut fruit, mixed/plain 150 g",
        "zh": "迷你切块水果（混合/单一）150克",
        "hi": "मिनी कटे फल, मिश्रित/सादा 150 ग्राम",
        "es": "Mini fruta cortada, mixta/sencilla 150 g",
        "fr": "Mini fruits découpés mélangés/non-mélangés 150 g",
        "ar": "فواكه مقطعة صغيرة، مشكلة/فردية 150 غ",
        "bn": "মিনি কাটা ফল, মিশ্র/সাধারণ ১৫০ গ্রাম",
        "pt": "Mini fruta cortada, mista/simples 150 g",
        "ru": "Мини нарезанные фрукты, смешанные/обычные 150 г",
        "ur": "منی کٹے پھل، ملے جلے/سادہ 150 گرام",
        "lb": "Mini geschniddent Uebst, gemëscht/eenzel 150 g"
    },
    "Mini salades 150 g": {
        "en": "Mini salads 150 g",
        "zh": "迷你沙拉 150克",
        "hi": "मिनी सलाद 150 ग्राम",
        "es": "Mini ensaladas 150 g",
        "fr": "Mini salades 150 g",
        "ar": "سلطات صغيرة 150 غ",
        "bn": "মিনি সালাদ ১৫০ গ্রাম",
        "pt": "Mini saladas 150 g",
        "ru": "Мини-салаты 150 г",
        "ur": "منی سلاد 150 گرام",
        "lb": "Mini Zalot 150 g"
    },
    "Petit bol de potage": {
        "en": "Small bowl of soup",
        "zh": "小份浓汤",
        "hi": "छोटा सूप का कटोरा",
        "es": "Tazón pequeño de sopa",
        "fr": "Petit bol de potage",
        "ar": "وعاء صغير من الحساء",
        "bn": "ছোট বাটি স্যুপ",
        "pt": "Taça pequena de sopa",
        "ru": "Маленькая тарелка супа",
        "ur": "سوپ کا چھوٹا پیالہ",
        "lb": "Kleng Zopp-Schierbel"
    },
    "Poche aux pommes 80 g": {
        "en": "Apple turnover 80 g",
        "zh": "苹果酥饼 80克",
        "hi": "सेब टर्नओवर 80 ग्राम",
        "es": "Empanadilla de manzana 80 g",
        "fr": "Poche aux pommes 80 g",
        "ar": "فطيرة تفاح 80 غ",
        "bn": "আপেল টার্নওভার ৮০ গ্রাম",
        "pt": "Folhado de maçã 80 g",
        "ru": "Яблочный слоёный пирожок 80 г",
        "ur": "سیب کا ٹرن اوور 80 گرام",
        "lb": "Äppelzak 80 g"
    },
    "Pommes de terre grenailles rôties": {
        "en": "Roasted new potatoes",
        "zh": "烤小土豆",
        "hi": "भुनी हुई नई आलू",
        "es": "Patatas nuevas asadas",
        "fr": "Pommes de terre grenailles rôties",
        "ar": "بطاطس صغيرة محمصة",
        "bn": "রোস্ট করা নতুন আলু",
        "pt": "Batatas novas assadas",
        "ru": "Запечённый молодой картофель",
        "ur": "بھنے ہوئے نئے آلو",
        "lb": "Gebrode Fréikartoffelen"
    },
    "Rôti de porc Orloff, jus lié": {
        "en": "Pork roast Orloff, thickened jus",
        "zh": "奥尔洛夫烤猪肉配浓肉汁",
        "hi": "पोर्क रोस्ट ऑरलॉफ़, गाढ़ा जूस",
        "es": "Asado de cerdo Orloff, jugo ligado",
        "fr": "Rôti de porc Orloff, jus lié",
        "ar": "لحم خنزير روستو أورلوف مع صلصة مكثفة",
        "bn": "পোর্ক রোস্ট অরলফ, ঘন গ্রেভি",
        "pt": "Assado de porco Orloff, molho engrossado",
        "ru": "Свиное жаркое Орлов, загущённый соус",
        "ur": "پورک روسٹ اورلوف، گاڑھا جوس",
        "lb": "Schweinsbrode Orloff, gebonnene Jus"
    },
    "Sachet pour sandwiches": {
        "en": "Sandwich bag",
        "zh": "三明治袋",
        "hi": "सैंडविच बैग",
        "es": "Bolsa para sándwiches",
        "fr": "Sachet pour sandwiches",
        "ar": "كيس للسندويشات",
        "bn": "স্যান্ডউইচ ব্যাগ",
        "pt": "Saco para sandes",
        "ru": "Пакет для сэндвичей",
        "ur": "سینڈوچ بیگ",
        "lb": "Sandwich-Täitchen"
    },
    "Salade aux mezzés variés": {
        "en": "Salad with assorted mezze",
        "zh": "什锦前菜沙拉",
        "hi": "मिश्रित मेज़े सलाद",
        "es": "Ensalada con mezze variados",
        "fr": "Salade aux mezzés variés",
        "ar": "سلطة بالمقبلات المتنوعة",
        "bn": "বিভিন্ন মেজে সহ সালাদ",
        "pt": "Salada com mezze variados",
        "ru": "Салат с ассорти мезе",
        "ur": "مختلف مزے کے ساتھ سلاد",
        "lb": "Zalot mat verschiddene Mezze"
    },
    "Salade campagnarde": {
        "en": "Country salad",
        "zh": "乡村沙拉",
        "hi": "देहाती सलाद",
        "es": "Ensalada campestre",
        "fr": "Salade campagnarde",
        "ar": "سلطة ريفية",
        "bn": "গ্রাম্য সালাদ",
        "pt": "Salada camponesa",
        "ru": "Деревенский салат",
        "ur": "دیہاتی سلاد",
        "lb": "Bauereszalot"
    },
    "Serviette en papier (à partir de la 2e serviette)": {
        "en": "Paper napkin (from the 2nd napkin)",
        "zh": "纸巾（自第2张起收费）",
        "hi": "पेपर नैपकिन (दूसरे नैपकिन से)",
        "es": "Servilleta de papel (a partir de la 2.ª)",
        "fr": "Serviette en papier (à partir de la 2e serviette)",
        "ar": "منديل ورقي (من المنديل الثاني)",
        "bn": "কাগজের ন্যাপকিন (২য়টি থেকে)",
        "pt": "Guardanapo de papel (a partir do 2.º)",
        "ru": "Бумажная салфетка (со 2-й салфетки)",
        "ur": "کاغذی نیپکن (دوسرے نیپکن سے)",
        "lb": "Pabeier-Salvett (vun der 2. Salvett un)"
    },
    "Soupe de pommes de terre": {
        "en": "Potato soup",
        "zh": "土豆汤",
        "hi": "आलू का सूप",
        "es": "Sopa de patata",
        "fr": "Soupe de pommes de terre",
        "ar": "شوربة البطاطس",
        "bn": "আলুর স্যুপ",
        "pt": "Sopa de batata",
        "ru": "Картофельный суп",
        "ur": "آلو کا سوپ",
        "lb": "Kartoffelzopp"
    },
    "Thé \"commerce équitable\"": {
        "en": "Fair trade tea",
        "zh": "公平贸易茶",
        "hi": "फेयर ट्रेड चाय",
        "es": "Té de comercio justo",
        "fr": "Thé \"commerce équitable\"",
        "ar": "شاي تجارة عادلة",
        "bn": "ফেয়ার ট্রেড চা",
        "pt": "Chá de comércio justo",
        "ru": "Чай справедливой торговли",
        "ur": "فیئر ٹریڈ چائے",
        "lb": "Fair-Trade Téi"
    },
    "Tisane": {
        "en": "Herbal tea",
        "zh": "花草茶",
        "hi": "हर्बल चाय",
        "es": "Infusión de hierbas",
        "fr": "Tisane",
        "ar": "شاي أعشاب",
        "bn": "ভেষজ চা",
        "pt": "Chá de ervas",
        "ru": "Травяной чай",
        "ur": "جڑی بوٹیوں کی چائے",
        "lb": "Kraidentéi"
    },
    "Wrap aux falafels": {
        "en": "Falafel wrap",
        "zh": "法拉费卷饼",
        "hi": "फ़लाफ़ेल रैप",
        "es": "Wrap de falafel",
        "fr": "Wrap aux falafels",
        "ar": "راب فلافل",
        "bn": "ফালাফেল র‍্যাপ",
        "pt": "Wrap de falafel",
        "ru": "Ролл с фалафелем",
        "ur": "فلافل ریپ",
        "lb": "Falafel-Wrap"
    },
    "Wrap façon croque monsieur": {
        "en": "Croque monsieur-style wrap",
        "zh": "法式火腿芝士卷饼",
        "hi": "क्रोक-मस्यू शैली रैप",
        "es": "Wrap estilo croque monsieur",
        "fr": "Wrap façon croque monsieur",
        "ar": "راب على طريقة الكروك موسيو",
        "bn": "ক্রক মসিয়ে স্টাইল র‍্যাপ",
        "pt": "Wrap estilo croque monsieur",
        "ru": "Ролл в стиле крок-месье",
        "ur": "کروک موسیو انداز کا ریپ",
        "lb": "Wrap am Stil vum Croque Monsieur"
    }
}


def dish_name_label(raw_name: str, lang: str) -> str:
    """Mirrors static/i18n.js's own dishNameLabel(): a real, human-checked
    translation when this specific Restopolis-written name is in the
    table above, else the raw name unchanged -- never a guessed/machine
    translation of arbitrary free text (see this module's docstring)."""
    entry = DISH_NAME_LABELS.get(raw_name)
    if entry is None:
        return raw_name
    return entry.get(lang) or entry.get(DEFAULT_LANG) or raw_name

