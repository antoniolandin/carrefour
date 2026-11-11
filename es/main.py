from curl_cffi import requests
import re
import json
import math
import time
from pathlib import Path
from tqdm import tqdm
from bs4 import BeautifulSoup

# Cada catálogo descargado se guarda aquí en su propio fichero
CATALOGS_DIR = Path("resultados/catalogos")


def extract_products_from_page(page_text) -> list[dict]:
    """
    Devuelve toda la información de los productos, sin necesidad de tener que mirar la página individual de cada uno.

    Para hacerlo de una sentada, se mira la información de los productos que hay en el código javascrit de la página del catálogo.
    """

    pattern = r'<script type="text/javascript">window\["impressions"\]=(\[.*\])'
    json_text = re.search(pattern, page_text).group(1)

    products = json.loads(json_text)

    return [
        {
            "name": x["item_name"].replace("-", " ").title(),
            "price": x.get("price"),
            "brand": x.get("item_brand"),
            "ean": x.get("item_ean"),
            "item_id": x.get("item_id"),
            "internal_id": x.get("item_internal_id"),
            "category": x.get("item_category"),
            "promotion": x.get("coupon"),
        }
        for x in products
    ]


def extract_products_from_catalog(session, catalog_number, url="https://www.carrefour.es/supermercado/la-despensa") -> list[dict]:
    """
    Obtener todos los productos de un catálogo de Carrefour España
    """

    catalog_url = f"{url}/la-despensa/a/cat{catalog_number}/c"

    # We use the curl_cffi requests, which is similar as the normal one but evades cloudflare
    text = fetch(session, catalog_url)
    soup = BeautifulSoup(text, "html.parser")

    # Get the number of pages
    _, n_products_per_page, n_products = [int(x.text) for x in soup.find_all("span", class_="pagination__results-item")]

    n_pages = math.ceil(n_products / n_products_per_page)

    products = extract_products_from_page(text)

    print(f"Descargando {n_products} productos del catálogo {catalog_number}...")
    for page in tqdm(range(1, n_pages), "Fetching products", unit="pág"):
        # GET route of the catalog at the current page
        page_url = f"{catalog_url}?offset={page * n_products_per_page}"

        # Fetch the current page
        text = fetch(session, page_url)

        # Add products
        products += extract_products_from_page(text)

    for product in products:
        product["catalog"] = f"cat{catalog_number}"

    return products


def extract_catalogs_from_page(page_text) -> dict[int, str]:
    """
    Devuelve los catálogos enlazados desde una página de catálogo (número -> nombre).

    Son los que aparecen en el menú y en las migas de pan: los catálogos padre, los hermanos y los hijos.
    """
    soup = BeautifulSoup(page_text, "html.parser")

    catalogs = {}
    for link in soup.find_all("a", href=re.compile(r"/cat\d+/c")):
        number = int(re.search(r"/cat(\d+)/c", link["href"]).group(1))
        name = link.get_text(" ", strip=True)

        if name:
            catalogs.setdefault(number, name)

    return catalogs


def show_catalogs(session) -> dict[int, str]:
    """
    Muestra los catálogos que aparecen en la página de un catálogo de Carrefour España, con su número y su nombre.
    """
    url = "https://www.carrefour.es/supermercado/la-despensa/la-despensa/a/cat20009/c"
    text = fetch(session, url)
    catalogs = extract_catalogs_from_page(text)

    for number, name in catalogs.items():
        print(f"{number:>10}  {name}")

    return catalogs


class FetchError(Exception):
    """
    Error al descargar una página. Guarda el código HTTP para poder distinguir un bloqueo (403) de otros fallos.
    """

    def __init__(self, status_code: int, url: str, attempts: int):
        super().__init__(f"HTTP {status_code} en {url} tras {attempts} intentos")
        self.status_code = status_code


def fetch(session, url: str, max_retries=4) -> str:
    """
    Dada una URL, trata de descargar el contenido de una página. Sí la petición de desacarga falla, espera y lo vuelve a intentar.
    """
    for attempt in range(max_retries + 1):
        response = session.get(url)

        # Si no hay error o se alcanzó el límite de intentos, salir del bucle
        if response.status_code not in (429, 500, 502, 503, 504) or attempt == max_retries:
            break

        retry_after = response.headers.get("Retry-After", "")
        wait = int(retry_after) if retry_after.isdigit() else 30 * 2**attempt
        print(f"\n{response.status_code} en {url}, esperando {wait} s")
        time.sleep(wait)

    if response.status_code >= 400:
        raise FetchError(response.status_code, url, attempt + 1)

    return response.text


def extract_products_from_catalogs(session, catalogs_file: str) -> list[dict]:
    with open(catalogs_file, "r") as f:
        catalog_numbers = [int(line) for line in f if line.strip()]

    CATALOGS_DIR.mkdir(parents=True, exist_ok=True)

    failed = []
    for catalog_number in catalog_numbers:
        catalog_file = CATALOGS_DIR / f"cat{catalog_number}.json"
        if catalog_file.exists():
            print(f"Catálogo {catalog_number} ya descargado, se salta")
            continue

        try:
            products = extract_products_from_catalog(session, catalog_number)
        except FetchError as e:
            failed.append(catalog_number)
            if e.status_code == 403:
                print(f"\n✗ Bloqueado por Cloudflare en el catálogo {catalog_number}: {e}")
                print("Se para la descarga. Espera un tiempo y vuelve a ejecutar para continuar.")
                break
            print(f"\n✗ Error en el catálogo {catalog_number}: {e}. Se sigue con el siguiente.")
            continue
        except Exception as e:
            failed.append(catalog_number)
            print(f"\n✗ Error en el catálogo {catalog_number}: {type(e).__name__}: {e}. Se sigue con el siguiente.")
            continue

        with open(catalog_file, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=4)

    if failed:
        print(f"\nCatálogos que han fallado: {failed}. Vuelve a ejecutar para reintentarlos.")

    products = []
    for catalog_number in catalog_numbers:
        catalog_file = CATALOGS_DIR / f"cat{catalog_number}.json"
        if catalog_file.exists():
            with open(catalog_file, "r", encoding="utf-8") as f:
                products += json.load(f)

    return products


if __name__ == "__main__":
    session = requests.Session(impersonate="chrome")

    products = extract_products_from_catalogs(session, "catalogos.txt")

    with open("resultados/products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=4)
