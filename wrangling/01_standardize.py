"""Step 1 - Standardise the four country files into one common schema.

Reads the raw JSON of es/fr/it/ro (never modifies it) and writes
data/01_standardized.csv with one row per raw record. Nothing is dropped here.
Run:  python wrangling/01_standardize.py
"""
import csv
import json
import re
import subprocess

from config import DATA, ECB_EUR_RON, FALLBACK_COLLECTED, ROOT, SOURCES, norm

NUM = r"(\d+(?:[.,]\d+)?)"
UNIT = r"(kg|kilogrammes?|g|gr|grammes?|mg|l|lt|litri|litro|litros|litres?|litru|cl|dl|ml)"
RE_MULTI = re.compile(rf"(?<![\w.,])(\d+)\s*[x*]\s*{NUM}\s*{UNIT}\b")
RE_ESPACK = re.compile(rf"pack (?:de )?(\d+) [a-z]+ (?:de )?{NUM}\s*{UNIT}\b")
RE_SINGLE = re.compile(rf"(?<![\w.,]){NUM}\s*{UNIT}\b")
RE_COUNT = re.compile(r"(?<![\w.,])(\d+)\s*(ud|uds|unidades|bucati|buc|pezzi|pz|uova|oeufs|pots?)\b")
RE_EGG = re.compile(r"\b(huevos?|oeufs?|uova|oua)\b")
RE_EGG_COUNT = re.compile(r"(?<![\w.,])(\d+)\s*(?:ud|uds|unidades|bucati|buc|pezzi|pz|uova|oeufs|oua)\b|[*x]\s*(\d+)(?!\d)|\b(?:da|de|par)\s+(\d+)\b")
RE_LOOSE = re.compile(r"aprox|granel|sfus|vrac|vrac\b|au kg|al kg")
RE_RO_PROMO = re.compile(r"\d+\s*la pret de\s*\d+|\d+\s*\+\s*\d+\s*gratis|gratis|promo\b|oferta")
TO_BASE = {"kg": ("kg", 1), "kilogramme": ("kg", 1), "kilogrammes": ("kg", 1), "g": ("kg", .001),
           "gr": ("kg", .001), "gramme": ("kg", .001), "grammes": ("kg", .001), "mg": ("kg", 1e-6),
           "l": ("l", 1), "lt": ("l", 1), "litri": ("l", 1), "litro": ("l", 1), "litros": ("l", 1),
           "litre": ("l", 1), "litres": ("l", 1), "litru": ("l", 1), "cl": ("l", .01), "dl": ("l", .1),
           "ml": ("l", .001)}

FIELDS = ["row_id", "country", "source_file", "source_row", "collected_date", "collected_date_source",
          "store", "url", "source_product_id", "ean", "ean_status", "name_raw", "name_norm", "brand_raw",
          "brand_norm", "search_query", "source_category", "pack_count", "unit_size", "unit_size_unit",
          "total_qty", "qty_basis", "size_source", "size_flags", "price_local", "currency", "fx_rate",
          "fx_date", "fx_source", "price_eur", "unit_price_eur", "unit_price_displayed_eur",
          "regular_price_eur", "promo_price_eur", "price_separation", "promo_flag", "promo_label",
          "availability", "collection_flag"]


def ean_status(code):
    if not code:
        return "missing"
    if not (code.isdigit() and len(code) in (8, 12, 13, 14)):
        return "not_a_barcode"
    digits = [int(c) for c in code]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits[:-1])))
    if (10 - total % 10) % 10 != digits[-1]:
        return "invalid_checksum"
    # GS1 prefixes 20-29 (and 02) are retailer-internal codes: valid only inside one country.
    if code.zfill(13)[:1] == "2" or code.zfill(13)[:2] == "02":
        return "internal_code"
    return "valid_gtin"


def to_float(text, country, unit_base):
    """Parse a number. Spanish names lost the decimal comma ('1,5 L' -> '15 L')."""
    restored = False
    if (country == "es" and unit_base[1] == 1 and text.isdigit() and len(text) >= 2
            and not (len(text) == 2 and text.endswith("0"))):
        text, restored = text[0] + "." + text[1:], True
    return float(text.replace(",", ".")), restored


def parse_size(text, country):
    """Return (pack_count, unit_size, unit, total, basis, flags) from free text."""
    t = norm(text)
    flags = []
    if not t:
        return None
    count = RE_COUNT.search(t)
    if RE_EGG.search(t):  # eggs are compared per unit, never per kg
        egg = RE_EGG_COUNT.search(t)
        if egg:
            n = int(next(g for g in egg.groups() if g))
            return n, 1, "unit", n, "unit", flags
        return None
    m = RE_MULTI.search(t) or RE_ESPACK.search(t)
    if m:
        packs, raw, unit = int(m.group(1)), m.group(2), m.group(3)
    else:
        singles = RE_SINGLE.findall(t)
        if singles:
            packs, (raw, unit) = 1, singles[-1]
        elif count:
            n = int(count.group(1))
            return n, 1, "unit", n, "unit", flags
        else:
            return None
    base = TO_BASE[unit]
    size, restored = to_float(raw, country, base)
    if restored:
        flags.append("es_decimal_restored")
    return packs, size, unit, round(packs * size * base[1], 6), base[0], flags


def collected_date(country):
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", SOURCES[country]], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        if out:
            return out, "git_last_commit_of_result_file"
    except Exception:
        pass
    return FALLBACK_COLLECTED[country], "git_last_commit_of_result_file(hardcoded)"


def fr_unit_price(text):
    m = re.match(r"\s*([\d.,]+)\s*€\s*/\s*(\w+)", text or "")
    if not m:
        return None, None
    basis = {"kg": "kg", "kilogramme": "kg", "l": "l", "litre": "l", "u": "unit"}.get(m.group(2).lower())
    return float(m.group(1).replace(",", ".")), basis


def standardise(country, i, r, date, date_src):
    row = dict.fromkeys(FIELDS, "")
    name = r.get("name") or ""
    row.update(row_id=f"{country}-{i:05d}", country=country, source_file=SOURCES[country], source_row=i,
               collected_date=date, collected_date_source=date_src, store=r.get("store", ""),
               url=r.get("url", ""), name_raw=name, name_norm=norm(name), brand_raw=r.get("brand") or "",
               brand_norm=norm((r.get("brand") or "").replace("-", " ")).strip("' "),
               search_query=r.get("search_query", ""), currency="EUR", fx_rate=1, fx_source="",
               price_separation="not_observed", availability="not_observed")
    # --- identifiers
    if country == "es":
        ean, row["source_product_id"] = r["ean"], r["internal_id"]
        row["source_category"] = r["catalog"]
    elif country == "fr":
        ean = r["product_id"] if r["product_id"].isdigit() else ""
        row["source_product_id"] = r["product_id"]
    elif country == "it":
        ean, row["source_product_id"], row["source_category"] = r["ean"], r["ean"], r["category"]
    else:  # ro: Bringo exposes no barcode, only internal ids
        ean, row["source_product_id"] = "", r["product_id"]
        row["currency"] = r["currency"]
    row["ean"], row["ean_status"] = ean, ean_status(ean)
    # --- price and currency
    price = r.get("price")
    price = float(price) if price not in (None, "") else None
    if price is None:
        row["collection_flag"] = "price_missing"  # cannot tell out-of-stock from scrape failure
    else:
        row["price_local"] = round(price, 2)
        if row["currency"] == "RON":
            fx_date = date if date in ECB_EUR_RON else max(d for d in ECB_EUR_RON if d <= date)
            row.update(fx_rate=ECB_EUR_RON[fx_date], fx_date=fx_date, fx_source="ECB euro reference rate")
        row["price_eur"] = round(price / row["fx_rate"], 4)
    # --- package size (structured field first, product name second)
    flags, size, src = [], None, ""
    if r.get("pack_size"):
        size, src = parse_size(r["pack_size"], country), "pack_size_field"
    if size is None:
        size, src = parse_size(name, country), "name"
    shown, shown_basis = fr_unit_price(r.get("unit_price")) if country == "fr" else (None, None)
    if shown is not None:
        row["unit_price_displayed_eur"] = shown
    if size is None and shown and price and shown_basis:
        size, src = (1, round(price / shown, 4), shown_basis, round(price / shown, 4), shown_basis, []), \
                    "derived_from_displayed_unit_price"
    if size is None:
        row["size_source"] = "not_found"
    else:
        packs, unit_size, unit, total, basis, f = size
        flags += f
        row.update(pack_count=packs, unit_size=unit_size, unit_size_unit=unit, total_qty=total,
                   qty_basis=basis, size_source=src)
        if price is not None and total:
            row["unit_price_eur"] = round(row["price_eur"] / total, 4)
            # FR: the unit price shown by the retailer wins over our parsed size
            # (multipacks such as "4 pots" of 125 g are often under-described).
            if shown and shown_basis and src != "derived_from_displayed_unit_price" and (
                    shown_basis != basis or abs(row["unit_price_eur"] - shown) / shown > 0.05):
                flags.append("size_overridden_by_displayed_unit_price")
                row.update(total_qty=round(price / shown, 4), qty_basis=shown_basis, unit_price_eur=shown,
                           size_source="derived_from_displayed_unit_price")
    if RE_LOOSE.search(row["name_norm"]):
        flags.append("variable_weight")
    row["size_flags"] = "|".join(flags)
    # --- promotion (flag only; promotional vs regular price was not collected)
    if country == "es":
        promo = r.get("promotion")
        row["promo_flag"] = "yes" if promo else "no"
        row["promo_label"] = re.sub(r"^.*/[^_/]*_", "", promo) if promo else ""
    elif country == "ro" and RE_RO_PROMO.search(row["name_norm"]):
        row["promo_flag"], row["promo_label"] = "yes", RE_RO_PROMO.search(row["name_norm"]).group(0)
    else:
        row["promo_flag"] = "not_observed"
    return row


def main():
    DATA.mkdir(exist_ok=True)
    rows = []
    for country, path in SOURCES.items():
        date, date_src = collected_date(country)
        records = json.loads((ROOT / path).read_text(encoding="utf-8"))
        rows += [standardise(country, i, r, date, date_src) for i, r in enumerate(records)]
        print(f"{country}: {len(records)} rows, collected_date={date}")
    with open(DATA / "01_standardized.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"-> {DATA / '01_standardized.csv'} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
