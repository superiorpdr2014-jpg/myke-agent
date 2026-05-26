import sys, io, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright

CALENDAR_URL = "https://timetreeapp.com/calendars/TEjWVnDzaE17"
AUTH_FILE = "timetree_auth.json"

with sync_playwright() as p:
    if os.path.exists(AUTH_FILE):
        print(f"使用已儲存的登入狀態：{AUTH_FILE}")
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=AUTH_FILE)
    else:
        print("首次登入：請在瀏覽器完成 TimeTree 登入")
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()

    page = ctx.new_page()
    page.goto(CALENDAR_URL)

    if not os.path.exists(AUTH_FILE):
        print("等待登入完成（頁面出現行事曆後按 Enter）...")
        input()
        ctx.storage_state(path=AUTH_FILE)
        print(f"登入狀態已儲存到 {AUTH_FILE}")

    page.wait_for_load_state("networkidle", timeout=15000)
    time.sleep(2)

    # Screenshot to see current state
    page.screenshot(path="timetree_screenshot.png")
    print("截圖已存：timetree_screenshot.png")

    # Get page title and basic structure
    print(f"頁面標題：{page.title()}")
    print(f"URL：{page.url}")

    # Get all text to see event structure
    text = page.inner_text("body")
    print("\n--- 頁面文字（前 2000 字）---")
    print(text[:2000])

    browser.close()
