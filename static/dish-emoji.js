// Default picture for a dish that has no photo: one emoji, chosen from the
// dish's name (first matching keyword wins -- order matters) and, failing that,
// from its Restopolis category. Pure and DOM-free so it can be unit-tested
// (tests_js/dish-emoji.test.mjs). Never claims to be a photo of the dish: it's
// a generic symbol, like the abstract illustration it replaces.

const NAME_EMOJI = [
  // packaging and extras first, so "Sachet pour sandwiches" is a bag, not a sandwich
  [/(sachet|couvercle|barquette|serviette|cuillere comestible|fourchette|gobelet|ecobox|mybento|mybowl|mycan|myfrupstut|mykit|myminibowl|mynapkin|mymug)/,"🥡"],
  [/(bretzel|pretzel)/,"🥨"],
  [/(pain au chocolat|croissant|chausson|huit|streusel|poche aux|viennoiserie)/,"🥐"],
  [/(cheesecake|gateau|cake|brownie|financier|eclair|paris.?brest|tiramisu|foret noire)/,"🍰"],
  [/(crispy apple)/,"🍏"],
  [/(cookie|biscuit|nutchy|crunchy)/,"🍪"],
  [/(glace|cornet|dame blanche)/,"🍦"],
  [/mousse de saumon/,"🐟"],
  [/(panna cotta|creme catalane|creme brul|mousse|banaboom|flan|riz au lait|dessert du jour)/,"🍮"],
  [/(strudel|clafoutis|tarte sucree|tarte tatin|pomme au four)/,"🥧"],
  [/(muesli|porridge|granola)/,"🥣"],
  [/^(yaourt|mini fromage frais|fromage blanc|skyr)/,"🥛"],
  [/\blait\b/,"🥛"],
  // sandwiches before meats/drinks: "jambon cuit", "egg sandwich" are fillings
  [/(sandwich|levain|ciabatta|baguette|petit pain|croque|panini|schockelasbotter|pain blanc)/,"🥪"],
  [/(chocolat chaud|cacao)/,"☕"],
  [/(cafe|espresso|cappuccino|latte|macchiato|ristretto)/,"☕"],
  [/\b(the|tea|infusion|tisane|camomille|rooibos)\b/,"🍵"],
  [/(sunny|jus|juice|smoothie|vitamine|drauwejus)/,"🧃"],
  [/(\beau\b|water|rosport|viva|lodyss|wasser)/,"💧"],
  [/(cola|limo|soda|sprite|fanta|ice tea|schweppes|orangina)/,"🥤"],
  [/(soupe|potage|veloute|minestrone|bouillon|creme de|gaspacho)/,"🍲"],
  [/(salad|salade|buddha|tapas vege)/,"🥗"],
  [/(wrap|tortilla|burrito|fajita)/,"🌯"],
  [/(burger)/,"🍔"],
  [/(kebab|gyros|shawarma|durum|doner)/,"🥙"],
  [/(pizza|focaccia|flammkuchen)/,"🍕"],
  [/(spaghetti|penne|tagliatelle|lasagne|pates|nouilles|pad tha|macaroni|farfalle|gnocchi|fusilli)/,"🍝"],
  [/(paella|risotto|\briz\b|basmati|zarzuela)/,"🍚"],
  [/(omelette|\boeuf|\begg)/,"🍳"],
  [/^tomate/,"🍅"],
  [/(curry|tikka|masala|colombo|chili|chilli|chakalaka|ragout|goulash|mijote|tajine|aloo|accras|wok)/,"🍛"],
  [/(frites|fritten|steakhouse|wedges|batonnets)/,"🍟"],
  [/(pommes de terre|gratin|dauphinois|parmentier|rosti|puree|croquette)/,"🥔"],
  [/(poulet|chicken|volaille|nugget|cuisse|dinde|mixed grill)/,"🍗"],
  [/(rumsteak|steak|boeuf|entrecote|faux-filet|hache|bolognaise|roulade|mignon|porc|jambon|saltimbocca|cordon bleu|schnitzel|escalope)/,"🥩"],
  [/boulettes de lentilles/,"🧆"],
  [/(saucisse|cevapcici|\bboulettes?\b|bratwurst|wiener|chipolata|lard|bacon)/,"🌭"],
  [/(colin|poisson|saumon|cabillaud|thon|truite|merlu|crevette|gambas|moule)/,"🐟"],
  [/(falafel|houmous|hummus|mezze)/,"🧆"],
  [/(samossa|empanada|nems?\b|gyoza|wonton|rouleau)/,"🥟"],
  [/(tarte|quiche|tourte|feuillete|nid au)/,"🥧"],
  [/(pain|tranche|toast)/,"🍞"],
  [/(feta|mozzarella|fromage|raclette|camembert)/,"🧀"],
  [/(tofu|tempeh|seitan|quorn|vegetal|vegan)/,"🥘"],
  [/(haricots?|petits pois|\bpois\b|mungo)/,"🫛"],
  [/(carotte)/,"🥕"],[/(brocoli)/,"🥦"],[/(champignon)/,"🍄"],[/(oignon|onion)/,"🧅"],
  [/(epinard|\bchou\b|laitue|mimosa)/,"🥬"],[/(courgette|concombre)/,"🥒"],
  [/(polenta|\bmais\b)/,"🌽"],[/(quinoa|semoule|couscous|boulgour|epeautre)/,"🍚"],
  [/(banane)/,"🍌"],[/(pomme)/,"🍎"],[/(poire)/,"🍐"],[/(quetsche|prune|peche|abricot)/,"🍑"],
  [/(orange|clementine|mandarine)/,"🍊"],[/(citron)/,"🍋"],[/(raisin)/,"🍇"],[/(fraise)/,"🍓"],[/(cerise)/,"🍒"],[/(fruit)/,"🍎"],
];
const CAT_EMOJI = [
  [/^(entree)/,"🥣"],[/vegan/,"🌱"],[/^vegetarien/,"🥘"],[/non-vegetarien/,"🍖"],[/feculents/,"🍚"],[/legumes/,"🥦"],
  [/^dessert/,"🍮"],[/snack/,"🥡"],[/sandwich/,"🥪"],[/viennoiserie/,"🥐"],[/gateaux|patisserie/,"🍰"],[/vitamines/,"🥗"],
  [/laitages/,"🥛"],[/fruits/,"🍎"],[/glaces/,"🍦"],[/boissons chaudes/,"☕"],[/boissons froides/,"🥤"],[/emballages/,"🥡"],
];
const norm = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
export function dishEmoji(item) {
  const n = norm(item.name) + " ";
  for (const [re,e] of NAME_EMOJI) if (re.test(n)) return e;
  const c = norm(item.category);
  for (const [re,e] of CAT_EMOJI) if (re.test(c)) return e;
  return "🍽️";
}
