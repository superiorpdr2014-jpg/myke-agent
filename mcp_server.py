"""
Myke Agent MCP Server
讓 Claude 桌面 app 直接執行晨報、IG 數據、行事曆查詢、Telegram、Airtable CRM
"""
import sys, os, json, time, sqlite3, shutil

# Ensure working directory is Myke_Agent
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(AGENT_DIR)
sys.path.insert(0, AGENT_DIR)

import requests
from datetime import datetime, timezone, timedelta
from fastmcp import FastMCP

mcp = FastMCP("Myke Agent - SUPERIOR PDR")

# ── Config ────────────────────────────────────────────────────
TOKEN  = "EAAQ6o3ckxjABRhqfDueupO45NL2Fik9t7f1PCFh7oGBVeMZAlnTiigFfMqW4o71uYVS9ZB6sKKXugmcfkFgGwNstClzaDMNsZAKi7FGA5lp1jQdZBsmonq9bsISHr410N68uJ8YbmkgbIZC58D1h4KiQJWF1asUmWvVjzikSjIgTckp1ob1Or1DtzgN9pQnJcrZAoSGnsNsZAlz9JF3SB1It1pO2AKtzm5ZB4Jfe39ZC8nsXzCrTofG9zVEU1nTdFw5etezaVc8Kgfnn8JqJ0Ti5SDxJxbaEdu6sBKS0ZD"
IG_ID  = "17841405319139027"
BASE   = "https://graph.facebook.com/v25.0"

CALENDAR_URL = "https://timetreeapp.com/calendars/TEjWVnDzaE17"
AUTH_FILE    = os.path.join(AGENT_DIR, "timetree_auth.json")
COOKIES_DB   = r"C:\Users\User\AppData\Roaming\wmux\Network\Cookies"
COOKIES_TMP  = r"C:\Users\User\AppData\Local\Temp\wmux_cookies_tmp"

# ── Telegram ─────────────────────────────────────────────────
TG_TOKEN  = "8908034513:AAHVLvO9IXF7X9ua3w9TYoSInaBVxzSuvIk"
TG_API    = f"https://api.telegram.org/bot{TG_TOKEN}"

# ── Airtable ──────────────────────────────────────────────────
AT_TOKEN  = "patkGI8IQ5Baf6Itv.092a4b5670dfba7b6b914892002a5dce9070acd341f4669380824902607c22ad"
AT_BASE   = "appZqWnlMF18ysfmk"
AT_API    = "https://api.airtable.com/v0"
AT_TABLES = {
    "客戶": "tblyppP7rIazjfo1o",
    "車輛": "tblck9rVDwxf3oeoE",
    "案件": "tblKQfzgfLg8AYiuQ",
}
AT_HEADERS = {"Authorization": f"Bearer {AT_TOKEN}", "Content-Type": "application/json"}

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


# ── Telegram Tools ────────────────────────────────────────────

@mcp.tool()
def telegram_get_messages(limit: int = 20) -> str:
    """
    讀取 SUPERIOR ECHO Bot 最新收到的 Telegram 訊息。
    顯示發話人、群組名稱、訊息內容與時間。
    limit: 最多讀幾則（預設 20）
    """
    r = requests.get(f"{TG_API}/getUpdates", params={"limit": min(limit, 100), "allowed_updates": ["message"]})
    data = r.json()
    if not data.get("ok"):
        return f"Telegram 錯誤：{data.get('description', '未知錯誤')}"

    updates = data.get("result", [])
    if not updates:
        return "目前無新訊息（Bot 尚未收到任何對話，或訊息已被讀取清空）"

    lines = [f"ECHO Bot 最新 {len(updates)} 則訊息：\n"]
    for u in updates[-limit:]:
        msg  = u.get("message") or u.get("channel_post") or {}
        if not msg:
            continue
        chat     = msg.get("chat", {})
        sender   = msg.get("from", {})
        text     = msg.get("text", "[非文字訊息]")
        ts       = datetime.fromtimestamp(msg.get("date", 0), tz=TW).strftime("%m/%d %H:%M")
        name     = sender.get("first_name", "") + " " + sender.get("last_name", "")
        username = f"@{sender['username']}" if sender.get("username") else name.strip()
        chat_name = chat.get("title") or chat.get("username") or "私訊"
        chat_id   = chat.get("id", "")
        lines.append(f"[{ts}] {chat_name} (id:{chat_id})")
        lines.append(f"  {username}：{text[:200]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def telegram_send_message(chat_id: str, message: str) -> str:
    """
    透過 SUPERIOR ECHO Bot 發送 Telegram 訊息到指定群組或用戶。
    chat_id: 群組或用戶的 ID（從 telegram_get_messages 取得）
    message: 要發送的訊息內容
    """
    r = requests.post(f"{TG_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    })
    data = r.json()
    if data.get("ok"):
        return f"訊息已發送到 {chat_id}"
    return f"發送失敗：{data.get('description', '未知錯誤')}"


# ── Airtable Tools ─────────────────────────────────────────────

def _at_get(table_key: str, params: dict) -> dict:
    url = f"{AT_API}/{AT_BASE}/{AT_TABLES[table_key]}"
    r = requests.get(url, headers=AT_HEADERS, params=params)
    return r.json()

def _at_post(table_key: str, fields: dict) -> dict:
    url = f"{AT_API}/{AT_BASE}/{AT_TABLES[table_key]}"
    r = requests.post(url, headers=AT_HEADERS, json={"fields": fields})
    return r.json()

def _at_patch(table_key: str, record_id: str, fields: dict) -> dict:
    url = f"{AT_API}/{AT_BASE}/{AT_TABLES[table_key]}/{record_id}"
    r = requests.patch(url, headers=AT_HEADERS, json={"fields": fields})
    return r.json()

def _fmt_customer(rec: dict) -> str:
    f = rec.get("fields", {})
    lines = [f"  客戶：{f.get('客戶名稱','—')}  電話：{f.get('客戶電話','—')}"]
    if f.get("指定分店"):    lines.append(f"  分店：{f['指定分店']}")
    if f.get("服務進度"):    lines.append(f"  進度：{f['服務進度']}")
    if f.get("客戶LINE名稱"): lines.append(f"  LINE：{f['客戶LINE名稱']}")
    lines.append(f"  ID：{rec['id']}")
    return "\n".join(lines)

def _fmt_case(rec: dict) -> str:
    f = rec.get("fields", {})
    lines = [f"  案件：{f.get('案件編號','—')}  狀態：{f.get('案件狀態','—')}"]
    if f.get("損傷說明"):        lines.append(f"  說明：{f['損傷說明'][:80]}")
    if f.get("指定分店"):        lines.append(f"  分店：{f['指定分店']}")
    if f.get("實際到店報價"):    lines.append(f"  報價：{f['實際到店報價']}")
    if f.get("派單時間"):        lines.append(f"  派單：{f['派單時間']}")
    lines.append(f"  ID：{rec['id']}")
    return "\n".join(lines)


@mcp.tool()
def crm_search_customer(keyword: str) -> str:
    """
    在 Airtable 客戶資料表搜尋客戶。
    keyword: 客戶名稱、電話、LINE名稱（部分符合）
    """
    formula = f"OR(FIND('{keyword}',{{客戶名稱}}),FIND('{keyword}',{{客戶電話}}),FIND('{keyword}',{{客戶LINE名稱}}))"
    data = _at_get("客戶", {"filterByFormula": formula, "maxRecords": 10})
    records = data.get("records", [])
    if not records:
        return f"找不到符合「{keyword}」的客戶"
    lines = [f"找到 {len(records)} 位客戶：\n"]
    for rec in records:
        lines.append(_fmt_customer(rec))
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def crm_get_cases(status: str = "") -> str:
    """
    查詢 Airtable 案件記錄。
    status: 篩選案件狀態（如「待報價」「修復中」「已完成」），空白則回傳最新 20 筆
    """
    params = {"maxRecords": 20, "sort[0][field]": "派單時間", "sort[0][direction]": "desc"}
    if status:
        params["filterByFormula"] = f"{{案件狀態}}='{status}'"
    data = _at_get("案件", params)
    records = data.get("records", [])
    if not records:
        return f"找不到{'狀態為「'+status+'」的' if status else ''}案件"
    lines = [f"案件記錄（{len(records)} 筆）：\n"]
    for rec in records:
        lines.append(_fmt_case(rec))
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def crm_update_case(record_id: str, status: str = "", note: str = "", quote: str = "") -> str:
    """
    更新 Airtable 案件記錄。
    record_id: 案件的 Airtable ID（從 crm_get_cases 取得，格式 rec...）
    status: 新的案件狀態
    note: 損傷說明備註
    quote: 實際到店報價
    """
    fields = {}
    if status: fields["案件狀態"] = status
    if note:   fields["損傷說明"] = note
    if quote:  fields["實際到店報價"] = quote
    if not fields:
        return "請至少提供一個要更新的欄位（status / note / quote）"
    result = _at_patch("案件", record_id, fields)
    if result.get("id"):
        return f"案件 {record_id} 更新成功：{fields}"
    return f"更新失敗：{result}"


@mcp.tool()
def crm_add_customer(name: str, phone: str = "", line_name: str = "", branch: str = "") -> str:
    """
    在 Airtable 新增客戶資料。
    name: 客戶名稱（必填）
    phone: 電話號碼
    line_name: LINE 顯示名稱
    branch: 指定分店
    """
    fields = {"客戶名稱": name}
    if phone:     fields["客戶電話"] = phone
    if line_name: fields["客戶LINE名稱"] = line_name
    if branch:    fields["指定分店"] = branch
    result = _at_post("客戶", fields)
    if result.get("id"):
        return f"客戶「{name}」已新增，ID：{result['id']}"
    return f"新增失敗：{result}"


@mcp.tool()
def crm_summary() -> str:
    """
    查詢 Airtable ECHO CRM 整體數據摘要：
    客戶總數、案件總數、各狀態案件數量。
    """
    customers = _at_get("客戶", {"fields[]": "客戶名稱"})
    cases     = _at_get("案件", {"fields[]": ["案件狀態"], "maxRecords": 200})

    total_customers = len(customers.get("records", []))
    case_records    = cases.get("records", [])
    status_count: dict = {}
    for rec in case_records:
        s = rec.get("fields", {}).get("案件狀態", "未設定")
        status_count[s] = status_count.get(s, 0) + 1

    now   = datetime.now(TW)
    lines = [f"ECHO CRM 數據摘要（{now.strftime('%m/%d %H:%M')}）\n"]
    lines.append(f"客戶總數：{total_customers} 位")
    lines.append(f"案件總數：{len(case_records)} 筆\n")
    lines.append("案件狀態分佈：")
    for s, c in sorted(status_count.items(), key=lambda x: -x[1]):
        lines.append(f"  {s}：{c} 筆")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
