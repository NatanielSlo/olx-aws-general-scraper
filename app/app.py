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
        self.key_word = os.environ.get('KEY_WORD', '')
        self.query = os.environ.get('QUERY', 'iphone')
        self.phone_model = os.environ.get('PHONE_MODEL', '')
        self.min_price = int(os.environ.get('MIN_PRICE', 0))
        self.page_limit = int(os.environ.get('PAGE_LIMIT', 1))

        self.url_builder = UrlBuilder()
        self.browser = None
        self.context = None
        
        self.sqs = boto3.client('sqs')
        self.sqs_url = os.environ.get('SQS_URL')

    async def start(self):
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=True, 
            args=[
                "--single-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--disable-setuid-sandbox"
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
        print("Przeglądarka i kontekst gotowe.")

    async def run_search(self):
        if not self.browser:
            await self.start()

        for page_num in range(1, self.page_limit + 1):
            url = self.url_builder.build_search_url(
                self.query, page_num, phone_model=self.phone_model
            )
            
            
            page = await self.context.new_page()
            search_page = SearchPage(page)
            
            try:
                print(f"Scrapuję stronę {page_num}: {url}")
                
                
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                
                if await self._check_for_blocks(page):
                    continue

                
                try:
                    await page.get_by_test_id("l-card").first.wait_for(state="visible", timeout=7000)
                except Exception:
                    print(f"Brak produktów lub zmiana struktury na stronie {page_num}. HTML: { (await page.title()) }")
                    continue

                new_products = await search_page.get_all_products(
                    self.key_word, self.min_price
                )
                
                if new_products:
                    self.send_to_sqs(new_products, page_num)
                
               
                is_end = await self._is_end_of_results(page, page_num)
                if is_end:
                    print("Osiągnięto koniec wyników.")
                    break
                
            except Exception as e:
                print(f"Błąd na stronie {page_num}: {str(e)}")
            finally:
                
                await page.close()
            
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
        
        await self.stop()

    def send_to_sqs(self, products, page_num):
        if not self.sqs_url:
            return

        print(f"Wysyłam {len(products)} produktów do SQS...")
        
        for product in products:
            try:
                product['page_source'] = page_num
                self.sqs.send_message(
                    QueueUrl=self.sqs_url,
                    MessageBody=json.dumps(product, ensure_ascii=False)
                )
            except Exception as e:
                print(f"Błąd SQS: {e}")

    async def stop(self):
        if self.browser:
            await self.browser.close()
            print("Przeglądarka zamknięta.")

    async def _check_for_blocks(self, page):
        # Sprawdzamy czy nie ma 403 lub Cloudflare
        content = await page.content()
        if "403 Forbidden" in content or "Access Denied" in content:
            print("Wykryto blokadę 403/Access Denied!")
            return True
        return False

    async def _is_end_of_results(self, page, page_num):
        # Jeśli URL się zmienił (np. przekierowanie na stronę 1), to koniec
        current_url = page.url
        if f"page={page_num}" not in current_url and page_num > 1:
            return True
        return False

def handler(event, context):
    scraper = GeneralScraper()
    try:
        asyncio.run(scraper.run_search())
    except Exception as e:
        print(f"Krytyczny błąd handlera: {e}")
        raise e
    
    return {
        "statusCode": 200,
        "body": "Scrapowanie zakończone."
    }