import asyncio
from playwright.async_api import async_playwright

async def run_scraper():
    async with async_playwright() as p:
        # Konfiguracja pod Lambdę (kluczowe flagi)
        browser = await p.chromium.launch(args=[
            "--single-process",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote"
        ])
        page = await browser.new_page()
        
        print("Wchodzę na OLX...")
        await page.goto("https://www.olx.pl", timeout=60000)
        title = await page.title()
        
        print(f"Sukces! Tytuł to: {title}")
        await browser.close()
        return title

def handler(event, context):
    title = asyncio.run(run_scraper())
    return {
        "statusCode": 200,
        "body": f"Zeskrapowano tytuł: {title}"
    }