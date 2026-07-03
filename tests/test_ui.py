import asyncio
from playwright.async_api import async_playwright

async def main():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = await browser.new_page()
            
            print("Going to http://localhost:8000")
            await page.goto("http://localhost:8000", wait_until="domcontentloaded")
            
            # Auto-login if we hit the login page
            if "/login" in page.url:
                print("Logging in...")
                await page.fill("input[name='username']", "admin")
                await page.fill("input[name='password']", "admin")
                await page.click("button[type='submit']")
                await page.wait_for_url("**/", wait_until="domcontentloaded")
                print("Logged in!")
                
            await page.screenshot(path="after_login.png")
            print("Taking screenshot to see the page state: after_login.png")

            print("Clicking Containers tab")
            await page.click("button:has-text('Containers')")
            await asyncio.sleep(1)

            # Click the nginx quadlet tree button (which is on server_id 2)
            print("Clicking nginx")
            await page.click("button[data-stem='nginx']")
            await asyncio.sleep(1)
            
            print("Clicking connect")
            await page.click("button:has-text('Connect')")
            await asyncio.sleep(2)
            
            print("Focusing terminal")
            await page.click(".xterm-rows")  # Click to focus the terminal
            await asyncio.sleep(2)
            
            print("Typing ls")
            await page.keyboard.type("ls\n")
            await asyncio.sleep(2)
            
            await page.screenshot(path="terminal_after_ls.png")
            print("Screenshot saved to terminal_after_ls.png")
            
            await browser.close()
    except Exception as e:
        print("Error in script:", e)

if __name__ == "__main__":
    asyncio.run(main())
