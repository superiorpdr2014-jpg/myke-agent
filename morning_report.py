import sys, io, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# ── Config ───────────────────────────────────────────────────
TOKEN  = "EAAQ6o3ckxjABRhqfDueupO45NL2Fik9t7f1PCFh7oGBVeMZAlnTiigFfMqW4o71uYVS9ZB6sKKXugmcfkFgGwNstClzaDMNsZAKi7FGA5lp1jQdZBsmonq9bsISHr410N68uJ8YbmkgbIZC58D1h4KiQJWF1asUmWvVjzikSjIgTckp1ob1Or1DtzgN9pQnJcrZAoSGnsNsZAlz9JF3SB1It1pO2AKtzm5ZB4Jfe39ZC8nsXzCrTofG9zVEU1nTdFw5etezaVc8Kgfnn8JqJ0Ti5SDxJxbaEdu6sBKS0ZD"
IG_ID  = "17841405319139027"
BASE   = "https://graph.facebook.com/v25.0"

CALENDAR_URL  = "https://timetreeapp.com/calendars/TEjWVnDzaE17"
AUTH_FILE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timetree_auth.json")
COOKIES_DB    = r"C:\Users\User\AppData\Roaming\wmux\Network\Cookies"
COOKIES_TMP   = r"C:\Users\User\AppData\Local\Temp\wmux_cookies_tmp"

TW = timezone(timedelta(hours=8))
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

USER_MAP = {
    28814678:  "Jay",
    1008067833: "杰",
    64569934:  "芷",
    64569925:  "Aki",
    30272072:  "十六",
    37718089:  "瑪莉姐",
}

# ── Refresh cookies from wmux browser ────────────────────────
def refresh_cookies_from_wmux():
    """Auto-rebuild timetree_auth.json from wmux's live cookies"""
    import sqlite3, shutil
    if not os.path.exists(COOKIES_DB):
        return False
    try:
        shutil.copy2(COOKIES_DB, COOKIES_TMP)
        conn = sqlite3.connect(COOKIES_TMP)
        cur = conn.cursor()
        cur.execute("SELECT host_key, name, value, path, is_httponly, is_secure FROM cookies WHERE host_key LIKE '%timetree%'")
        rows = cur.fetchall()
        conn.close()
        os.remove(COOKIES_TMP)
        if not rows:
            return False
        cookies = [{
            "name": r[1], "value": r[2],
            "domain": r[0].lstrip("."),
            "path": r[3] or "/",
            "expires": -1,
            "httpOnly": bool(r[4]),
            "secure": bool(r[5]),
            "sameSite": "Lax"
        } for r in rows]
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookies, "origins": []}, f)
        return True
    except Exception:
        return False

# ── TimeTree ──────────────────────────────────────────────────
def get_timetree_events():
    if not os.path.exists(AUTH_FILE):
        refresh_cookies_from_wmux()
    if not os.path.exists(AUTH_FILE):
        return []

    captured = []

    def on_response(resp):
        if "timetreeapp.com" in resp.url and resp.status == 200:
            try:
                if "json" in resp.headers.get("content-type", ""):
                    captured.append({"url": resp.url, "body": resp.json()})
            except Exception:
                pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=AUTH_FILE)
            page = ctx.new_page()
            page.on("response", on_response)

            page.goto(CALENDAR_URL, wait_until="networkidle", timeout=25000)
            time.sleep(2)

            # Switch to week view to trigger week-specific API calls
            try:
                page.get_by_text("週", exact=True).first.click()
                time.sleep(2)
            except Exception:
                pass

            browser.close()
    except Exception as e:
        print(f"  [TimeTree 錯誤] {e}")
        return []

    # Extract events from sync API response
    for resp in captured:
        if "events/sync" in resp["url"]:
            return resp["body"].get("events", [])

    return []

def filter_events(events, target_date):
    """Filter events for a specific date (Taiwan timezone)"""
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=TW)
    day_end   = day_start + timedelta(days=1)
    ts_start  = int(day_start.timestamp() * 1000)
    ts_end    = int(day_end.timestamp() * 1000)

    result = []
    for ev in events:
        start = ev.get("start_at", 0)
        if ts_start <= start < ts_end:
            result.append(ev)
    return sorted(result, key=lambda x: x.get("start_at", 0))

def format_event(ev):
    start_ts = ev.get("start_at", 0) / 1000
    start_dt = datetime.fromtimestamp(start_ts, tz=TW)
    title = ev.get("title", "（無標題）")
    all_day = ev.get("all_day", False)

    attendee_ids = ev.get("attendees", [])
    names = [USER_MAP.get(uid, str(uid)) for uid in attendee_ids]
    names_str = "、".join(names) if names else ""

    if all_day:
        time_str = "全天"
    else:
        end_ts = ev.get("end_at", 0) / 1000
        end_dt = datetime.fromtimestamp(end_ts, tz=TW)
        time_str = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"

    return title, time_str, names_str

# ── IG ───────────────────────────────────────────────────────
def get_account_info():
    r = requests.get(f"{BASE}/{IG_ID}", params={
        "fields": "username,followers_count,media_count",
        "access_token": TOKEN
    })
    return r.json()

def get_recent_posts(limit=5):
    r = requests.get(f"{BASE}/{IG_ID}/media", params={
        "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
        "limit": limit,
        "access_token": TOKEN
    })
    return r.json().get("data", [])

# ── Report ───────────────────────────────────────────────────
def generate_morning_report():
    now = datetime.now(TW)
    wd  = WEEKDAYS[now.weekday()]

    print(f"\n{'='*56}")
    print(f"  SUPERIOR PDR 晨報   {now.strftime('%Y/%m/%d')} 週{wd}")
    print(f"{'='*56}")

    # ── TimeTree ─────────────────────────────────────────────
    print(f"\n【行事曆】卓越行銷部")

    # Auto-refresh cookies from wmux
    refresh_cookies_from_wmux()

    events = get_timetree_events()

    if events:
        today_evs = filter_events(events, now)
        tomorrow  = now + timedelta(days=1)
        tmr_evs   = filter_events(events, tomorrow)

        # This week remaining (today+1 to end of week)
        week_evs = []
        for d in range(2, 8 - now.weekday()):
            target = now + timedelta(days=d)
            week_evs.extend(filter_events(events, target))

        print(f"\n  今日 ({now.strftime('%m/%d')} 週{wd})")
        if today_evs:
            for ev in today_evs:
                title, time_str, names = format_event(ev)
                print(f"    {time_str}  {title}" + (f"  / {names}" if names else ""))
        else:
            print("    （無排程）")

        print(f"\n  明日 ({tomorrow.strftime('%m/%d')})")
        if tmr_evs:
            for ev in tmr_evs:
                title, time_str, names = format_event(ev)
                print(f"    {time_str}  {title}" + (f"  / {names}" if names else ""))
        else:
            print("    （無排程）")

        if week_evs:
            print(f"\n  本週其餘排程")
            cur_day = None
            for ev in week_evs:
                start_ts = ev.get("start_at", 0) / 1000
                ev_date  = datetime.fromtimestamp(start_ts, tz=TW)
                day_label = f"{ev_date.strftime('%m/%d')} 週{WEEKDAYS[ev_date.weekday()]}"
                if day_label != cur_day:
                    print(f"\n    {day_label}")
                    cur_day = day_label
                title, time_str, names = format_event(ev)
                print(f"      {time_str}  {title}" + (f"  / {names}" if names else ""))
    else:
        print("  無法讀取行事曆（請確認 wmux 已開啟且已登入 TimeTree）")

    # ── IG ───────────────────────────────────────────────────
    print(f"\n{'─'*56}")
    print(f"【IG】@superiorpdrtaiwan")

    info  = get_account_info()
    posts = get_recent_posts(5)

    followers = info.get("followers_count", 0)
    media     = info.get("media_count", 0)
    print(f"\n  粉絲 {followers:,}   貼文 {media}")

    if posts:
        top = max(posts, key=lambda x: x.get("like_count", 0))

    print(f"\n  最新 5 則")
    for i, p in enumerate(posts, 1):
        ts    = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00")).astimezone(TW)
        cap   = p.get("caption", "")[:45].replace("\n", " ")
        likes = p.get("like_count", 0)
        cmts  = p.get("comments_count", 0)
        star  = " ★" if p == top else ""
        print(f"\n    [{i}]{star} {ts.strftime('%m/%d')} {p['media_type']}")
        print(f"    愛心 {likes:,}   留言 {cmts}")
        print(f"    {cap}...")
        print(f"    {p.get('permalink','')}")

    print(f"\n{'='*56}\n")

if __name__ == "__main__":
    generate_morning_report()
