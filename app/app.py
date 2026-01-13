import json
import os
import random
import asyncio
import boto3  
from src.utils.url_builder import UrlBuilder
from src.pages.search_page import SearchPage
from playwright.async_api import async_playwright

class GeneralScraper:
    def __init__(self):
        # Stałe parametry z ENV
        self.key_word = os.environ.get('KEY_WORD', '')
        self.min_price = int(os.environ.get('MIN_PRICE', 0))
        self.sqs_url = os.environ.get('SQS_URL') # Kolejka docelowa dla produktów
        
        self.url_builder = UrlBuilder()
        self.sqs = boto3.client('sqs')
        self.browser = None
        self.context = None

    async def start(self):
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=True, 
            args=[
                "--single-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote"
            ]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        
        await self.context.route("**/*", lambda route: 
            route.abort() if route.request.resource_type in ["image", "media", "font"] 
            else route.continue_()
        )

    async def process_page(self, page_data):
        """Metoda przetwarzająca dokładnie JEDNĄ stronę przekazaną z SQS"""
        page_num = page_data.get('page', 1)
        query = page_data.get('query', 'iphone')
        phone_model = page_data.get('phone_model', '')

        await self.start()
        page = await self.context.new_page()
        search_page = SearchPage(page)

        try:
            url = self.url_builder.build_search_url(query, page_num, phone_model=phone_model)
            print(f"Pracuję nad stroną {page_num}: {url}")

            # Ładowanie strony z bezpiecznym timeoutem
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            
            # Sprawdzenie blokady CloudFront/403
            if "The request could not be satisfied" in await page.content():
                print(f"BLOKADA na stronie {page_num}. Przerywam.")
                raise Exception("CloudFront Blocked")

            # Czekamy na produkty
            try:
                await page.get_by_test_id("l-card").first.wait_for(state="visible", timeout=10000)
            except Exception:
                print(f"Timeout: Nie znaleziono produktów na stronie {page_num}.")
                return

            # Pobieranie produktów
            products = await search_page.get_all_products(self.key_word, self.min_price)
            
            if products:
                print(f"Znaleziono {len(products)} produktów. Wysyłam do SQS.")
                self.send_items_to_sqs(products, page_num)
            else:
                print(f"Strona {page_num} wydaje się być pusta (po filtrowaniu).")

        finally:
            await page.close()
            await self.browser.close()

    def send_items_to_sqs(self, products, page_num):
        for product in products:
            product['page_source'] = page_num
            self.sqs.send_message(
                QueueUrl=self.sqs_url,
                MessageBody=json.dumps(product, ensure_ascii=False)
            )

def handler(event, context):
    """
    Handler odbierający rekordy z SQS. 
    Batch size w Lambdzie najlepiej ustawić na 1, aby 1 wiadomość = 1 uruchomienie.
    """
    if not event.get('Records'):
        print("Brak danych w evencie.")
        return

    for record in event['Records']:
        page_data = json.loads(record['body'])
        scraper = GeneralScraper()
        
        # Używamy asyncio.run dla każdego rekordu osobno
        try:
            asyncio.run(scraper.process_page(page_data))
        except Exception as e:
            print(f"Błąd przetwarzania strony: {e}")
            # Rzucamy błąd, żeby wiadomość wróciła do kolejki (Retry)
            raise e

    return {"statusCode": 200}