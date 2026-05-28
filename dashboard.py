import requests
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone, timedelta

# ── Config（從 st.secrets 讀取，本地用 .streamlit/secrets.toml）─
AT_TOKEN  = st.secrets["AT_TOKEN"]
AT_BASE   = st.secrets["AT_BASE"]
AT_API    = "https://api.airtable.com/v0"
AT_TABLES = {
    "客戶資料": "tblyppP7rIazjfo1o",
    "車輛資料": "tblck9rVDwxf3oeoE",
    "案件記錄": "tblKQfzgfLg8AYiuQ",
}
AT_HEADERS = {"Authorization": f"Bearer {AT_TOKEN}"}

TG_TOKEN = st.secrets["TG_TOKEN"]
TG_API   = f"https://api.telegram.org/bot{TG_TOKEN}"
TW       = timezone(timedelta(hours=8))

REFRESH_SEC = 30  # auto-refresh every 30 seconds

# ── Page setup ────────────────────────────────────────────────
st.set_page_config(
    page_title="SUPERIOR PDR · Myke Dashboard",
    page_icon="🔧",
    layout="wide",
)

# Auto-refresh counter
count = st_autorefresh(interval=REFRESH_SEC * 1000, key="dashboard_refresh")

# ── Data fetchers ─────────────────────────────────────────────
@st.cache_data(ttl=REFRESH_SEC)
def fetch_airtable(table_name: str) -> pd.DataFrame:
    table_id = AT_TABLES[table_name]
    records, offset = [], None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        r = requests.get(f"{AT_API}/{AT_BASE}/{table_id}", headers=AT_HEADERS, params=params)
        data = r.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    if not records:
        return pd.DataFrame()
    rows = []
    for rec in records:
        row = {"_id": rec["id"]}
        row.update(rec.get("fields", {}))
        rows.append(row)
    return pd.DataFrame(rows)

@st.cache_data(ttl=REFRESH_SEC)
def fetch_telegram_messages(limit: int = 50) -> list:
    r = requests.get(f"{TG_API}/getUpdates", params={"limit": limit, "allowed_updates": ["message"]})
    data = r.json()
    if not data.get("ok"):
        return []
    messages = []
    for u in reversed(data.get("result", [])):
        msg = u.get("message") or u.get("channel_post") or {}
        if not msg:
            continue
        chat   = msg.get("chat", {})
        sender = msg.get("from", {})
        ts     = datetime.fromtimestamp(msg.get("date", 0), tz=TW)
        messages.append({
            "時間":   ts.strftime("%m/%d %H:%M"),
            "群組":   chat.get("title") or chat.get("username") or "私訊",
            "發話人": (sender.get("first_name") or "") + " " + (sender.get("last_name") or ""),
            "訊息":   msg.get("text", "[非文字]")[:200],
            "chat_id": chat.get("id", ""),
        })
    return messages

# ── Header ────────────────────────────────────────────────────
now = datetime.now(TW)
col_title, col_time = st.columns([3, 1])
with col_title:
    st.markdown("## 🔧 SUPERIOR PDR · Myke Dashboard")
with col_time:
    st.markdown(f"<div style='text-align:right;padding-top:12px;color:#888'>"
                f"更新：{now.strftime('%H:%M:%S')}　每 {REFRESH_SEC}s 自動刷新</div>",
                unsafe_allow_html=True)

st.divider()

# ── Telegram ──────────────────────────────────────────────────
st.markdown("### 💬 Telegram · ECHO Bot 即時訊息")

messages = fetch_telegram_messages(50)
if messages:
    df_tg = pd.DataFrame(messages).drop(columns=["chat_id"])
    st.dataframe(
        df_tg,
        use_container_width=True,
        hide_index=True,
        column_config={
            "時間":   st.column_config.TextColumn("時間",   width=90),
            "群組":   st.column_config.TextColumn("群組",   width=140),
            "發話人": st.column_config.TextColumn("發話人", width=110),
            "訊息":   st.column_config.TextColumn("訊息"),
        }
    )
else:
    st.info("目前無訊息（Bot 尚未收到任何對話）")

st.divider()

# ── Airtable Tables ───────────────────────────────────────────
st.markdown("### 📋 ECHO CRM · Airtable 資料表")

tab1, tab2, tab3 = st.tabs(["👤 客戶資料", "🚗 車輛資料", "📁 案件記錄"])

# ── 客戶資料 ─────────────────────────────────────────────────
with tab1:
    df = fetch_airtable("客戶資料")
    if df.empty:
        st.info("客戶資料表為空")
    else:
        # Drop internal link columns
        display_cols = [c for c in df.columns if c != "_id" and not isinstance(df[c].iloc[0], list)]
        st.metric("客戶總數", len(df))
        search = st.text_input("搜尋客戶（姓名 / 電話 / LINE）", key="search_customer")
        if search:
            mask = df.apply(lambda row: row.astype(str).str.contains(search, case=False, na=False).any(), axis=1)
            df = df[mask]
            st.caption(f"找到 {len(df)} 筆")
        st.dataframe(
            df[display_cols] if display_cols else df,
            use_container_width=True,
            hide_index=True,
        )

# ── 車輛資料 ─────────────────────────────────────────────────
with tab2:
    df = fetch_airtable("車輛資料")
    if df.empty:
        st.info("車輛資料表為空")
    else:
        display_cols = [c for c in df.columns if c != "_id" and not isinstance(df[c].iloc[0], list)]
        st.metric("車輛總數", len(df))
        search = st.text_input("搜尋車輛（車牌 / 廠牌 / 型號）", key="search_vehicle")
        if search:
            mask = df.apply(lambda row: row.astype(str).str.contains(search, case=False, na=False).any(), axis=1)
            df = df[mask]
            st.caption(f"找到 {len(df)} 筆")
        st.dataframe(
            df[display_cols] if display_cols else df,
            use_container_width=True,
            hide_index=True,
        )

# ── 案件記錄 ─────────────────────────────────────────────────
with tab3:
    df = fetch_airtable("案件記錄")
    if df.empty:
        st.info("案件記錄表為空")
    else:
        display_cols = [c for c in df.columns if c != "_id" and not isinstance(df[c].iloc[0], list)]

        col1, col2, col3 = st.columns(3)
        col1.metric("案件總數", len(df))
        if "案件狀態" in df.columns:
            status_counts = df["案件狀態"].value_counts()
            col2.metric("進行中", int(status_counts.get("修復中", 0)))
            col3.metric("已完成", int(status_counts.get("已完成", 0)))

            status_filter = st.selectbox(
                "篩選狀態",
                ["全部"] + list(df["案件狀態"].dropna().unique()),
                key="case_status"
            )
            if status_filter != "全部":
                df = df[df["案件狀態"] == status_filter]

        search = st.text_input("搜尋案件", key="search_case")
        if search:
            mask = df.apply(lambda row: row.astype(str).str.contains(search, case=False, na=False).any(), axis=1)
            df = df[mask]
            st.caption(f"找到 {len(df)} 筆")

        st.dataframe(
            df[display_cols] if display_cols else df,
            use_container_width=True,
            hide_index=True,
        )

# ── Footer ────────────────────────────────────────────────────
st.markdown(
    "<div style='text-align:center;color:#aaa;margin-top:20px;font-size:12px'>"
    "Myke Agent Dashboard · SUPERIOR PDR · 資料來源：Airtable + Telegram</div>",
    unsafe_allow_html=True
)
