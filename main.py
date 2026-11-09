from curl_cffi import requests
import re
import json
import time
from tqdm import tqdm
from bs4 import BeautifulSoup


def extract_products_from_page(page_text) -> list[dict]:
    """
    Devuelve toda la información de los productos, sin necesidad de tener que mirar la página individual de cada uno.

    Para hacerlo de una sentada, se mira la información de los productos que hay en el código javascrit de la página del catálogo.
    """

    pattern = r'<script type="text/javascript">window\["impressions"\]=(\[.*\])'
    json_text = re.search(pattern, page_text).group(1)

    products = json.loads(json_text)

    return [{"name": x["item_name"].replace("-", " ").title(), "price": x["price"], "brand": x["item_brand"], "ean": x["item_ean"]} for x in products]


def extract_products_from_catalog(session, catalog_number=20009, url="https://www.carrefour.es/supermercado/la-despensa") -> list[dict]:
    """
    Obtener todos los productos de un catálogo de Carrefour España
    """

    catalog_url = f"{url}/la-despensa/a/cat{catalog_number}/c"

    # We use the curl_cffi requests, which is similar as the normal one but evades cloudflare
    response = requests.get(catalog_url, impersonate="chrome")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Get the number of pages
    _, n_products_per_page, n_products = [int(x.text) for x in soup.find_all("span", class_="pagination__results-item")]

    n_pages = n_products // n_products_per_page

    products = []
    for page in tqdm(range(n_pages), "Fetching products", unit="pág"):
        # GET route of the catalog at the current page
        catalog_url = f"{url}/la-despensa/alimentacion/cat20009/c?offset={page * n_products_per_page}"

        # Fetch the current page
        text = fetch(session, catalog_url)

        # Add products
        products += extract_products_from_page(text)

    return products


def fetch(session, url: str, max_retries=4) -> str:
    """
    Dada una URL, trata de descargar el contenido de una página. Sí la petición de desacarga falla, espera y lo vuelve a intentar.
    """
    for attempt in range(max_retries + 1):
        response = session.get(url)

        # Si no hay error o se alcanzó el límite de intentos, salir del bucle
        if response.status_code not in (429, 503) or attempt == max_retries:
            break

        retry_after = response.headers.get("Retry-After", "")
        wait = int(retry_after) if retry_after.isdigit() else 30 * 2**attempt
        print(f"\n{response.status_code} en {url}, esperando {wait} s")
        time.sleep(wait)

    response.raise_for_status()
    return response.text


if __name__ == "__main__":
    session = requests.Session(impersonate="chrome")

    products = extract_products_from_catalog(session)

    with open("products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=4)
