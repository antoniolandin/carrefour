import argparse
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin


BASKET_PATH = Path(__file__).resolve().parents[1] / "cesta.csv"
SEARCH_URL = "https://www.carrefour.fr/s"
CARD_SELECTOR = "article.product-list-card-plp-grid-new"


def read_french_terms():
    with BASKET_PATH.open(encoding="utf-8-sig", newline="") as basket:
        return [row["fr"].strip() for row in csv.DictReader(basket) if row["fr"].strip()]


def build_search_url(term):
    return f"{SEARCH_URL}?{urlencode({'q': term})}"


def extract_products(html, search_query):
    from bs4 import BeautifulSoup

    page = BeautifulSoup(html, "html.parser")
    cards = page.select(CARD_SELECTOR)
    if not cards:
        raise ValueError("No product card found in the saved results page.")
    return [extract_product(card, search_query) for card in cards]


def extract_product(card, search_query):
    title_link = card.select_one("a.product-list-card-plp-grid-new__title-container[href]")
    if title_link is None:
        raise ValueError(f"Product card {card.get('data-testid')} has no product link.")

    price = None
    parts = card.select(".product-price .product-price__content")
    if len(parts) == 3 and parts[2].get_text(strip=True) == "€":
        euros = parts[0].get_text(strip=True)
        cents = re.fullmatch(r"(?:0?,)?([0-9]{2})", parts[1].get_text(strip=True))
        if euros.isdecimal() and cents:
            price = int(euros) + int(cents[1]) / 100

    return {
        "search_query": search_query,
        "product_id": card.get("data-testid"),
        "url": urljoin(SEARCH_URL, title_link["href"]),
        "name": card_text(card, ".product-card-title__text"),
        "brand": card_text(card, ".product-list-card-plp-grid-new__brand"),
        "pack_size": card_text(card, ".product-list-card-plp-grid-new__meta--shimzone"),
        "price": price,
        "unit_price": card_text(card, ".product-list-card-plp-grid-new__per-unit-label"),
    }


def card_text(card, selector):
    element = card.select_one(selector)
    return element.get_text(" ", strip=True) if element else None


def scrape_basket():
    from playwright.sync_api import sync_playwright

    terms = read_french_terms()
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_page(locale="fr-FR")
            page.goto(build_search_url(terms[0]), wait_until="domcontentloaded")
            store = input(
                "Select your Drive store in the browser, then type its name here: "
            ).strip()
            if not store:
                raise ValueError("Enter the Drive store name to label the prices.")

            for term in terms:
                print(f"Collecting {term}...", flush=True)
                page.goto(build_search_url(term), wait_until="domcontentloaded")
                cards = page.locator(CARD_SELECTOR)
                cards.first.wait_for()
                while page.locator(".pagination__button-wrap button:visible").count():
                    count = cards.count()
                    page.locator(".pagination__button-wrap button:visible").click()
                    cards.nth(count).wait_for()
                products = extract_products(page.content(), term)
                unique_products = {}
                for product in products:
                    product["store"] = store
                    unique_products.setdefault(product["product_id"] or product["url"], product)
                results.extend(unique_products.values())
        finally:
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, help="Read all products from a saved results page.")
    parser.add_argument("--query", help="Search term used to find these products.")
    parser.add_argument("--output", type=Path, help="Save the results to this JSON file.")
    parser.add_argument("--live", action="store_true", help="Search Carrefour for the full basket.")
    args = parser.parse_args()
    if args.live and args.html:
        parser.error("Choose either --live or --html.")
    if not args.live and args.html is None:
        for term in read_french_terms():
            print(f"{term}: {build_search_url(term)}")
        return

    try:
        if args.live:
            products = scrape_basket()
            if args.output is None:
                args.output = Path(__file__).with_name("products_fr.json")
        else:
            products = extract_products(args.html.read_text(encoding="utf-8"), args.query)
        results = json.dumps(products, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(results, encoding="utf-8")
            print(f"Saved {len(products)} product cards to {args.output}")
        else:
            print(results, end="")
    except (OSError, ValueError, ModuleNotFoundError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
