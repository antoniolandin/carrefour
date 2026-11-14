"""Shared configuration for the wrangling pipeline (paths, FX, basket rules)."""
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

SOURCES = {
    "es": "es/resultados/products.json",
    "fr": "fr/products_fr.json",
    "it": "it/products_it_clean.json",
    "ro": "ro/products_ro.json",
}

# Collection date = date of the last git commit touching each country's result
# file (no timestamp was scraped). Used if git is not available at run time.
# LIMITATION: the commit date is an upper bound of the real collection date.
FALLBACK_COLLECTED = {"es": "2026-11-12", "fr": "2026-11-13", "it": "2026-11-11", "ro": "2026-11-13"}

# ECB euro foreign exchange reference rate, 1 EUR = X RON, keyed by date.
# Source: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
ECB_EUR_RON = {"2026-11-13": 5.3494}


def norm(text):
    """Lowercase, strip accents and collapse spaces (matching key only)."""
    if not text:
        return ""
    text = text.lower().replace("œ", "oe").replace("æ", "ae").replace("×", "x")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


# Basket rules. `inc` = regex per country that the normalised name must match;
# `exc` = regex (any language) that sends the row to the excluded file.
# The rules only remove OTHER product families (noise). Variants inside the
# family (brand, fat %, organic...) are kept: they are judged at annotation time.
BASKET = [
    dict(id=1, item="spaghetti",
         inc=dict(es=r"espagueti|spaghett|spaguett", fr=r"spaghetti", it=r"spaghett", ro=r"spaghet"),
         exc=r"salsa|sauce|sugo|\bsos\b|bolognes|bolones|carbonara|noodle|instant|calabac|konjac|soja|haricot|tomate|plato|pronti|hrana|cuchara|utensil|mesure"),
    dict(id=2, item="rice",
         inc=dict(es=r"^arroz\b", fr=r"\briz\b", it=r"\briso\b", ro=r"\borez\b"), it_cat={"riso"},
         exc=r"bebida|boisson|bevanda|bautura|tortitas|galettes?|gallette|napolitane|con leche|au lait|vinagre|vinaigre|aceto|otet|harina|farine|farina|faina|hrana|caini|pisici|aparat|budinca|pudding|souffle|expandat|creme?\b|crema|lapte|latte|biscuit|snack|chips|paste|pates|noodles|taitei|sirop|ulei|huile|olio|aceite|cu orez|sarmale|pilaf|micro|vasitos?|cocido|cuit|listo|papier|feuille|\bvin\b|sake|sampon|rondele|fulgi|paella|funghi|zafferano|farro|produs pe baza|desert|mochi|inghetata|bio organic baby|cereale"),
    dict(id=3, item="olive_oil",
         inc=dict(es=r"^aceite de oliva", fr=r"^huile d.?olive", it=r"olio.*oliva", ro=r"^ulei.*masline"),
         exc=r"atun|bonito|sardin|caballa|anchoa|mejillon|thon|tonno|\bton\b|macrou|sgombro|maquereau|file|spray|chips|sansa|orujo|pomace|grignons|turta|hering|somon|masline (verzi|negre)|ardei|rosii|aromatiz|trufa|tartuf|truffe|hrana"),
    dict(id=4, item="wheat_flour",
         inc=dict(es=r"^harina", fr=r"^farine", it=r"\bfarina\b", ro=r"\bfaina\b"),
         exc=r"maiz|arroz|garbanzo|avena|almendra|espelta|centeno|coco|\bmais\b|\briz\b|sarrasin|chataigne|seigle|epeautre|pois|avoine|riso|ceci|mandorl|farro|segale|porumb|orez|malai|secara|ovaz|migdal|naut|hrisca|spelta|biscuit|paste|pates|\bpasta\b|tempura|rebozar|freir|gnocchi|polenta|quinoa|soja|soia|castagn|lupin|cartofi|pesmet|paine|tortilla|napolitane|taitei|cozonac|grisine|covrig|sticks|blat|\bfoi\b|lipii|hrana"),
    dict(id=5, item="white_sugar",
         inc=dict(es=r"^azucar", fr=r"^sucre", it=r"\bzucchero\b", ro=r"\bzahar\b"),
         exc=r"moreno|cana|glas|vainill|coco|panela|canne|roux|glace|vanill|gelifiant|confiture|canna|velo|vanigl|brun|pudra|trestie|invertido|liquido|perle|candi|cassonade|stevia|edulcor|zero|fara|bautura|sirop|boluri|ceai"),
    dict(id=6, item="ground_coffee",
         inc=dict(es=r"^cafe.*molido", fr=r"moulu", it=r"macinat", ro=r"cafea.*macinat"), it_cat={"caffè_macinato"},
         exc=r"capsul|dosette|cialde|solubl|instant|boabe|rasnita|moulin|filtros"),
    dict(id=7, item="crushed_tomato",
         inc=dict(es=r"^tomate triturado", fr=r"pulpe.*tomate|tomates? concass", it=r"\bpolpa\b", ro=r"pulpa.*rosii|rosii.*(cuburi|tocate|maruntite|taiate)|\bpolpa\b"),
         exc=r"\bton\b|peste|hering|macrou|sardine|hrana"),
    dict(id=8, item="tuna_in_oil",
         inc=dict(es=r"^atun.*aceite", fr=r"\bthon\b.*huile", it=r"tonno.*olio", ro=r"^ton\b.*ulei"),
         exc=r"pate|ensalad|salade|insalat|salata|pisici|\bchat\b|gatt|hrana|rillettes|tartinabil"),
    dict(id=9, item="whole_milk",
         inc=dict(es=r"^leche entera", fr=r"^lait.*entier", it=r"\bintero\b", ro=r"^lapte.*(integral|3[.,]5)"),
         exc=r"polvo|poudre|polvere|praf|condens|concentr|yogur|iaurt|yaourt|chocolat|cacao|cabra|chevre|capra|oaie|brebis|pecora|oveja"),
    dict(id=10, item="plain_yogurt",
         inc=dict(es=r"^yogur.*natural", fr=r"^yaourt.*nature", it=r"yogurt.*(bianco|naturale)", ro=r"^iaurt.*natur"), it_cat={"yogurt_magro"},
         exc=r"soja|soia|soya|coco|vegetal|avena|almendra|amande|mandorl|ovaz|migdale|hrana|kefir"),
    dict(id=11, item="butter",
         inc=dict(es=r"^mantequilla", fr=r"^beurre", it=r"\bburro\b", ro=r"\bunt\b"),
         exc=r"cacahuete|arachid|arahide|cacao|karite|galleta|biscuit|biscott|croissant|margarin|ghee|clarif|palomitas|corp|labbra|cu unt|cozonac|aroma"),
    dict(id=12, item="corn_flakes",
         inc={c: r"corn ?flakes|copos de maiz|petales de mais|fiocchi di mais|fulgi de porumb" for c in ("es", "fr", "it", "ro")},
         exc=r"barrita|barre|baton|hrana|fish|peste|\bpui\b|snitel|crispy|granola|nugget"),
    dict(id=13, item="mineral_water",
         inc=dict(es=r"^agua mineral", fr=r"^eau.*(minerale|source)", it=r"\bacqua\b", ro=r"^apa\b.*(mineral|plata|izvor)"),
         it_cat={"acqua_frizzante"},
         exc=r"micelar|florale?|colonia|toilette|cologne|aromatiz|zumo|limon|citron|limone|lamaie|sabor|gout|gust|arome|tonic|parfum|demachiant|gura|oxigenata|distilata|demineral|coco|trandafir|fleur|javel"),
    dict(id=14, item="chicken_breast",
         inc=dict(es=r"^pechuga.*pollo", fr=r"(filets?|blancs?).*poulet", it=r"petto.*pollo", ro=r"piept.*pui"),
         exc=r"empanad|\bpanes?\b|panat|cordon|nugget|fiambre|jambon|sunca|lonchas?|tranches?|affettat|cott[ao]|hrana|pisici|caini|\bchat\b|chien|conserva|pate|pavo|dinde|curcan|ahumad|fume|afumat|roti|cocida|asada|grille|kebab|snitel|schnitzel|crispy|marinat|marine|burger|hamburg|salam|parizer|crenvur|aspic|supa|salata|sandwich"),
    dict(id=15, item="tomato",
         inc=dict(es=r"^tomates?\b", fr=r"^tomates?\b", it=r"\bpomodor[oi]", ro=r"^rosii\b"),
         exc=r"triturado|frito|salsa|concentr|entier|\bsec[oa]s?\b|sech|zumo|pelad|ketchup|entero|pulpe|concass|sauce|pelee|coulis|\bjus\b|farci|polpa|passata|pelati|sugo|secchi|succo|pulpa|\bsuc\b|\bsos\b|pasta|bulion|uscate|decojite|cuburi|tocate|conserva|rallado|tamizado|troceado|en aceite|a l.huile|sott.olio|in ulei|maruntite|taiate|sofrito|bote|lata|frasco|tarro|brik|confit|marinate|murate|gogonele|tomate de"),
    dict(id=16, item="potato",
         inc=dict(es=r"^patatas?\b", fr=r"^pommes? de terre", it=r"\bpatate\b", ro=r"^cartofi\b"), it_cat={"patate"},
         exc=r"fritas|fritte|chips|pure|congelad|surgel|paja|bravas|gajo|prefrit|snack|tortilla|ensalad|salade|rosti|saute|micro|crocchette|gnocchi|forno|dolci|americane|douce|dulci|boniato|prajiti|piure|congelati|\bpai\b|wedges|salata|cocida|cuite|vapeur|lessate|noisette|dauphine|duchesse|rissol|gratin|stick|pringles|lays|aperitiv|hash|parisienne|cuburi|cubes|fries|croccant|barchette|patasnella|mccain|lamb weston|patatine|veloci"),
    dict(id=17, item="apple",
         inc=dict(es=r"^manzanas?\b", fr=r"^pommes?\b", it=r"\bmel[ae]\b", ro=r"^mere\b"),
         exc=r"zumo|compota|pure|vinagre|sidra|chips|infusion|yogur|mermelada|nectar|compote|\bjus\b|cidre|vinaigre|dessert|duchesse|dauphine|noisette|rissol|frites|saute|succo|aceto|mousse|sidro|confettura|frullato|\bsuc\b|otet|compot|cidru|\bgem\b|ceai|rulou|baton|placinta|strudel|bautura|deshidrat|uscate|sechee|essiccat|asada|tarta|tarte|torta|de terre|grenade|\bpin\b|amour|granada"),
    dict(id=18, item="banana",
         inc=dict(es=r"^(platanos?|bananas?)\b", fr=r"^bananes?\b", it=r"^banane?\b", ro=r"^(w |baby )?banane\b"),
         exc=r"chips|sechee|uscate|deshidrat|essiccat|macho|plantain|pure|piure|\bsuc\b|nectar|smoothie|iaurt|lapte|budinca|cereale|biscuit|baton"),
    dict(id=19, item="eggs",
         inc=dict(es=r"^huevos?\b", fr=r"^oeufs?\b", it=r"\buova\b", ro=r"^oua\b"),
         exc=r"cocido|codorniz|chocolat|ciocolat|cioccolat|kinder|pascua|paques|pasqua|paste|liquido|clara|caille|\bdurs?\b|brouill|quaglia|sode|pasta|tagliatelle|all.uovo|prepelita|fierte|taitei|sorpresa|surprise|lump|poisson|truite|saumon|hilado|peste|icre"),
    dict(id=20, item="sliced_bread",
         inc=dict(es=r"^pan (de )?molde", fr=r"^pain de mie", it=r"pancarre|pan carre|bauletto|pane bianco", ro=r"paine.*toast|^toast\b"), it_cat={"pane_a_fette_e_pancarrè"},
         exc=r"prajitor|toaster|tostadora|grille-pain|brioche|briosce|ciabatt|tramezzin|segale|proteico"),
    dict(id=21, item="coca_cola",
         inc={c: r"coca.?cola" for c in ("es", "fr", "it", "ro")},
         exc=r"puzzle|verre|vaso|bicchier|pahar|balsam|bonbon|caramel|tic tac|mentos|chupa|glace|halls|lip smacker|gomme|jeleuri|haribo|t-shirt|tricou|\bmug\b"),
    dict(id=22, item="nutella",
         inc={c: r"nutella" for c in ("es", "fr", "it", "ro")},
         exc=r"biscuit|b.?ready|galleta|barrita|\bgo\b|muffin|croissant|cornetto|gelato|helado|glace|inghetata|napolitan|snack|pezzi|cono|\bice\b|barquette"),
]


# ---------------------------------------------------------------------------
# Step 3 - representative products. All text patterns run on normalised names.
# ---------------------------------------------------------------------------
# Carrefour own brands (private label) in the four countries.
PRIVATE_LABEL = r"carrefour|\bsimpl\b|el mercado|circulo de calidad|de nuestra tierra|reflets de france|terre d.?italia|filiere qualite|filiera qualita"
# Own-brand lines that are NOT the standard/economy tier (organic, premium, regional).
PRIVATE_PREMIUM = r"\b(bio|eco|extra|selection|sensation|sensations|original|kids)\b|reflets|terre d|nuestra tierra|circulo|filier|le marche"
# "Brands" that are really category words or placeholders.
NOT_A_BRAND = {"", "marca nacional sin marca", "patate", "frutta", "verdura", "pomodori", "colture", "banane", "mele", "uova"}

# Variants that are never the standard product, whatever the basket item.
# (Gluten-free is handled per item: Spanish names carry "Sin Gluten" as a generic claim.)
GENERIC_AVOID = (r"\bbio\b|biolog|ecolog|\beco\b|organic|"
                 r"integral|complet\b|sin lactosa|sans lactose|senza lattosio|fara lactoza|delact|proteic|protein|"
                 r"\blight\b|descafein|decafein|decaffein|decofein|sin azucar|sans sucre|senza zuccher|fara zahar")

# target = (basis, standard single-unit size, standard total size). A candidate's
# format is compared with both and the better similarity is used.
# avoid  = non-standard variants of this item (lower the score, never delete).
# require= specification the standard product must show.
# brand  = fixed brand for brand-defined items; produce=True -> no brand profile.
PROFILE = {
    "spaghetti":      dict(target=("kg", 0.5, 0.5), avoid=r"sin gluten|sans gluten|senza glutine|fara gluten|gluten free|huevo|oeuf|uovo|\bou\b|legum|lentej|garbanz|ceci|pois|nero|tinta|seppia|rapid|3 min|kamut|farro|espelta"),
    "rice":           dict(target=("kg", 1, 1), avoid=r"basmati|thai|jasmin|vaporizad|parboil|etuve|incoll|risott|arborio|carnaroli|sushi|bomba|salvaje|sauvage|selvaggio|venere|negro|noir|rojo|rouge|rosso|precocido|10 ?min|expres|sachet|bolsas|microond|camargue|camarague|gourmet"),
    "olive_oil":      dict(target=("l", 1, 1), require=r"virgen extra|vierge extra|extra vergine|extra ?virgin|extravirgin|extravergine"),
    "wheat_flour":    dict(target=("kg", 1, 1), avoid=r"sin gluten|sans gluten|senza glutine|fara gluten|gluten free|fuerza|reposteria|pizza|manitoba|autolievit|levure|bizcoch|gateau|dolci|\bpan\b|pain|pane\b|t65|t80|t110|t150|650|neagra|semola|duro|\bdur\b"),
    "white_sugar":    dict(target=("kg", 1, 1), avoid=r"cubic|cuburi|morceaux|zollette|terron|baghete|sticks|buchette|sobres"),
    "ground_coffee":  dict(target=("kg", 0.25, 0.25), avoid=r"aromat|vanil|caramel|avellan|noisette|nocciol"),
    "crushed_tomato": dict(target=("kg", 0.4, 0.4), avoid=r"\bajo\b|\bail\b|aglio|usturoi|basilic|albahaca|busuioc|cipolla|oignon|cebolla|ceapa|picant|herbes|ierburi|oregano|datterin|cherry|cilieg"),
    "tuna_in_oil":    dict(target=("kg", 0.08, 0.24), require=r"oliva|olive|masline", avoid=r"picant|limon|citron|limone|lamaie|ventresca|ventre|bonito|filet|trancio|tranche|vetro|verre|borcan|frasco|tarro"),
    "whole_milk":     dict(target=("l", 1, 1), avoid=r"calcio|omega|crecimiento|croissance|crescita|infantil|bebe|bimbi|copii"),
    "plain_yogurt":   dict(target=("kg", 0.125, 0.5), avoid=r"grieg|grec|greco|greek|grecesc|skyr|azucarad|sucre|zuccherat|indulcit|bebible|boire|da bere|de baut|cabra|chevre|capra|oveja|brebis|pecora|oaie|bifidus|velout"),
    "butter":         dict(target=("kg", 0.25, 0.25), avoid=r"con sal|\bsalad|\bsale\b|demi.sel|salat[oa]|\bsarat|facil de untar|tartinable|spalmabil|tartinabil|ligera|leger|legger|aroma|\bajo\b|\bail\b|aglio|herbes|chiarificat"),
    "corn_flakes":    dict(target=("kg", 0.5, 0.5), avoid=r"chocolat|ciocolat|cioccolat|miel|miere|honey|azucarad|glac|frosted|sucre|zuccherat|fruits|frutas|fructe"),
    "mineral_water":  dict(target=("l", 1.5, 9), single_only=True, avoid=r"carbogaz|con gas|gaseosa|gazeuse|petillant|frizzante|effervescente|carbogazoas|sparkling|\bgas\b|garrafa|bidon|dispens|grifo|sport|tapon|infantil|bebe|kids|copii"),
    "chicken_breast": dict(target=("kg", 0.5, 0.5), avoid=r"adob|ajillo|halal|corral|campero|fermier|label rouge|ruspante|picant|straccetti|bocconcini|cubos|cuburi|emince|aiguillet"),
    "tomato":         dict(target=("kg", 1, 1), produce=True, avoid=r"cherry|cerise|cilieg|datter|cocktail|coctel|kumato|\braf\b|corazon|coeur|cuore|inima|ancien|pachino"),
    "potato":         dict(target=("kg", 1, 2), produce=True, avoid=r"guarnicion|grenaille|novelle|nueva|baby|mini|rouge|roja|rosse|violet|dolce|microond"),
    "apple":          dict(target=("kg", 1, 1), produce=True),
    "banana":         dict(target=("kg", 1, 1), produce=True, avoid=r"baby|mini"),
    "eggs":           dict(target=("unit", 10, 10), avoid=r"camper|plein air|aperto|aer liber|omega|label rouge|fermier|\btara\b"),
    "sliced_bread":   dict(target=("kg", 0.5, 0.5), avoid=r"sin gluten|sans gluten|senza glutine|fara gluten|gluten free|sin corteza|sans croute|senza crosta|fara coaja|semillas|cereal|graines|\bsemi\b|seminte|multicer|avena|centeno|seigle|secara|brioch|leche|\blait\b|latte|rustic|maiz|american|burger|xxl"),
    "coca_cola":      dict(target=("l", 1.5, 1.5), single_only=True, brand=r"coca.?cola", avoid=r"zero|cafeina|cafeine|caffeina|cofeina|scaf|cherry|vanil|limon|lemon|lime"),
    "nutella":        dict(target=("kg", 0.4, 0.4), brand=r"nutella", avoid=r"plant|vegan|\bgo\b|pack|barquette|portion"),
}

# Known gaps explained by HOW the data was collected (not by the market).
KNOWN_GAPS = {
    ("nutella", "it"): "No hazelnut-cocoa spread in the Italian extract. Collection artefact, NOT unavailability: "
                       "it/main_it.py keeps only the majority category of each search ('biscotti_classici' for "
                       "'nutella'), so the spread jars were filtered out before saving. Needs re-collection.",
}
