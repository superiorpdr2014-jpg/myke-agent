import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_FILE  = os.path.join(SCRIPT_DIR, "timetree_auth.json")

print("開啟瀏覽器...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--window-size=1280,900"])
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()

    page.goto("https://timetreeapp.com/signin")
    print("瀏覽器已開啟 TimeTree 登入頁面")
    print("請登入，完成後等 5 秒會自動儲存 session\n")

    # Wait 90 seconds for user to log in
    for i in range(90):
        time.sleep(1)
        current_url = page.url
        if "signin" not in current_url and "login" not in current_url:
            print(f"偵測到已登入！URL: {current_url}")
            time.sleep(3)
            break
        if i % 10 == 9:
            print(f"等待登入中... ({i+1}/90 秒) 目前 URL: {current_url}")
    else:
        print("90 秒內未偵測到登入，強制儲存目前 session")

    ctx.storage_state(path=AUTH_FILE)
    print(f"\nSession 已儲存：{AUTH_FILE}")
    browser.close()

print("完成！現在可以跑 morning_report.py 了")
