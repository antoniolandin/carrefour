"""Step 3 - Representative candidates per basket item, profile and country.

For each of the 22 basket items and each country, proposes up to two profiles:
  private_label : standard Carrefour own-brand product (economy fallback if none)
  leading_brand : the brand best repeated across countries (local leader if none)
Each profile lists the suggested product plus up to 3 alternatives, with a
SUGGESTED label (identical / equivalent / unmatched). Suggestions are aids only:
the reviewer decides in the empty final_* columns. Nothing is merged here.

Input : data/02_basket_products.csv
Output: data/03_candidates.csv, data/03_review_matches.xlsx
Run   : python wrangling/03_generate_candidates.py [--force]
"""
import csv
import math
import re
import sys
from collections import Counter, defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from config import (BASKET, DATA, ROOT, norm, GENERIC_AVOID, KNOWN_GAPS, NOT_A_BRAND, PRIVATE_LABEL, PRIVATE_PREMIUM,
                    PROFILE)

COUNTRIES = ("es", "fr", "it", "ro")
with open(ROOT / "cesta.csv", encoding="utf-8") as _f:
    GENERIC_WORDS = {w for row in csv.DictReader(_f) for term in row.values() for w in norm(term).split()} - {"coca-cola", "nutella"}
TOP_N = 4  # suggested product + 3 alternatives
XLSX = DATA / "03_review_matches.xlsx"
REVIEW_COLS = ["final_choice", "final_label", "final_confidence", "reviewer_notes"]
COLS = ["group_id", "basket_id", "basket_item", "profile", "country", "rank", "role", "name_raw", "brand",
        "pack", "total_qty", "qty_basis", "price_local", "currency", "price_eur", "unit_price_eur",
        "unit_price_unit", "target_format", "size_similarity", "flag_es_decimal_restored",
        "flag_unit_price_outlier", "flag_promotion", "other_flags", "ean", "ean_status", "ean_also_in",
        "score", "suggested_label", "suggested_confidence", "suggestion_reason", "candidate_note",
        *REVIEW_COLS, "url", "row_id"]


def num(value):
    return float(value) if value not in ("", None) else None


def similarity(qty, target):
    """1 = same size, 0 = four times bigger/smaller or unknown."""
    if not qty or not target:
        return 0.0
    return max(0.0, 1 - abs(math.log2(qty / target)) / 2)


def prepare(rows):
    """Add private-label flag, brand key and format/specification scores to every row."""
    by_item = defaultdict(list)
    for r in rows:
        by_item[r["basket_item"]].append(r)
    for item, group in by_item.items():
        prof = PROFILE[item]
        # brand vocabulary from the countries that have a brand field
        vocab = {r["brand_norm"] for r in group if r["brand_norm"] not in NOT_A_BRAND
                 and not re.search(PRIVATE_LABEL, r["brand_norm"]) and len(r["brand_norm"]) >= 3}
        vocab -= GENERIC_WORDS  # e.g. 'pollo', 'riso': category words stored in the brand field
        canon = {b: min((v for v in vocab if b == v or (len(v) >= 4 and re.search(rf"\b{re.escape(v)}\b", b))), key=len)
                 for b in vocab}
        for r in group:
            text = f"{r['brand_norm']} {r['name_norm']}"
            r["is_pl"] = bool(re.search(PRIVATE_LABEL, text))
            tier_text = r["brand_norm"] or " ".join(re.findall(r"carrefour \w+|reflets de france|terre d.?italia", r["name_norm"]))
            r["pl_premium"] = bool(re.search(PRIVATE_PREMIUM, tier_text))
            if prof.get("brand"):
                r["brand_key"] = item.replace("_", "-") if re.search(prof["brand"], text) else ""
            elif r["is_pl"]:
                r["brand_key"] = ""
            elif r["brand_norm"] in canon:
                r["brand_key"] = canon[r["brand_norm"]]
            else:  # no brand field (Romania): look for a known brand inside the name
                found = [b for b in set(canon.values()) if len(b) >= 4 and re.search(rf"\b{re.escape(b)}\b", r["name_norm"])]
                r["brand_key"] = max(found, key=len) if found else ""
            # format similarity against the standard format of the item
            basis, unit_target, total_target = prof["target"]
            total, packs = num(r["total_qty"]), num(r["pack_count"]) or 1
            derived = r["size_source"] == "derived_from_displayed_unit_price"
            if total and r["qty_basis"] == basis:
                sims = [similarity(total / packs, unit_target)]
                # single_only items (bottled drinks) are compared per bottle; the pack-total target is
                # used for the other items, or when the pack structure is unknown (size derived in FR)
                if derived or not prof.get("single_only"):
                    sims.append(similarity(total, total_target))
                r["size_sim"] = round(max(sims), 2)
            else:
                r["size_sim"] = 0.0
            issues = []
            if re.search(GENERIC_AVOID, r["name_norm"]) or re.search(GENERIC_AVOID, r["brand_norm"]):
                issues.append("non-standard variant (organic/free-from/light...)")
            if prof.get("avoid") and re.search(prof["avoid"], r["name_norm"]):
                issues.append(f"non-standard variant ('{re.search(prof['avoid'], r['name_norm']).group(0)}')")
            if prof.get("require") and not re.search(prof["require"], r["name_norm"]):
                issues.append("required specification not found in name")
            r["spec_issues"] = issues
            r["standard"] = not issues and r["size_sim"] >= 0.5 and bool(r["unit_price_eur"])
    return by_item


def score(r, profile, shared):
    tier = 1.0
    if profile == "private_label" and r["is_pl"] and r["pl_premium"]:
        tier = 0.6
    s = 0.5 * r["size_sim"] + 0.3 * (0 if r["spec_issues"] else 1) + 0.2 * tier
    if shared.get(r["row_id"]) and r["standard"] and tier == 1.0:
        s += 0.15  # same barcode sold in another country: best anchor for an identical match
    if r["unit_price_outlier"] == "yes":
        s -= 0.25
    if "es_decimal_restored" in r["size_flags"]:
        s -= 0.05
    if r["promo_flag"] == "yes":
        s -= 0.05
    if not r["unit_price_eur"]:
        s *= 0.3
    return round(max(s, 0), 3)


def suggest(r, shared, by_id):
    """Suggested label, confidence and reason for one candidate (aid for the reviewer)."""
    others = shared.get(r["row_id"], [])
    if others:
        sizes = [(by_id[o]["country"], num(by_id[o]["total_qty"])) for o in others]
        mine = num(r["total_qty"])
        where = ", ".join(sorted({c.upper() for c, _ in sizes}))
        if mine and all(q and abs(q - mine) / mine <= 0.05 for _, q in sizes):
            return "identical", "high", f"same barcode and same parsed format as {where}"
        if mine and any(q and abs(q - mine) / mine > 0.05 for _, q in sizes):
            return "equivalent", "medium", f"same barcode as {where} but parsed format differs - verify pack size"
        return "identical", "medium", f"same barcode as {where}; format could not be verified on both sides"
    if not r["unit_price_eur"]:
        return "unmatched", "low", "package size not found: unit price not comparable"
    if r["spec_issues"]:
        return "unmatched", "low", "; ".join(r["spec_issues"])
    if r["size_sim"] < 0.5:
        return "unmatched", "low", "format too far from the standard format"
    alerts = r["unit_price_outlier"] == "yes" or "es_decimal_restored" in r["size_flags"]
    conf = "high" if r["size_sim"] >= 0.85 and not alerts else "medium"
    reason = "same basket function, standard variant, comparable format"
    if r["country"] == "ro":
        conf, reason = ("medium" if conf == "high" else conf), reason + "; RO has no barcode (cannot be identical)"
    if alerts:
        reason += "; check alert flags"
    return "equivalent", conf, reason


def pack_text(r):
    if not r["total_qty"]:
        return ""
    if r["size_source"] == "derived_from_displayed_unit_price":
        return f"{float(r['total_qty']):g} {r['qty_basis']} (from shown unit price)"
    size = f"{float(r['unit_size']):g} {r['unit_size_unit']}"
    return f"{r['pack_count']} x {size}" if num(r["pack_count"]) and float(r["pack_count"]) > 1 else size


def line(rule, profile, country, rank, r, shared, by_id, note):
    basis, unit_t, total_t = PROFILE[rule["item"]]["target"]
    target = f"{unit_t:g} {basis}" + (f" (or {total_t:g} {basis} pack)" if total_t != unit_t else "")
    out = dict.fromkeys(COLS, "")
    out.update(group_id=f"{rule['id']:02d}_{rule['item']}|{profile}", basket_id=rule["id"], basket_item=rule["item"],
               profile=profile, country=country, rank=rank, target_format=target, candidate_note=note)
    if r is None:
        out.update(role="no_candidate", rank="", suggested_label="unmatched", suggested_confidence="high")
        return out
    label, conf, reason = suggest(r, shared, by_id)
    other = [f for f in (r["size_flags"].split("|") + r["assignment_flag"].split("|"))
             if f and f != "es_decimal_restored"]
    out.update(role="suggested" if rank == 1 else "alternative", name_raw=r["name_raw"],
               brand=(r["brand_raw"] or r["brand_key"]) + (" [own brand]" if r["is_pl"] else ""),
               pack=pack_text(r), total_qty=num(r["total_qty"]), qty_basis=r["qty_basis"],
               price_local=num(r["price_local"]), currency=r["currency"], price_eur=num(r["price_eur"]),
               unit_price_eur=num(r["unit_price_eur"]),
               unit_price_unit=f"EUR/{r['qty_basis']}" if r["unit_price_eur"] else "", size_similarity=r["size_sim"],
               flag_es_decimal_restored="yes" if "es_decimal_restored" in r["size_flags"] else "",
               flag_unit_price_outlier=r["unit_price_outlier"],
               flag_promotion=(r["promo_label"] or "yes") if r["promo_flag"] == "yes" else
               ("not_observed" if r["promo_flag"] == "not_observed" else ""),
               other_flags="|".join(other), ean=r["ean"], ean_status=r["ean_status"],
               ean_also_in=", ".join(sorted({by_id[o]["country"].upper() for o in shared.get(r["row_id"], [])})),
               score=r["_score"], suggested_label=label, suggested_confidence=conf, suggestion_reason=reason,
               url=r["url"], row_id=r["row_id"])
    return out


def build(rows):
    by_item = prepare(rows)
    by_id = {r["row_id"]: r for r in rows}
    # barcodes present in more than one country (only real GTINs count)
    by_ean = defaultdict(list)
    for r in rows:
        if r["ean_status"] == "valid_gtin":
            by_ean[r["ean"]].append(r)
    shared = {r["row_id"]: [o["row_id"] for o in group if o["country"] != r["country"]]
              for group in by_ean.values() if len({g["country"] for g in group}) > 1 for r in group}

    out = []
    for rule in BASKET:
        item, prof = rule["item"], PROFILE[rule["item"]]
        group = by_item.get(item, [])
        # cross-country ranking of brands for this item
        presence, standard, volume = defaultdict(set), defaultdict(set), Counter()
        for r in group:
            if r["brand_key"]:
                presence[r["brand_key"]].add(r["country"])
                volume[r["brand_key"]] += 1
                if r["standard"]:
                    standard[r["brand_key"]].add(r["country"])
        # brands that sell the STANDARD variant in most countries come first
        ranking = sorted(presence, key=lambda b: (-len(standard[b]), -len(presence[b]), -volume[b], b))
        for profile in ("private_label", "leading_brand"):
            if profile == "leading_brand" and prof.get("produce"):
                continue  # unbranded fresh produce: a brand profile is not meaningful
            for country in COUNTRIES:
                local = [r for r in group if r["country"] == country]
                gap = KNOWN_GAPS.get((item, country))
                if not local:
                    note = gap or ("No product of this family in the collected data. Availability was not observed, "
                                   "so 'not sold' cannot be told apart from 'not collected'.")
                    out.append(line(rule, profile, country, "", None, shared, by_id, note))
                    continue
                notes = {}
                if profile == "private_label":
                    if prof.get("brand"):
                        out.append(line(rule, profile, country, "", None, shared, by_id,
                                        "Brand-defined basket item: own-brand equivalents were not collected "
                                        "(the search term was the brand name)."))
                        continue
                    pool = [r for r in local if r["is_pl"]]
                    if len(pool) < TOP_N:  # economy fallback: cheapest standard products of other brands
                        cheap = sorted((r for r in local if r["standard"] and not r["is_pl"]),
                                       key=lambda r: float(r["unit_price_eur"]))[:TOP_N - len(pool)]
                        notes = {r["row_id"]: "economy fallback: not a Carrefour own brand, cheapest standard product" for r in cheap}
                        pool = pool + cheap
                else:
                    local_brands = sorted((b for b in ranking if country in presence[b]),
                                          key=lambda b: (country not in standard[b], ranking.index(b)))
                    if not local_brands:
                        pool = [r for r in local if not r["is_pl"]]
                        notes = {r["row_id"]: "brand not available in the data for this country: verify the brand by hand" for r in pool}
                    else:
                        lead = local_brands[0]
                        if len(presence[lead]) == 1:  # no cross-country brand here: local leader by assortment size
                            lead = max(local_brands, key=lambda b: (country in standard[b], sum(r["brand_key"] == b for r in local)))
                        tag = (f"brand '{lead}' present in {', '.join(c.upper() for c in sorted(presence[lead]))}"
                               if len(presence[lead]) > 1 else f"local leader fallback: '{lead}' only found in {country.upper()}")
                        pool = [r for r in local if r["brand_key"] == lead]
                        notes = {r["row_id"]: tag for r in pool}
                        if len(pool) < TOP_N:  # complete the alternatives with the next brands
                            for b in local_brands:
                                if b != lead:
                                    extra = [r for r in local if r["brand_key"] == b]
                                    notes.update({r["row_id"]: f"other brand '{b}' (in {len(presence[b])} countries)" for r in extra})
                                    pool += extra
                for r in pool:
                    r["_score"] = score(r, profile, shared)
                    r["_lead"] = 1 if notes.get(r["row_id"], "").startswith(("other brand", "economy fallback")) else 0
                pool.sort(key=lambda r: (r["_lead"], -r["_score"], num(r["unit_price_eur"]) or 9e9))
                if not pool:
                    out.append(line(rule, profile, country, "", None, shared, by_id,
                                    "No candidate for this profile in the collected data."))
                for rank, r in enumerate(pool[:TOP_N], 1):
                    out.append(line(rule, profile, country, rank, r, shared, by_id, notes.get(r["row_id"], "")))
    for o in out:  # known collection gaps are stated wherever the item has no candidate
        if o["role"] == "no_candidate" and (o["basket_item"], o["country"]) in KNOWN_GAPS:
            o["candidate_note"] = KNOWN_GAPS[(o["basket_item"], o["country"])]
        if o["role"] == "no_candidate":
            o["suggestion_reason"] = o["candidate_note"]
    return out


# ------------------------------------------------------------------ Excel
FILL = {k: PatternFill("solid", fgColor=v) for k, v in dict(
    head="1F3864", pick="E2EFDA", none="F8D7DA", alert="FFD966", review="FFF2CC", group="D9E1F2").items()}
WIDTH = dict(group_id=26, basket_item=15, profile=14, country=8, rank=6, role=12, name_raw=52, brand=24, pack=20,
             total_qty=9, qty_basis=8, price_local=10, currency=8, price_eur=10, unit_price_eur=11,
             unit_price_unit=10, target_format=20, size_similarity=9, flag_es_decimal_restored=12,
             flag_unit_price_outlier=12, flag_promotion=16, other_flags=24, ean=15, ean_status=13, ean_also_in=10,
             score=7, suggested_label=13, suggested_confidence=11, suggestion_reason=48, candidate_note=48,
             final_choice=11, final_label=13, final_confidence=13, reviewer_notes=40, url=30, row_id=10, basket_id=7)
LEGEND = [
    ("HOW TO REVIEW", ""),
    ("1", "Each group_id is one basket item x profile. Inside it, every country shows a suggested product (rank 1, green) and up to 3 alternatives."),
    ("2", "For each country in the group, put an x in final_choice on the product you accept (the suggestion or an alternative)."),
    ("3", "Set final_label (identical / equivalent / unmatched) and final_confidence on the chosen row. If no product is acceptable, mark the rank-1 row as unmatched."),
    ("4", "Red rows = no candidate. They are already suggested as unmatched; the note says why."),
    ("5", "Do not re-run 03_generate_candidates.py after you start: it refuses to overwrite a file with review marks unless --force is given."),
    ("LABELS", ""),
    ("identical", "Same barcode (valid GTIN) found in another country AND same format. Suggested automatically only on barcode evidence; Romania can never be identical (no barcodes on Bringo)."),
    ("equivalent", "Same basket function and comparable specification/format, different barcode or brand."),
    ("unmatched", "No clear equivalent. Also suggested when the variant is non-standard, the format is far from the standard one, or the size is unknown. Doubtful matches are never merged silently."),
    ("COLUMNS", ""),
    ("profile", "private_label = Carrefour own brand, standard tier preferred (economy fallback if none). leading_brand = brand present in most countries for that item (local leader fallback if none)."),
    ("pack / total_qty / qty_basis", "Standardised size: total quantity in kg, l or units."),
    ("price_eur / unit_price_eur", "Shelf price in EUR and price per kg / l / unit. RON converted at the ECB reference rate of the collection date (see data/01_standardized.csv: fx_rate, fx_date)."),
    ("target_format / size_similarity", "Standard format used for ranking; 1 = same size, 0 = 4x bigger/smaller or unknown."),
    ("flag_es_decimal_restored", "Spanish names lost the decimal comma ('1,5 L' -> '15 L'). Size was reconstructed by rule: verify."),
    ("flag_unit_price_outlier", "Unit price more than 4x away from the median of its basket item and country."),
    ("flag_promotion", "ES: promotion label shown on the product. RO: promotion text found in the name. not_observed: the scraper did not collect promotions (FR, IT, most RO). Regular vs promotional price is NOT separated in any country."),
    ("other_flags", "variable_weight (sold by weight / approx.), size_overridden_by_displayed_unit_price (FR), found_under_other_query."),
    ("ean_also_in", "Countries where the same barcode appears among the basket products."),
    ("score", "Ranking aid only: 0.5 format similarity + 0.3 standard variant + 0.2 tier, +0.15 shared barcode, minus alert penalties."),
    ("LIMITATIONS", ""),
    ("availability", "Not observed in any country: a missing product cannot be classified as out of stock vs. not collected."),
    ("collection date", "Date of the last git commit of each country's result file (ES, IT 2026-11-11; FR, RO 2026-11-13). No timestamp was scraped."),
    ("Italy", "it/main_it.py kept only the majority category of each search. Known effect: no Nutella spread. Possible effects: only fresh milk, only sparkling-water category, few corn flakes."),
    ("Romania", "No brand field and no barcode. Brands are detected only when a brand known from ES/FR/IT appears in the product name; otherwise verify by hand."),
    ("fresh produce", "Tomato, potato, apple and banana have no leading_brand profile (unbranded produce)."),
]


def write_xlsx(lines):
    wb = Workbook()
    ws = wb.active
    ws.title = "review"
    ws.append(COLS)
    for o in lines:
        ws.append([o[c] for c in COLS])
    idx = {c: i + 1 for i, c in enumerate(COLS)}
    for c, i in idx.items():
        cell = ws.cell(1, i)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), FILL["head"]
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = WIDTH.get(c, 12)
    ws.row_dimensions[1].height = 32
    previous = None
    for n, o in enumerate(lines, 2):
        fill = FILL["none"] if o["role"] == "no_candidate" else FILL["pick"] if o["rank"] == 1 else None
        for c, i in idx.items():
            cell = ws.cell(n, i)
            if c in REVIEW_COLS:
                cell.fill = FILL["review"]
            elif c.startswith("flag_") and o[c] not in ("", "not_observed"):
                cell.fill = FILL["alert"]
            elif fill:
                cell.fill = fill
        if (o["group_id"], o["country"]) != previous and o["country"] == COUNTRIES[0]:
            for i in (idx["group_id"], idx["basket_item"], idx["profile"]):
                ws.cell(n, i).font = Font(bold=True)
        previous = (o["group_id"], o["country"])
        for c in ("price_local", "price_eur", "unit_price_eur"):
            ws.cell(n, idx[c]).number_format = "0.00"
    last = len(lines) + 1
    for col, options in (("final_choice", "x"), ("final_label", "identical,equivalent,unmatched"),
                         ("final_confidence", "high,medium,low")):
        dv = DataValidation(type="list", formula1=f'"{options}"', allow_blank=True)
        ws.add_data_validation(dv)
        letter = get_column_letter(idx[col])
        dv.add(f"{letter}2:{letter}{last}")
    ws.freeze_panes = ws.cell(2, idx["name_raw"] + 1)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLS))}{last}"

    # summary: one line per group, suggested product per country
    sm = wb.create_sheet("summary")
    head = ["basket_id", "basket_item", "profile"]
    for c in COUNTRIES:
        head += [f"{c}_suggested", f"{c}_unit_price", f"{c}_label"]
    sm.append(head)
    groups = defaultdict(dict)
    for o in lines:
        if o["rank"] == 1 or o["role"] == "no_candidate":
            groups[(o["basket_id"], o["basket_item"], o["profile"])][o["country"]] = o
    for (bid, item, profile), per in groups.items():
        row = [bid, item, profile]
        for c in COUNTRIES:
            o = per.get(c)
            row += [o["name_raw"] or "(no candidate)", o["unit_price_eur"], o["suggested_label"]] if o else ["", "", ""]
        sm.append(row)
    for i, h in enumerate(head, 1):
        cell = sm.cell(1, i)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), FILL["head"]
        sm.column_dimensions[get_column_letter(i)].width = 44 if h.endswith("suggested") else 14
    for row in sm.iter_rows(min_row=2):
        for cell in row:
            if cell.value == "unmatched":
                cell.fill = FILL["none"]
            elif cell.value == "identical":
                cell.fill = FILL["pick"]
            if isinstance(cell.value, float):
                cell.number_format = "0.00"
    sm.freeze_panes = "D2"

    lg = wb.create_sheet("legend")
    for key, text in LEGEND:
        lg.append([key, text])
        if not text:
            lg.cell(lg.max_row, 1).font = Font(bold=True, color="FFFFFF")
            lg.cell(lg.max_row, 1).fill = lg.cell(lg.max_row, 2).fill = FILL["head"]
        lg.cell(lg.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
    lg.column_dimensions["A"].width, lg.column_dimensions["B"].width = 30, 120
    wb.save(XLSX)


def has_review_marks():
    if not XLSX.exists():
        return False
    ws = load_workbook(XLSX, read_only=True)["review"]
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    cols = [header.index(c) for c in REVIEW_COLS if c in header]
    return any(row[i] not in (None, "") for row in ws.iter_rows(min_row=2, values_only=True) for i in cols)


def main():
    if "--force" not in sys.argv and has_review_marks():
        sys.exit(f"{XLSX.name} already contains review marks. Rename it or run with --force to overwrite.")
    with open(DATA / "02_basket_products.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    lines = build(rows)
    with open(DATA / "03_candidates.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, COLS)
        writer.writeheader()
        writer.writerows(lines)
    write_xlsx(lines)
    picks = [o for o in lines if o["rank"] == 1 or o["role"] == "no_candidate"]
    print(f"{len(lines)} candidate rows, {len(picks)} item x profile x country cells")
    print("suggested labels (rank 1):", dict(Counter(o["suggested_label"] for o in picks)))
    print(f"-> {XLSX}")


if __name__ == "__main__":
    main()
