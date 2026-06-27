import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        page.on("console", lambda msg: print(f"Browser console: {msg.type}: {msg.text}"))
        page.on("pageerror", lambda err: print(f"Browser page error: {err}"))
        try:
            await page.goto("http://localhost:8000/")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

asyncio.run(main())
