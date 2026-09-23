from curl_cffi import requests
import re
import json
from tqdm import tqdm

url = "https://www.carrefour.es/supermercado"

# Catalog 20009 corresponds to the alimentation products catalog
catalog_number = 20009

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
        f"{url}/{product['item_name']}/R-{product['item_internal_id']}/p"
        for product in products
    ]
