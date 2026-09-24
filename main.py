from curl_cffi import requests
import re
import json
from tqdm import tqdm


def get_catalog_urls(url: str, catalog_number: int) -> list[str]:
    # GET route of the catalog from carrefour spain
    catalog_url = f"{url}/la-despensa/a/cat{catalog_number}/c"

    # We use the curl_cffi requests, which is similar as the normal one but evades cloudflare
    response = requests.get(catalog_url, impersonate="chrome")
    assert response.status_code == 200
    text = response.text

    # First we need to know how many products are in the catalog
    # For that we capture the "1 - 24 de 1008 productos" text using a regular expression
    print("Searching for the number of products...")
    regex = r"(?:<[^>]+>)?\d+(?:<[^>]+>)?\s*-\s*(?:<[^>]+>)?\d+(?:<[^>]+>)?\s+de\s+(?:<[^>]+>)?(\d+)(?:<[^>]+>)?\s+productos"
    number_products = int(re.search(regex, text).group(1))
    print(f"The're {number_products} products")

    # Now we need to know how many pages has the catalog
    regex = r"Página \d+ de (\d+)"
    page_number = int(re.search(regex, text).group(1))

    # The number of products per page
    number_products_page = number_products // page_number

    # First step is to get the URLs of all the products of the catalog
    products_url = []
    for page in tqdm(range(page_number), "Fetching product names", unit="pág"):
        # GET route of the catalog at the current page
        catalog_url = f"{url}/la-despensa/alimentacion/cat20009/c?offset={
            page * number_products_page
        }"

        # Fetch the current page
        response = requests.get(catalog_url, impersonate="chrome")
        response.raise_for_status()
        text = response.text

        # Find the data in the page
        regex = r"window\[\"impressions\"\]=(\[.*\])"
        json_data = re.search(regex, text).group(1)

        # Convert the json data to a python object
        products = json.loads(json_data)

        # Add all the URLs of the current page
        products_url += [
            f"{url}/{product['item_name']}/"
            + f"R-{product['item_internal_id']}".upper().replace("PROD", "prod")
            + "/p"
            for product in products
        ]

    return products_url


def get_product(product_url: str):
    print(product_url)

    # We use the curl_cffi requests, which is similar as the normal one but evades cloudflare
    response = requests.get(product_url, impersonate="chrome")
    response.raise_for_status()
    if response.status_code == 301:
        print("Not found:", product_url)
        return
    text = response.text

    regex = r"<title>([^>]*)\s\|[^>]*</title>"
    search = re.search(regex, text)
    if not search:
        print("Not found", product_url)
        return

    product_name = search.group(1)

    regex = r"<span class=\"buybox__price\"[^>]*>\s*(\d+(?:\,\d+)?)\s*€\s*</span>"
    product_price = float(re.search(regex, text).group(1).replace(",", "."))

    # Some products have the price per weight
    product_price_per_unit = None
    regex = r"<div class=\"buybox__price-per-unit\"[^>]*>(?:<[^>]+>)*\s*(\d+(?:\,\d+)?)\s*€/kg\s*(?:<[^>]+>)*</div>"
    search = re.search(regex, text)
    if search:
        product_price_per_unit = search.group(1)

    return {
        "name": product_name,
        "price": product_price,
        "price_per_unit": product_price_per_unit,
    }


def get_products(products_url: list[str]) -> list[dict]:
    products = []
    # for url in tqdm(products_url, "Fetching products", unit="product"):
    for url in products_url:
        products.append(get_product(url.strip()))
    return products


def create_catalog_urls_file(url, catalog_number, name="catalog_urls.txt"):
    catalog_urls = get_catalog_urls(url, catalog_number)
    with open(name, "w") as f:
        f.write("\n".join(catalog_urls))


if __name__ == "__main__":
    product_url = "https://www.carrefour.es/supermercado/avena-integral-en-polvo-prozis-400-g/R-prod670294/p"

    # url from Carrefour Spain
    url = "https://www.carrefour.es/supermercado"

    # Catalog 20009 corresponds to the alimentation products catalog
    catalog_number = 20009

    # create_catalog_urls_file(url, catalog_number)

    # catalog_urls = get_catalog_urls(url, catalog_number)
    with open("catalog_urls.txt", "r") as f:
        catalog_urls = f.readlines()

    products = get_products(catalog_urls)
