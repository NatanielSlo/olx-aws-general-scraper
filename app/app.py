import json
import os
import random
import asyncio
import boto3  # Dodajemy boto3

from src.utils.url_builder import UrlBuilder
from src.pages.search_page import SearchPage
# Usunęliśmy PostgresUploader - w Lambdzie lepiej robić to przez SQS/API
from playwright.async_api import async_playwright


class GeneralScraper:
    def __init__(self):
        self.key_word = os.environ.get('KEY_WORD', '')
        self.query = os.environ.get('QUERY', 'iphone')
        self.phone_model = os.environ.get('PHONE_MODEL', '')
        self.min_price = int(os.environ.get('MIN_PRICE', 0))
        self.page_limit = int(os.environ.get('PAGE_LIMIT', 1))

        self.url_builder = UrlBuilder()
        self.browser = None
        self.context = None
        self.page = None
        self.search_page = None
        
        # Inicjalizacja klienta SQS
        self.sqs = boto3.client('sqs')
        # URL pobieramy ze zmiennej środowiskowej (ustawimy ją w AWS)
        self.sqs_url = os.environ.get('SQS_URL')

    async def start(self):
        playwright = await async_playwright().start()
        # KLUCZOWE: Flagi dla Chromium w Lambdzie (Docker)
        self.browser = await playwright.chromium.launch(
            headless=True, # Lambda musi być headless
            args=[
                "--single-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote"
            ]
        )
        
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
            viewport={'width': 1280, 'height': 720}
        )
        
        # Blokowanie obrazków - oszczędza transfer i czas w Lambdzie
        await self.context.route("**/*", lambda route: 
            route.abort() if route.request.resource_type in ["image", "media", "font"] 
            else route.continue_()
        )
        
        self.page = await self.context.new_page()
        self.search_page = SearchPage(self.page)
        print("Przeglądarka gotowa w AWS Lambda.")

    async def run_search(self):
        if not self.page:
            await self.start()

        for page_num in range(1, self.page_limit + 1):
            url = self.url_builder.build_search_url(
                self.query, page_num, phone_model=self.phone_model
            )
            
            print(f"Scrapuję stronę {page_num}: {url}")
            await self.page.goto(url, wait_until="domcontentloaded")
            
            if await self._check_for_blocks(url):
                continue
            
            # Pobieranie produktów
            new_products = await self.search_page.get_all_products(
                self.key_word, self.min_price
            )
            
            
            if new_products:
                self.send_to_sqs(new_products, page_num)
            
            if await self._is_end_of_results(page_num):
                break
            
            
            await self.page.wait_for_timeout(random.randint(500, 1500))
        
        await self.stop()

    def send_to_sqs(self, products, page_num):
        if not self.sqs_url:
            return

        print(f"Wysyłam {len(products)} produktów do SQS (pojedynczo)...")
        
        for product in products:
            try:
                product['page_source'] = page_num
                self.sqs.send_message(
                    QueueUrl=self.sqs_url,
                    MessageBody=json.dumps(product, ensure_ascii=False)
                )
            except Exception as e:
                print(f"Błąd przy wysyłaniu pojedynczego produktu: {e}")

        async def stop(self):
            if self.browser:
                await self.browser.close()
                print("Przeglądarka zamknięta.")

    async def _check_for_blocks(self, url):
        is_403 = await self.page.locator("h1:has-text('403 ERROR')").is_visible()
        if is_403:
            print("Wykryto blokadę 403!")
            return True
        return False

    async def _is_end_of_results(self, page_num):
        if f"page={page_num}" not in self.page.url and page_num > 1:
            return True
        return False

# HANDLER - to wywołuje AWS Lambda
def handler(event, context):
    scraper = GeneralScraper()
    asyncio.run(scraper.run_search())
    return {
        "statusCode": 200,
        "body": "Scrapowanie zakończone pomyślnie."
    }