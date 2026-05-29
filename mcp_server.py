"""
Myke Agent MCP Server
讓 Claude 桌面 app 直接執行晨報、IG 數據、行事曆查詢、Telegram、Airtable CRM
"""
import sys, os, json, time, sqlite3, shutil, tomllib, pathlib, imaplib, email, textwrap
from email.header import decode_header

# Ensure working directory is Myke_Agent
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(AGENT_DIR)
sys.path.insert(0, AGENT_DIR)

import requests
from datetime import datetime, timezone, timedelta
from fastmcp import FastMCP

mcp = FastMCP("Myke Agent - SUPERIOR PDR")

# ── Secrets（從 .streamlit/secrets.toml 讀取）────────────────
_secrets_path = pathlib.Path(AGENT_DIR) / ".streamlit" / "secrets.toml"
_secrets = tomllib.loads(_secrets_path.read_text(encoding="utf-8"))

# ── Config ────────────────────────────────────────────────────
TOKEN  = _secrets.get("META_TOKEN", "")
IG_ID  = "17841405319139027"
BASE   = "https://graph.facebook.com/v25.0"

CALENDAR_URL = "https://timetreeapp.com/calendars/TEjWVnDzaE17"
AUTH_FILE    = os.path.join(AGENT_DIR, "timetree_auth.json")
COOKIES_DB   = r"C:\Users\User\AppData\Roaming\wmux\Network\Cookies"
COOKIES_TMP  = r"C:\Users\User\AppData\Local\Temp\wmux_cookies_tmp"

# ── Telegram ─────────────────────────────────────────────────
TG_TOKEN  = _secrets.get("TG_TOKEN", "")
TG_API    = f"https://api.telegram.org/bot{TG_TOKEN}"

# ── Gmail ─────────────────────────────────────────────────────
GMAIL_USER = _secrets.get("GMAIL_USER", "")
GMAIL_PASS = _secrets.get("GMAIL_PASS", "")
GMAIL_INQUIRY_KW = [
    "凹痕", "修復", "報價", "pdr", "板金", "保險桿", "掉漆", "維修",
    "dent", "repair", "quote", "estimate", "appointment", "booking",
    "合作", "詢問", "inquiry", "collaboration",
]
GMAIL_SKIP_SENDERS = [
    "noreply", "no-reply", "netflix", "paypal", "amazon", "strava",
    "dropbox", "openai", "anthropic", "ups", "dbs.com", "sinopac",
    "americanexpress", "amex", "edm", "shopifyemail",
]

# ── Airtable ──────────────────────────────────────────────────
AT_TOKEN  = _secrets["AT_TOKEN"]
AT_BASE   = _secrets["AT_BASE"]
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

    # Gmail
    lines.append(f"\n{'─'*54}")
    lines.append("【Gmail】soulbreakin@gmail.com")
    if GMAIL_USER and GMAIL_PASS:
        try:
            g_emails = _gmail_fetch(hours=24, max_results=30)
            inquiries = [e for e in g_emails if e["is_inquiry"]]
            total = len(g_emails)
            skipped = sum(1 for e in g_emails if e["is_skip"])
            lines.append(f"\n  過去 24h 共 {total} 封  |  廣告略過 {skipped}  |  詢問 {len(inquiries)}")
            if inquiries:
                lines.append("\n  🔔 需要關注：")
                for e in inquiries:
                    lines.append(f"    • {e['sender'][:40]}")
                    lines.append(f"      {e['subject']}")
                    lines.append(f"      {e['snippet'][:120]}")
            else:
                lines.append("  暫無客戶/業務詢問")
        except Exception as e:
            lines.append(f"  Gmail 讀取失敗：{e}")
    else:
        lines.append("  （尚未設定）")

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
def crm_set_quote(customer_id: str, case_id: str, price_text: str) -> str:
    """
    真人報價後手動觸發：更新客戶服務進度為「已報價」，並填入案件網路區間報價。
    customer_id: 客戶 Airtable record ID
    case_id:     案件 Airtable record ID
    price_text:  報價文字，支援格式：
                   1500-2500 / $1500-$2500 / 1500~2500 / $1500~$2500 / $2500
    """
    import re
    range_re  = re.compile(r'(?:NT\$|\$)?(\d{3,6})\s*[-~]\s*(?:NT\$|\$)?(\d{3,6})')
    single_re = re.compile(r'(?:NT\$|\$)(\d{3,6})')

    m = range_re.search(price_text)
    if m:
        quote = f"NT${m.group(1)}-NT${m.group(2)}"
    else:
        m = single_re.search(price_text)
        if m:
            quote = f"NT${m.group(1)}"
        else:
            return f"無法辨識報價格式：「{price_text}」\n支援格式：1500-2500 / $1500-$2500 / 1500~2500 / $2500"

    r1 = _at_patch("客戶", customer_id, {"服務進度": "已報價"})
    r2 = _at_patch("案件", case_id,    {"網路區間報價": quote})

    if r1.get("id") and r2.get("id"):
        return f"報價已記錄：{quote}\n客戶服務進度 → 已報價"
    return f"部分更新失敗：客戶={r1}  案件={r2}"


@mcp.tool()
def crm_find_or_create_vehicle(customer_id: str, brand: str, model: str,
                                year: int = 0, plate: str = "") -> str:
    """
    查找客戶是否已有相同廠牌+型號的車輛，有則回傳現有記錄 ID，沒有才新建。
    避免重複建立車輛記錄。
    customer_id: 客戶 Airtable record ID（rec...）
    brand: 廠牌（如 Toyota）
    model: 型號（如 Camry）
    year: 年分（選填）
    plate: 車牌號碼（選填）
    """
    # ARRAYJOIN returns display names not IDs — filter by brand+model only,
    # then match customerId in Python to avoid false misses.
    formula = f"AND(LOWER({{廠牌}})='{brand.lower()}',LOWER({{型號}})='{model.lower()}')"
    data = _at_get("車輛", {"filterByFormula": formula, "maxRecords": 100})
    existing = [r for r in data.get("records", [])
                if customer_id in r.get("fields", {}).get("所屬客戶", [])]
    if existing:
        rec = existing[0]
        f = rec.get("fields", {})
        return (f"車輛已存在，ID：{rec['id']}\n"
                f"  {f.get('廠牌','')} {f.get('型號','')}  車牌：{f.get('車牌號碼','—')}")

    fields: dict = {
        "所屬客戶": [customer_id],
        "廠牌": brand,
        "型號": model,
    }
    if year:  fields["年分"]   = year
    if plate: fields["車牌號碼"] = plate
    result = _at_post("車輛", fields)
    if result.get("id"):
        return f"新建車輛成功，ID：{result['id']}\n  {brand} {model}  車牌：{plate or '—'}"
    return f"新建車輛失敗：{result}"


@mcp.tool()
def crm_create_case(customer_id: str, vehicle_id: str = "",
                    branch: str = "", damage: str = "", price_range: str = "") -> str:
    """
    建立新案件，並自動連結客戶與車輛。
    customer_id: 客戶 record ID（必填）
    vehicle_id:  車輛 record ID（建議填，從 crm_find_or_create_vehicle 取得）
    branch:      指定分店（台北士林店 / 新北中和店 / 新北板橋店 / 台北濱江店 /
                            桃園平鎮店 / 新竹竹北店 / 台中南屯店 / 高雄楠梓電）
    damage:      損傷說明
    price_range: 網路區間報價
    """
    # If no branch given, inherit from customer record
    resolved_branch = branch
    if not resolved_branch:
        cust = _at_get("客戶", {"filterByFormula": f"RECORD_ID()='{customer_id}'"})
        recs = cust.get("records", [])
        if recs:
            resolved_branch = recs[0].get("fields", {}).get("指定分店", "")

    fields: dict = {"所屬客戶": [customer_id]}
    if vehicle_id:       fields["所屬車輛"]    = [vehicle_id]
    if resolved_branch:  fields["指定分店"]    = resolved_branch
    if damage:           fields["損傷說明"]    = damage
    if price_range:      fields["網路區間報價"] = price_range

    result = _at_post("案件", fields)
    if result.get("id"):
        case_no = result.get("fields", {}).get("案件編號", "—")
        return (f"案件建立成功！案件編號：{case_no}\n"
                f"  ID：{result['id']}\n"
                f"  客戶：{customer_id}  車輛：{vehicle_id or '未指定'}\n"
                f"  分店：{resolved_branch or '未指定'}")
    return f"建立案件失敗：{result}"


@mcp.tool()
def crm_dedup_vehicles() -> str:
    """
    掃描車輛資料表，找出同一客戶下廠牌+型號重複的車輛記錄並列出。
    只回報，不刪除。確認後可執行 airtable_dedup_vehicles.py --execute 實際清除。
    """
    def fetch_all_cars():
        records, offset = [], None
        while True:
            params = {"pageSize": 100}
            if offset:
                params["offset"] = offset
            r = requests.get(f"{AT_API}/{AT_BASE}/{AT_TABLES['車輛']}",
                             headers=AT_HEADERS, params=params)
            data = r.json()
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
        return records

    cars = fetch_all_cars()
    groups: dict = {}
    for car in cars:
        flds = car.get("fields", {})
        cust = (flds.get("所屬客戶") or ["無客戶"])[0]
        key  = (cust, flds.get("廠牌","").strip(), flds.get("型號","").strip())
        groups.setdefault(key, []).append(car)

    dups = {k: v for k, v in groups.items() if len(v) > 1}
    if not dups:
        return f"車輛資料共 {len(cars)} 筆，未發現重複記錄。"

    lines = [f"車輛資料共 {len(cars)} 筆，發現 {len(dups)} 組重複：\n"]
    total_extra = 0
    for (cust, brand, model), recs in dups.items():
        extra = len(recs) - 1
        total_extra += extra
        plates = [r.get("fields",{}).get("車牌號碼","—") for r in recs]
        lines.append(f"  {brand} {model}  ×{len(recs)} 筆  車牌：{', '.join(plates)}")
    lines.append(f"\n共 {total_extra} 筆多餘記錄，執行 airtable_dedup_vehicles.py --execute 可清除。")
    return "\n".join(lines)


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


# ── Gmail helpers ─────────────────────────────────────────────
def _gmail_decode(value: str) -> str:
    parts = decode_header(value or "")
    out = []
    for b, enc in parts:
        if isinstance(b, bytes):
            out.append(b.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(b)
    return "".join(out)

def _gmail_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace") if payload else ""
    return ""

def _gmail_is_skip(sender: str) -> bool:
    s = sender.lower()
    return any(kw in s for kw in GMAIL_SKIP_SENDERS)

def _gmail_is_inquiry(subject: str, body: str) -> bool:
    text = (subject + " " + body[:500]).lower()
    return any(kw in text for kw in GMAIL_INQUIRY_KW)

def _gmail_fetch(hours: int = 24, max_results: int = 50) -> list:
    conn = imaplib.IMAP4_SSL("imap.gmail.com")
    conn.login(GMAIL_USER, GMAIL_PASS)
    conn.select("INBOX")
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%d-%b-%Y")
    _, data = conn.search(None, f'(SINCE "{since}")')
    uid_list = data[0].split() if data[0] else []
    uid_list = uid_list[-max_results:][::-1]
    results = []
    for uid in uid_list:
        _, msg_data = conn.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        subject = _gmail_decode(msg.get("Subject", "(no subject)"))
        sender  = _gmail_decode(msg.get("From", ""))
        date_str = msg.get("Date", "")
        body = _gmail_body(msg)
        results.append({
            "uid": uid.decode(),
            "subject": subject,
            "sender": sender,
            "date": date_str,
            "snippet": textwrap.shorten(body.strip(), width=250, placeholder="..."),
            "body": body,
            "is_inquiry": _gmail_is_inquiry(subject, body) and not _gmail_is_skip(sender),
            "is_skip": _gmail_is_skip(sender),
        })
    conn.logout()
    return results


@mcp.tool()
def email_summary(hours: int = 24) -> str:
    """
    查看 Jay 的 Gmail（soulbreakin@gmail.com）最近的信件摘要。
    自動分類：客戶/業務詢問優先顯示，廣告/系統信件過濾。
    hours: 查詢過去幾小時（預設 24）
    """
    if not GMAIL_USER or not GMAIL_PASS:
        return "Gmail 尚未設定，請在 secrets.toml 加入 GMAIL_USER 和 GMAIL_PASS。"
    try:
        emails = _gmail_fetch(hours=hours)
    except Exception as e:
        return f"Gmail 連線失敗：{e}"

    if not emails:
        return f"過去 {hours} 小時沒有新信件。"

    inquiries = [e for e in emails if e["is_inquiry"]]
    normal    = [e for e in emails if not e["is_inquiry"] and not e["is_skip"]]
    skipped   = [e for e in emails if e["is_skip"]]

    now = datetime.now(TW)
    lines = [f"Gmail 信件摘要（過去 {hours}h）— {now.strftime('%m/%d %H:%M')}",
             f"共 {len(emails)} 封  |  詢問 {len(inquiries)}  |  一般 {len(normal)}  |  略過廣告 {len(skipped)}\n"]

    if inquiries:
        lines.append(f"🔔 客戶 / 業務詢問（{len(inquiries)} 封）")
        lines.append("─" * 50)
        for e in inquiries:
            lines.append(f"寄件：{e['sender']}")
            lines.append(f"主旨：{e['subject']}")
            lines.append(f"時間：{e['date'][:30]}")
            lines.append(f"內容：{e['snippet']}")
            lines.append("")

    if normal:
        lines.append(f"📬 一般信件（{len(normal)} 封）")
        lines.append("─" * 50)
        for e in normal:
            lines.append(f"  • {e['date'][:20]}  {e['sender'][:35]}  |  {e['subject']}")

    return "\n".join(lines)


@mcp.tool()
def email_draft_reply(uid: str) -> str:
    """
    根據指定 email UID 產生繁體中文回覆草稿建議。
    uid：從 email_summary 取得的信件 UID。
    """
    if not GMAIL_USER or not GMAIL_PASS:
        return "Gmail 尚未設定。"
    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.login(GMAIL_USER, GMAIL_PASS)
        conn.select("INBOX")
        _, msg_data = conn.fetch(uid.encode(), "(RFC822)")
        conn.logout()
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        subject = _gmail_decode(msg.get("Subject", ""))
        sender  = _gmail_decode(msg.get("From", ""))
        body    = _gmail_body(msg)
        excerpt = textwrap.shorten(body.strip(), width=500, placeholder="...")
    except Exception as e:
        return f"讀取信件失敗：{e}"

    return (
        f"【回覆草稿建議】\n"
        f"收件人：{sender}\n"
        f"主旨：Re: {subject}\n\n"
        f"--- 原始信件摘要 ---\n{excerpt}\n\n"
        f"--- 請根據以上內容，以繁體中文、代表 SUPERIOR PDR Jay 的口吻，產生專業且友善的回覆草稿 ---"
    )


@mcp.tool()
def email_mark_read(uid: str) -> str:
    """將指定 UID 的 Gmail 信件標記為已讀。"""
    if not GMAIL_USER or not GMAIL_PASS:
        return "Gmail 尚未設定。"
    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com")
        conn.login(GMAIL_USER, GMAIL_PASS)
        conn.select("INBOX")
        conn.store(uid.encode(), "+FLAGS", "\\Seen")
        conn.logout()
        return f"UID {uid} 已標記為已讀。"
    except Exception as e:
        return f"操作失敗：{e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
