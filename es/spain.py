from seleniumbase import Driver
from selenium.webdriver.support.ui import WebDriverWait
from curl_cffi import requests
from bs4 import BeautifulSoup
import time
from tqdm import tqdm
import json
import csv
import re


def fetch_selenium(driver, url):
    SHADOW = "document.querySelector('.x-root-container')?.shadowRoot"

    driver.uc_open_with_reconnect(url, 5)

    # Espera a que haya al menos una tarjeta de producto
    WebDriverWait(driver, 15).until(lambda d: d.execute_script(f"return {SHADOW}?.querySelectorAll('article.x-result').length > 0"))

    html = driver.execute_script(f"return {SHADOW}.innerHTML")

    return html


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
        wait = int(retry_after) if retry_after.isdigit() else 16 * 2**attempt
        print(f"\n{response.status_code} en {url}, esperando {wait} s")
        time.sleep(wait)

    response.raise_for_status()
    return response.text


def parse_price(price: str) -> float:
    return float(price.split()[0].replace(",", "."))


def extract_products(html_text: str) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")

    products = []
    for article in soup.find_all("article", class_="x-result"):
        name = article.select_one('[data-test="result-title"] p').get_text(strip=True)

        price = parse_price(article.select_one('[data-test="result-current-price"]').get_text(strip=True))

        match = re.search(r"(\d+(?:[.,]\d+)?)\s*€\s*/\s*\w+", article.get_text(" "))
        price_per_unit = parse_price(match.group(1)) if match else None

        url = article.find("a", class_="x-result-link")["href"]

        products.append({"name": name, "price": price, "price_per_unit": price_per_unit, "url": url})

    return products


def get_ean(session, product_url: str) -> str:
    url = "https://www.carrefour.es" + product_url
    text = fetch(session, url)

    soup = BeautifulSoup(text, "html.parser")

    for s in soup.find_all("script", type="application/ld+json"):
        d = json.loads(s.string)
        if d.get("@type") == "Product":
            ean = d.get("gtin13")
            return ean


if __name__ == "__main__":
    driver = Driver(uc=True, headless=False)
    session = requests.Session(impersonate="chrome")

    with open("cesta.csv", "r") as f:
        reader = csv.DictReader(f)

        products_names = [row["es"] for row in reader]

    products = {name: [] for name in products_names}
    for name in tqdm(products_names, "Fetching products"):
        html_text = fetch_selenium(driver, "https://www.carrefour.es/?query=" + name)

        products[name] = extract_products(html_text)
        for product in products[name]:
            product["ean"] = get_ean(session, product["url"])

    with open("resultados/busqueda.json", "w") as f:
        f.write(json.dumps(products))
