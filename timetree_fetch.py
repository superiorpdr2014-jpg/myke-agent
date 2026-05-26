import sys, io, time, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright
from datetime import datetime, timezone, timedelta

AUTH_FILE    = "timetree_auth.json"
CALENDAR_URL = "https://timetreeapp.com/calendars/TEjWVnDzaE17"
TW = timezone(timedelta(hours=8))

captured_responses = []

def get_calendar_events():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=AUTH_FILE)
        page = ctx.new_page()

        # Intercept API responses
        def handle_response(response):
            url = response.url
            if "timetreeapp.com" in url and response.status == 200:
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = response.json()
                        captured_responses.append({"url": url, "body": body})
                except Exception:
                    pass

        page.on("response", handle_response)

        page.goto(CALENDAR_URL, wait_until="networkidle", timeout=25000)
        time.sleep(3)

        # Switch to week view to trigger week API calls
        try:
            page.get_by_text("週", exact=True).first.click()
            time.sleep(3)
        except Exception:
            pass

        # Also click 今天 to make sure we're on current week
        try:
            page.get_by_text("今天", exact=True).first.click()
            time.sleep(2)
        except Exception:
            pass

        # Get full page text as fallback
        page_text = page.inner_text("body")

        browser.close()

    return captured_responses, page_text


def parse_page_text_events(text, today):
    """Parse events from page text with date context"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Find week headers - look for date pattern like 25/26/27 etc
    today_day = today.day
    today_str = f"{today.month}/{today.day}"

    events = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip navigation and UI elements
        if line in ("今天", "月", "週", "全天", "行事曆", "找不到相符的行事"):
            i += 1
            continue
        # Skip pure numbers (time slots or date numbers)
        if line.isdigit() and int(line) <= 60:
            i += 1
            continue
        # Skip weekday names
        if line in ("週日", "週一", "週二", "週三", "週四", "週五", "週六"):
            i += 1
            continue

        # Detect if it's an event (has content besides just a time)
        time_pattern = re.match(r"^(\d{1,2}:\d{2})(\s*-\s*\d{1,2}:\d{2})?$", line)
        if time_pattern:
            i += 1
            continue

        # Check if it looks like an event name (has Chinese or meaningful content)
        if len(line) >= 3 and not re.match(r"^\d+\.\d+$", line) and not re.match(r"^\d{4}年\d+月$", line):
            # Look ahead for time info
            time_info = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if re.match(r"^\d{1,2}:\d{2}", next_line):
                    time_info = next_line
            events.append({"text": line, "time": time_info})

        i += 1

    return events


if __name__ == "__main__":
    today = datetime.now(TW)
    print(f"抓取日期：{today.strftime('%Y/%m/%d')} 週{['一','二','三','四','五','六','日'][today.weekday()]}")
    print("讀取 TimeTree 行事曆中...\n")

    responses, page_text = get_calendar_events()

    # Try structured data from API intercept
    all_events = []
    for resp in responses:
        url = resp["url"]
        body = resp["body"]
        if isinstance(body, dict) and ("events" in str(body) or "data" in str(body)):
            print(f"API 回應：{url}")
            print(json.dumps(body, ensure_ascii=False, indent=2)[:500])
            print("---")

    # Save raw page text for analysis
    with open("timetree_raw.txt", "w", encoding="utf-8") as f:
        f.write(page_text)
    print(f"原始頁面文字存於 timetree_raw.txt\n")

    # Parse events from page text
    events = parse_page_text_events(page_text, today)
    print(f"解析到 {len(events)} 個事件：")
    for ev in events:
        time_str = f" [{ev['time']}]" if ev['time'] else ""
        print(f"  • {ev['text']}{time_str}")

    # Save captured API responses
    if responses:
        with open("timetree_api_responses.json", "w", encoding="utf-8") as f:
            json.dump(responses, f, ensure_ascii=False, indent=2)
        print(f"\nAPI 回應存於 timetree_api_responses.json（{len(responses)} 個）")
