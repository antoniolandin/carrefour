from curl_cffi import requests
import re
import json
from tqdm import tqdm
from bs4 import BeautifulSoup


def extract_catalog_product_links(catalog_number=20009, url="https://www.carrefour.es/supermercado/la-despensa") -> list[str]:
    """
    Esta función extrae todos los links de los productos de un catálogo.

    Necesitamos estos links de los productos para así poder ir uno por uno obteniendo su información.
    """
    # GET route of the catalog from carrefour spain
    catalog_url = f"{url}/la-despensa/a/cat{catalog_number}/c"

    # We use the curl_cffi requests, which is similar as the normal one but evades cloudflare
    response = requests.get(catalog_url, impersonate="chrome")
    response.raise_for_status()
    text = response.text

    # First we need to know how many products are in the catalog
    # For that we capture the "1 - 24 de 1008 productos" text using a regular expression
    print("Searching for the number of products...")
    pattern = r"(?:<[^>]+>)?\d+(?:<[^>]+>)?\s*-\s*(?:<[^>]+>)?\d+(?:<[^>]+>)?\s+de\s+(?:<[^>]+>)?(\d+)(?:<[^>]+>)?\s+productos"
    number_products = int(re.search(pattern, text).group(1))
    print(f"The're {number_products} products")

    # Now we need to know how many pages has the catalog
    pattern = r"Página \d+ de (\d+)"
    page_number = int(re.search(pattern, text).group(1))

    # The number of products per page
    number_products_page = number_products // page_number

    # First step is to get the URLs of all the products of the catalog
    products_url = []
    for page in tqdm(range(page_number), "Fetching product links", unit="pág"):
        # GET route of the catalog at the current page
        catalog_url = f"{url}/la-despensa/alimentacion/cat20009/c?offset={page * number_products_page}"

        # Fetch the current page
        response = requests.get(catalog_url, impersonate="chrome")
        response.raise_for_status()
        text = response.text

        # Find the data in the page
        pattern = r"window\[\"impressions\"\]=(\[.*\])"
        json_data = re.search(pattern, text).group(1)

        # Convert the json data to a python object
        products = json.loads(json_data)

        # Add all the URLs of the current page
        products_url += [
            f"{url}/{product['item_name']}/" + f"R-{product['item_internal_id']}".upper().replace("PROD", "prod") + "/p" for product in products
        ]

    return set(products_url)


def extract_product_info(product_url: str) -> dict:
    """
    Extraer el nombre, precio, precio por kilo y el código de barras EAN-13 de un producto.
    """
    # Fetch product page
    response = requests.get(product_url, impersonate="chrome")
    response.raise_for_status()
    text = response.text

    soup = BeautifulSoup(text, "html.parser")

    # Encontrar datos del producto usando BeautifulSoup
    product_name = soup.find("h1", class_="product-header__name").text.strip()
    product_price = soup.find("span", class_="buybox__price").text.strip()
    product_price_per_unit = soup.find("div", class_="buybox__price-per-unit").find("span").text.strip()

    # Convertir a floats
    product_price = float(product_price.split()[0].replace(",", "."))
    product_price_per_unit = float(product_price_per_unit.split()[0].replace(",", "."))

    # Encontrar el código de barras EAN-13 usando una expresión regular
    pattern = r"\b\d{13}\b"
    ean13 = re.search(pattern, text).group()

    return {"product_name": product_name, "product_price": product_price, "product_price_per_unit": product_price_per_unit, "ean13": ean13}


if __name__ == "__main__":
    # product_links = extract_catalog_product_links()
    # with open("catalog.txt", "w") as f:
    #     f.write("\n".join(product_links))

    # Abrir el archivo de cache con todas las urls de los productos
    with open("catalog.txt", "r") as f:
        product_links = f.readlines()

    products = []
    for product_link in product_links:  # tqdm(product_links, "Fetching products", unit=" products"):
        product = extract_product_info(product_link)
        products.append(product)

    with open("products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=4)
