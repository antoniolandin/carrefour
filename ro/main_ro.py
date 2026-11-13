import argparse
import csv
import json
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup


BASKET = Path(__file__).resolve().parents[1] / "cesta.csv"
SEARCH = "https://www.bringo.ro/ro/search/carrefour_orhideea"
# Romanian search terms follow the row order of the shared basket.
TERMS = (
    "spaghetti", "orez", "ulei de măsline", "făină de grâu", "zahăr alb",
    "cafea măcinată", "pulpă de roșii", "ton în ulei", "lapte integral",
    "iaurt natural", "unt nesărat", "fulgi de porumb", "apă minerală",
    "piept de pui", "roșii", "cartofi", "mere", "banane", "ouă",
    "pâine toast", "coca-cola", "nutella",
)


def read_page(html, term):
    soup = BeautifulSoup(html, "html.parser")
    products = []
    for card in soup.select(".box-product[data-cnstrc-item-id]"):
        link = card.select_one("a.bringo-product-name[href]")
        if link is None:
            continue
        url = urljoin(SEARCH, link["href"])
        if not urlsplit(url).path.startswith("/ro/carrefour_orhideea/products/"):
            raise ValueError(f"Unexpected store in results for {term!r}.")
        price = card.get("data-cnstrc-item-price")
        products.append({
            "search_query": term,
            "product_id": card["data-cnstrc-item-id"],
            "name": link.get_text(" ", strip=True),
            "price": float(price) if price else None,
            "currency": "RON",
            "store": "Carrefour Orhideea, Bucharest",
            "url": url,
        })
    if not products:
        raise ValueError(f"No product cards found for {term!r}.")
    next_link = soup.select_one('a[rel="next"][href]')
    return products, urljoin(SEARCH, next_link["href"]) if next_link else None


def scrape(terms):
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            page = browser.new_page(locale="ro-RO")
            for term in terms:
                print(f"Collecting {term}...", flush=True)
                url = f"{SEARCH}?{urlencode({'criteria[search][value]': term})}"
                visited = set()
                products = {}
                while url:
                    if url in visited or urlsplit(url)._replace(query="", fragment="").geturl() != SEARCH:
                        raise ValueError(f"Unexpected pagination URL for {term!r}.")
                    visited.add(url)
                    response = page.goto(url, wait_until="domcontentloaded")
                    if response is None or not response.ok:
                        status = response.status if response else "no response"
                        raise ValueError(f"Bringo returned {status} for {term!r}.")
                    batch, url = read_page(page.content(), term)
                    for product in batch:
                        products.setdefault(product["product_id"], product)
                results.extend(products.values())
        finally:
            browser.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--html", type=Path, help="Read the saved spaghetti results.")
    mode.add_argument("--test", action="store_true", help="Run one live spaghetti search.")
    args = parser.parse_args()
    try:
        if args.html:
            products, _ = read_page(args.html.read_text(encoding="utf-8"), TERMS[0])
        elif args.test:
            products = scrape(TERMS[:1])
        else:
            with BASKET.open(encoding="utf-8-sig", newline="") as basket:
                rows = list(csv.DictReader(basket))
            if len(rows) != len(TERMS):
                raise ValueError("The basket and Romanian search terms differ in length.")
            products = scrape(TERMS)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    data = json.dumps(products, ensure_ascii=False, indent=2)
    if args.html or args.test:
        print(data)
    else:
        output = Path(__file__).with_name("products_ro.json")
        output.write_text(data + "\n", encoding="utf-8")
        print(f"Saved {len(products)} products to {output}")


if __name__ == "__main__":
    main()
