"""
Myke Agent MCP Server
讓 Claude 桌面 app 直接執行晨報、IG 數據、行事曆查詢
"""
import sys, io, os, json, time, sqlite3, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Ensure working directory is Myke_Agent
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(AGENT_DIR)
sys.path.insert(0, AGENT_DIR)

import requests
from datetime import datetime, timezone, timedelta
from fastmcp import FastMCP

mcp = FastMCP("Myke Agent - SUPERIOR PDR")

# ── Config ────────────────────────────────────────────────────
TOKEN  = "EAAQ6o3ckxjABRs5zHPoCeEMWNrqSVKtmZB4n3a1ncNbrUmcot4qvzkQ98pWI6xt2ZBPIFmLhouUDxWkEcAZANNrgRudYmiFDBsgnTCZB4tIKLVsaWmZAGSpQ7GnNpw3Vdyo3guk0ZBrwl3JSrfCUrXnOTcptUpQRdRbqvGma3XGxtzQW48M9ZARM1yJuMZAfZCNT8lMbxKD1uGyEhSxSOx88MK4nL9ZBIc450kgssUloZB62VDIqehHpsYvWek3ZB0jxZASNYntA3CnyuEWX7KUyjXrtSGfMMRwZDZD"
IG_ID  = "17841405319139027"
BASE   = "https://graph.facebook.com/v25.0"

CALENDAR_URL = "https://timetreeapp.com/calendars/TEjWVnDzaE17"
AUTH_FILE    = os.path.join(AGENT_DIR, "timetree_auth.json")
COOKIES_DB   = r"C:\Users\User\AppData\Roaming\wmux\Network\Cookies"
COOKIES_TMP  = r"C:\Users\User\AppData\Local\Temp\wmux_cookies_tmp"

TW = timezone(timedelta(hours=8))
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
USER_MAP = {
    28814678:   "Jay",
    1008067833: "杰",
    64569934:   "芷",
    64569925:   "Aki",
    30272072:   "十六",
    37718089:   "瑪莉姐",
}

# ── Helpers ───────────────────────────────────────────────────
def refresh_cookies():
    if not os.path.exists(COOKIES_DB):
        return False
    try:
        shutil.copy2(COOKIES_DB, COOKIES_TMP)
        conn = sqlite3.connect(COOKIES_TMP)
        cur  = conn.cursor()
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
            "expires": -1, "httpOnly": bool(r[4]),
            "secure": bool(r[5]), "sameSite": "Lax"
        } for r in rows]
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookies, "origins": []}, f)
        return True
    except Exception:
        return False

def fetch_timetree_events():
    refresh_cookies()
    if not os.path.exists(AUTH_FILE):
        return []
    from playwright.sync_api import sync_playwright
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
            ctx  = browser.new_context(storage_state=AUTH_FILE)
            page = ctx.new_page()
            page.on("response", on_response)
            page.goto(CALENDAR_URL, wait_until="networkidle", timeout=25000)
            time.sleep(2)
            try:
                page.get_by_text("週", exact=True).first.click()
                time.sleep(2)
            except Exception:
                pass
            browser.close()
    except Exception as e:
        return []
    for resp in captured:
        if "events/sync" in resp["url"]:
            return resp["body"].get("events", [])
    return []

def filter_events(events, target_date):
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=TW)
    ts_start  = int(day_start.timestamp() * 1000)
    ts_end    = int((day_start + timedelta(days=1)).timestamp() * 1000)
    return sorted([e for e in events if ts_start <= e.get("start_at", 0) < ts_end],
                  key=lambda x: x.get("start_at", 0))

def fmt_event(ev):
    start_dt = datetime.fromtimestamp(ev.get("start_at", 0) / 1000, tz=TW)
    end_dt   = datetime.fromtimestamp(ev.get("end_at",   0) / 1000, tz=TW)
    all_day  = ev.get("all_day", False)
    time_str = "全天" if all_day else f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
    names    = "、".join(USER_MAP.get(uid, str(uid)) for uid in ev.get("attendees", []))
    return ev.get("title", "（無標題）"), time_str, names

def ig_info():
    r = requests.get(f"{BASE}/{IG_ID}", params={
        "fields": "username,followers_count,media_count", "access_token": TOKEN
    })
    return r.json()

def ig_posts(limit=5):
    r = requests.get(f"{BASE}/{IG_ID}/media", params={
        "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
        "limit": limit, "access_token": TOKEN
    })
    return r.json().get("data", [])

# ── MCP Tools ─────────────────────────────────────────────────

@mcp.tool()
def morning_report() -> str:
    """
    產生 SUPERIOR PDR 每日晨報，包含：
    - 卓越行銷部 TimeTree 行事曆（今日 / 明日 / 本週）
    - @superiorpdrtaiwan IG 粉絲數與最新 5 則貼文數據
    適合每天早上執行，掌握當天任務與 IG 表現。
    """
    now = datetime.now(TW)
    wd  = WEEKDAYS[now.weekday()]
    lines = []
    lines.append(f"\n{'='*54}")
    lines.append(f"  SUPERIOR PDR 晨報   {now.strftime('%Y/%m/%d')} 週{wd}")
    lines.append(f"{'='*54}")

    # TimeTree
    lines.append("\n【行事曆】卓越行銷部")
    events = fetch_timetree_events()
    if events:
        today_evs = filter_events(events, now)
        tmr_evs   = filter_events(events, now + timedelta(days=1))
        week_evs  = []
        for d in range(2, 8 - now.weekday()):
            week_evs.extend(filter_events(events, now + timedelta(days=d)))

        lines.append(f"\n  今日 ({now.strftime('%m/%d')} 週{wd})")
        if today_evs:
            for ev in today_evs:
                t, ts, n = fmt_event(ev)
                lines.append(f"    {ts}  {t}" + (f"  / {n}" if n else ""))
        else:
            lines.append("    （無排程）")

        lines.append(f"\n  明日 ({(now+timedelta(days=1)).strftime('%m/%d')})")
        if tmr_evs:
            for ev in tmr_evs:
                t, ts, n = fmt_event(ev)
                lines.append(f"    {ts}  {t}" + (f"  / {n}" if n else ""))
        else:
            lines.append("    （無排程）")

        if week_evs:
            lines.append("\n  本週其餘排程")
            cur_day = None
            for ev in week_evs:
                ev_dt = datetime.fromtimestamp(ev.get("start_at", 0) / 1000, tz=TW)
                dl = f"{ev_dt.strftime('%m/%d')} 週{WEEKDAYS[ev_dt.weekday()]}"
                if dl != cur_day:
                    lines.append(f"\n    {dl}")
                    cur_day = dl
                t, ts, n = fmt_event(ev)
                lines.append(f"      {ts}  {t}" + (f"  / {n}" if n else ""))
    else:
        lines.append("  無法讀取行事曆（請確認 wmux 已開啟）")

    # IG
    lines.append(f"\n{'─'*54}")
    lines.append("【IG】@superiorpdrtaiwan")
    info  = ig_info()
    posts = ig_posts(5)
    lines.append(f"\n  粉絲 {info.get('followers_count',0):,}   貼文 {info.get('media_count',0)}")
    top = max(posts, key=lambda x: x.get("like_count", 0)) if posts else None
    lines.append("\n  最新 5 則")
    for i, p in enumerate(posts, 1):
        ts   = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00")).astimezone(TW)
        cap  = p.get("caption", "")[:50].replace("\n", " ")
        star = " ★" if p == top else ""
        lines.append(f"\n    [{i}]{star} {ts.strftime('%m/%d')} {p['media_type']}")
        lines.append(f"    愛心 {p.get('like_count',0):,}   留言 {p.get('comments_count',0)}")
        lines.append(f"    {cap}...")
        lines.append(f"    {p.get('permalink','')}")

    lines.append(f"\n{'='*54}\n")
    return "\n".join(lines)


@mcp.tool()
def ig_stats() -> str:
    """
    快速查詢 @superiorpdrtaiwan IG 即時數據：
    粉絲數、總貼文數、最新貼文表現。
    """
    info  = ig_info()
    posts = ig_posts(5)
    now   = datetime.now(TW)
    lines = [f"@superiorpdrtaiwan IG 數據（{now.strftime('%m/%d %H:%M')}）\n"]
    lines.append(f"粉絲：{info.get('followers_count',0):,}")
    lines.append(f"總貼文：{info.get('media_count',0)}")
    if posts:
        top = max(posts, key=lambda x: x.get("like_count", 0))
        lines.append(f"\n最新 5 則：")
        for i, p in enumerate(posts, 1):
            ts   = datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00")).astimezone(TW)
            cap  = p.get("caption", "")[:40].replace("\n", " ")
            star = " ★" if p == top else ""
            lines.append(f"  [{i}]{star} {ts.strftime('%m/%d')}  愛心{p.get('like_count',0):,}  留言{p.get('comments_count',0)}  {cap}...")
    return "\n".join(lines)


@mcp.tool()
def calendar_today() -> str:
    """
    查詢卓越行銷部今天的行事曆排程。
    比 morning_report 更快，只回傳今日事件。
    """
    now    = datetime.now(TW)
    wd     = WEEKDAYS[now.weekday()]
    events = fetch_timetree_events()
    if not events:
        return "無法讀取行事曆（請確認 wmux 已開啟）"
    today_evs = filter_events(events, now)
    if not today_evs:
        return f"{now.strftime('%m/%d')} 週{wd} 今日無排程"
    lines = [f"{now.strftime('%m/%d')} 週{wd} 今日排程：\n"]
    for ev in today_evs:
        t, ts, n = fmt_event(ev)
        lines.append(f"  {ts}  {t}" + (f"  / {n}" if n else ""))
    return "\n".join(lines)


@mcp.tool()
def calendar_week() -> str:
    """
    查詢卓越行銷部本週完整行事曆排程（今天到週日）。
    """
    now    = datetime.now(TW)
    events = fetch_timetree_events()
    if not events:
        return "無法讀取行事曆（請確認 wmux 已開啟）"
    lines = [f"本週行事曆（{now.strftime('%m/%d')} 起）\n"]
    days_left = 7 - now.weekday()
    for d in range(days_left):
        target  = now + timedelta(days=d)
        day_evs = filter_events(events, target)
        wd      = WEEKDAYS[target.weekday()]
        label   = f"{'今天' if d==0 else '明天' if d==1 else ''} {target.strftime('%m/%d')} 週{wd}"
        lines.append(f"\n{label}")
        if day_evs:
            for ev in day_evs:
                t, ts, n = fmt_event(ev)
                lines.append(f"  {ts}  {t}" + (f"  / {n}" if n else ""))
        else:
            lines.append("  （無排程）")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
