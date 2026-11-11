from curl_cffi import requests
import re
import json
import time
import pandas as pd
from tqdm import tqdm
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def check_and_handle_cloudflare(page, timeout_seconds=60):
    """
    Detecta si Cloudflare ha lanzado un desafío de verificación humana ("Soy humano").
    Si lo detecta, pausa la ejecución y espera a que el usuario lo resuelva manualmente.
    """
    try:
        # Selectores comunes que indican que Cloudflare ha bloqueado la página con un desafío
        cf_selectors = [
            "#challenge-running",
            "iframe[src*='challenges.cloudflare.com']",
            "div.cf-browser-verification",
            "text=Verifica che tu sia un umano" # Versión en italiano de Cloudflare
        ]
        
        is_blocked = False
        for selector in cf_selectors:
            if page.locator(selector).is_visible(timeout=2000):
                is_blocked = True
                break
                
        if is_blocked:
            print("\n" + "!"*60)
            print(" ¡ALERTA! Cloudflare ha detectado el bot y pide verificación humana.")
            print(f" Por favor, ve a la ventana del navegador y resuelve el captcha manualmente.")
            print(f" Tienes {timeout_seconds} segundos para solucionarlo...")
            print("!"*60 + "\n")
            
            # Esperamos a que desaparezca el reto de Cloudflare (máximo el tiempo indicado)
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                still_blocked = False
                for selector in cf_selectors:
                    if page.locator(selector).is_visible():
                        still_blocked = True
                        break
                if not still_blocked:
                    print("Continuando con el scraping...")
                    time.sleep(2)
                    return True
                time.sleep(1)
                
            print("Tiempo agotado para resolver el captcha de Cloudflare.")
            return False
            
    except Exception:
        pass
        
    return True

def filter_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filtra el DataFrame para conservar únicamente los productos cuya categoría 
    coincida con la categoría mayoritaria (moda) de su respectiva búsqueda (search_query).
    """
    if df.empty or 'category' not in df.columns or 'search_query' not in df.columns:
        print("El DataFrame está vacío o no contiene las columnas necesarias ('category', 'search_query').")
        return df

    filtered_groups = []

    # Agrupamos por término de búsqueda (ej: 'spaghetti', 'riso', etc.)
    for query, group in df.groupby('search_query'):
        # Si la categoría es desconocida en todos, evitamos filtrar erróneamente
        if group['category'].nunique() <= 1:
            filtered_groups.append(group)
            continue

        # Calculamos la categoría más frecuente (moda) para este alimento
        # mode() puede devolver varios valores si hay empate, cogemos el primero con [0]
        moda_categoria = group['category'].mode()[0]
        
        # Filtramos el grupo quedándonos solo con los que pertenecen a la categoría mayoritaria
        grupo_filtrado = group[group['category'] == moda_categoria]
        
        # Opcional: mostrar un aviso de cuántos elementos se descartaron en esta query
        descartados = len(group) - len(grupo_filtrado)
        if descartados > 0:
            print(f"Para '{query}': se descartaron {descartados} productos fuera de la categoría '{moda_categoria}'.")
            
        filtered_groups.append(grupo_filtrado)

    # Unimos de nuevo todos los grupos limpios en un único DataFrame
    df_clean = pd.concat(filtered_groups, ignore_index=True)
    return df_clean

def scroll_to_bottom_to_load_all(page, max_scrolls=10):
    """
    Hace scroll hacia abajo repetidamente para forzar la carga 
    de todos los productos en páginas de scroll infinito.
    """
    last_height = page.evaluate("document.body.scrollHeight")
    
    for _ in range(max_scrolls):
        # Desplazarse hasta el final de la página
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        
        # Esperar a que carguen los nuevos elementos dinámicos
        time.sleep(2)
        
        # Calcular la nueva altura de la página
        new_height = page.evaluate("document.body.scrollHeight")
        
        # Si la altura no cambia, significa que ya hemos llegado al final del catálogo
        if new_height == last_height:
            break
        last_height = new_height

def extract_products_from_page(html_text, product_name) -> list[dict]:
    """
    Extrae los productos leyendo directamente el JSON incrustado 
    en el atributo data-product-json de cada <article>.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    products = []
    
    # Buscamos todos los artículos de productos
    cards = soup.find_all("article", class_=lambda x: x and "product-item-with-tooltip" in x)
    
    for card in cards:
        try:
            # Obtenemos el texto del JSON que está dentro del atributo
            json_str = card.get("data-product-json")
            if not json_str:
                continue
                
            # Convertimos el string JSON en un diccionario de Python
            p_data = json.loads(json_str)
            
            # Mapeamos los campos (las claves exactas pueden variar ligeramente)
            product_info = {
                "search_query": product_name,
                "name": p_data.get("name") or p_data.get("item_name") or "",
                "price": p_data.get("price") or p_data.get("value") or None,
                "brand": p_data.get("brand") or p_data.get("item_brand") or "",
                "category": p_data.get("category") or p_data.get("item_category") or "NA",
                "ean": p_data.get("ean") or p_data.get("item_ean") or p_data.get("id") or ""
            }
            
            products.append(product_info)
            
        except json.JSONDecodeError:
            # Si hay algún problema al parsear el JSON de un producto específico, lo saltamos
            continue
        except Exception:
            continue
            
    return products

def fetch(session, url: str, max_retries=4) -> str:
    """
    Dada una URL, trata de descargar el contenido de una página. Sí la petición de desacarga falla, espera y lo vuelve a intentar.
    
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.carrefour.it/"
    }
    """
    for attempt in range(max_retries + 1):
        response = session.get(url, impersonate="chrome120")

        # Si no hay error o se alcanzó el límite de intentos, salir del bucle
        if response.status_code not in (429, 503, 403) or attempt == max_retries:
            break

        retry_after = response.headers.get("Retry-After", "")
        wait = int(retry_after) if retry_after.isdigit() else 30 * 2**attempt
        print(f"\n{response.status_code} en {url}, esperando {wait} s")
        time.sleep(wait)

    response.raise_for_status()
    return response.text

def extract_products_from_csv(page, filename='cesta.csv') -> list[dict]:
    '''
    Extraer todos los productos de la cesta elegida, e iniciar la búsqueda en la página
    '''
    all_products = []
    
    with open(file=filename, mode='r', encoding='utf-8') as f:
        df_products = pd.read_csv(f)

    # Nos quedamos los productos en italiano
    product_names = df_products["it"]
    for product_name in tqdm(product_names, desc="Buscando en Carrefour IT", unit="alimento"):

        products = search_product_on_carrefour(page, product_name)
   
        all_products.extend(products)
        
        time.sleep(2.0)

    return all_products

def search_product_on_carrefour(page, product_name) -> list[dict]:
    """
    Navega a la URL de búsqueda utilizando Playwright, espera a que cargue el DOM
    y extrae los resultados.
    """
    url = f'https://www.carrefour.it/search?q={product_name}'

    try:
        # Navegamos a la página de búsqueda
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Revisamos si hubiera un bloqueo de Cloudflare, se tiene que completar manualmente (pulsar el 'Soy un humano')
        if not check_and_handle_cloudflare(page, timeout_seconds=40):
            print(f"Omitiendo '{product_name}' por bloqueo persistente de Cloudflare.")
            return []
        
        accept_cookies_if_present(page)

        # Necesamos scrollear hasta el final de la página para que en el HTML carguen todos los productos
        scroll_to_bottom_to_load_all(page)

        # Esperamos un momento a que los elementos article aparezcan en pantalla
        try:
            page.wait_for_selector("article.product-item-with-tooltip", timeout=8000)
        except Exception:
            # Si pasan 8 segundos y no aparecen, puede que no haya resultados o la página esté vacía
            pass

        html_content = page.content()
        return extract_products_from_page(html_content, product_name)
        
    except Exception as e:
        print(f"\nExcepción al buscar '{product_name}' con Playwright: {e}")
        return []

def accept_cookies_if_present(page):
    """
    Busca e intenta hacer clic en el botón de aceptar cookies de Carrefour.
    """
    possible_selectors = [
        "button#onetrust-accept-btn-handler",
        "button:has-text('Accetta')",
        "button:has-text('Accetta tutti')",
        "text=Accetta"
    ]
    
    for selector in possible_selectors:
        try:
            # Esperamos un par de segundos por si aparece el banner
            page.wait_for_selector(selector, timeout=3000)
            page.click(selector)
            time.sleep(1)
            break
        except Exception:
            continue

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        page = context.new_page()

        try:
            # Entramos primero a la home para inicializar cookies y resolver cualquier problema de Cloudflare si lo hubiera
            page.goto("https://www.carrefour.it/", wait_until="domcontentloaded", timeout=40000)
            time.sleep(3)
            accept_cookies_if_present(page)
        except Exception as e:
            print(f"Aviso en la carga inicial: {e}")

        products = extract_products_from_csv(page, filename='cesta.csv')

        browser.close()

    df_products = pd.DataFrame(products)
    
    print(f"Total de productos antes del filtrado: {len(df_products)}")

    # Limpiamos los productos por si hubieran algunos que no correspondieran a la búsqueda
    df_clean = filter_by_category(df_products)
    
    print(f"Total de productos después del filtrado: {len(df_clean)}")

    # Guardamos los resultados limpios
    df_clean.to_json("products_it_clean.json", orient="records", force_ascii=False, indent=4)
