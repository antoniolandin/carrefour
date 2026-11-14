"""Step 2 - Assign each standardised row to a basket item and set noise aside.

Input : data/01_standardized.csv
Output: data/02_basket_products.csv   rows kept (one per product and country)
        data/02_excluded.csv          rows dropped, each with an explicit reason
        data/02_coverage.csv          basket item x country counts
Run:  python wrangling/02_filter_basket.py
"""
import csv
import re
import statistics
from collections import Counter

from config import BASKET, DATA, ROOT, norm

COUNTRIES = ("es", "fr", "it", "ro")


def load_queries():
    """Map (country, normalised search term) -> basket id, from cesta.csv row order."""
    with open(ROOT / "cesta.csv", encoding="utf-8") as f:
        return {(c, norm(row[c])): i for i, row in enumerate(csv.DictReader(f), 1) for c in COUNTRIES}


def classify(row, queries):
    """Return (basket rule or None, reason, flag)."""
    name, country = row["name_norm"], row["country"]
    hits, vetoed = [], []
    for rule in BASKET:
        included = re.search(rule["inc"][country], name) or (
            country == "it" and row["source_category"] in rule.get("it_cat", ()))
        if not included:
            continue
        veto = re.search(rule["exc"], name)
        (vetoed if veto else hits).append((rule, veto.group(0) if veto else ""))
    if not hits:
        if vetoed:
            return None, f"excluded_by_rule:{vetoed[0][0]['item']}:'{vetoed[0][1]}'", ""
        return None, "no_basket_family_match", ""
    own = queries.get((country, norm(row["search_query"])))
    for rule, _ in hits:
        if rule["id"] == own:
            return rule, "", "" if len(hits) == 1 else "multiple_rule_hits"
    flag = "found_under_other_query" if own else ""
    if len(hits) > 1:
        flag = (flag + "|multiple_rule_hits").strip("|")
    return hits[0][0], "", flag


def main():
    queries = load_queries()
    with open(DATA / "01_standardized.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    kept, excluded, seen = [], [], {}
    for row in rows:
        rule, reason, flag = classify(row, queries)
        if rule is None:
            excluded.append({**row, "exclusion_reason": reason})
            continue
        if row["collection_flag"] == "price_missing":
            excluded.append({**row, "exclusion_reason": f"price_missing:{rule['item']}"})
            continue
        key = (row["country"], row["ean"] or row["source_product_id"] or row["url"])
        if key in seen:
            excluded.append({**row, "exclusion_reason": f"duplicate_of:{seen[key]}"})
            continue
        seen[key] = row["row_id"]
        kept.append({**row, "basket_id": rule["id"], "basket_item": rule["item"], "assignment_flag": flag})

    def write(name, data, extra):
        fields = list(rows[0].keys()) + extra
        with open(DATA / name, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fields)
            w.writeheader()
            w.writerows(data)

    # Flag unit prices far from the median of their basket item and country (review aid, nothing is dropped).
    groups = {}
    for r in kept:
        if r["unit_price_eur"]:
            groups.setdefault((r["basket_item"], r["country"], r["qty_basis"]), []).append(float(r["unit_price_eur"]))
    for r in kept:
        values = groups.get((r["basket_item"], r["country"], r["qty_basis"]), [])
        r["unit_price_outlier"] = ""
        if len(values) >= 5 and r["unit_price_eur"]:
            median = statistics.median(values)
            if not median / 4 <= float(r["unit_price_eur"]) <= median * 4:
                r["unit_price_outlier"] = "yes"
    kept.sort(key=lambda r: (r["basket_id"], r["country"], r["name_norm"]))
    write("02_basket_products.csv", kept, ["basket_id", "basket_item", "assignment_flag", "unit_price_outlier"])
    write("02_excluded.csv", excluded, ["exclusion_reason"])

    counts = Counter((r["basket_item"], r["country"]) for r in kept)
    sized = Counter((r["basket_item"], r["country"]) for r in kept if r["unit_price_eur"])
    with open(DATA / "02_coverage.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["basket_id", "basket_item"] + [f"{c}_n" for c in COUNTRIES] + [f"{c}_with_unit_price" for c in COUNTRIES])
        print(f"{'item':16}" + "".join(f"{c:>6}" for c in COUNTRIES))
        for rule in BASKET:
            n = [counts[(rule["item"], c)] for c in COUNTRIES]
            w.writerow([rule["id"], rule["item"]] + n + [sized[(rule["item"], c)] for c in COUNTRIES])
            print(f"{rule['item']:16}" + "".join(f"{x:>6}" for x in n))
    print(f"kept {len(kept)} | excluded {len(excluded)} of {len(rows)}")
    for reason, n in Counter(r["exclusion_reason"].split(":")[0] for r in excluded).most_common():
        print(f"  {reason}: {n}")


if __name__ == "__main__":
    main()
