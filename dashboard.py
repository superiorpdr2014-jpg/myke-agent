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

TW = timezone(timedelta(hours=8))

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

# ── Airtable Tables ───────────────────────────────────────────
st.markdown("### 📋 ECHO CRM · Airtable 資料表")

tab1, tab2, tab3 = st.tabs(["👤 客戶資料", "🚗 車輛資料", "📁 案件記錄"])

STATUS_COLORS = {
    "已派單": "#3b82f6",
    "已預約": "#f59e0b",
    "諮詢中": "#8b5cf6",
    "修復中": "#f97316",
    "已完成": "#22c55e",
    "已取消": "#ef4444",
    "None":   "#9ca3af",
}

def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    """Convert linked record IDs to counts, format timestamps."""
    for col in df.columns:
        if col == "_id":
            continue
        # Linked records → show count
        if df[col].apply(lambda v: isinstance(v, list)).any():
            df[col] = df[col].apply(
                lambda v: f"{len(v)} 筆" if isinstance(v, list) and v else ("—" if isinstance(v, list) else v)
            )
        # ISO timestamps → Taiwan time readable
        if df[col].dtype == object:
            sample = df[col].dropna().head(5).astype(str)
            if sample.str.match(r"\d{4}-\d{2}-\d{2}T").any():
                def fmt_ts(v):
                    try:
                        dt = pd.to_datetime(v, utc=True).tz_convert("Asia/Taipei")
                        return dt.strftime("%Y/%m/%d %H:%M")
                    except Exception:
                        return v
                df[col] = df[col].apply(lambda v: fmt_ts(v) if pd.notna(v) else "—")
    return df

def style_status(val):
    color = STATUS_COLORS.get(str(val), STATUS_COLORS["None"])
    return f"background-color:{color}22; color:{color}; font-weight:600; border-radius:4px; padding:2px 6px;"

# ── 客戶資料 ─────────────────────────────────────────────────
with tab1:
    df = fetch_airtable("客戶資料")
    if df.empty:
        st.info("客戶資料表為空")
    else:
        df = clean_df(df)

        # Sort by 最後更新時間 desc
        if "最後更新時間" in df.columns:
            df = df.sort_values("最後更新時間", ascending=False)

        all_cols = [c for c in df.columns if c != "_id"]
        # Move 客戶LINE名稱 to position 1 (second column)
        if "客戶LINE名稱" in all_cols:
            all_cols.remove("客戶LINE名稱")
            all_cols.insert(1, "客戶LINE名稱")
        display_cols = all_cols
        st.metric("客戶總數", len(df))
        search = st.text_input("搜尋客戶（姓名 / 電話 / LINE）", key="search_customer")
        if search:
            mask = df.apply(lambda row: row.astype(str).str.contains(search, case=False, na=False).any(), axis=1)
            df = df[mask]
            st.caption(f"找到 {len(df)} 筆")

        styled = df[display_cols]
        if "服務進度" in styled.columns:
            st.dataframe(
                styled.style.map(style_status, subset=["服務進度"]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.dataframe(styled, use_container_width=True, hide_index=True)

# ── 車輛資料 ─────────────────────────────────────────────────
with tab2:
    df = fetch_airtable("車輛資料")
    if df.empty:
        st.info("車輛資料表為空")
    else:
        df = clean_df(df)
        display_cols = [c for c in df.columns if c != "_id"]
        st.metric("車輛總數", len(df))
        search = st.text_input("搜尋車輛（車牌 / 廠牌 / 型號）", key="search_vehicle")
        if search:
            mask = df.apply(lambda row: row.astype(str).str.contains(search, case=False, na=False).any(), axis=1)
            df = df[mask]
            st.caption(f"找到 {len(df)} 筆")
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

# ── 案件記錄 ─────────────────────────────────────────────────
with tab3:
    df = fetch_airtable("案件記錄")
    if df.empty:
        st.info("案件記錄表為空")
    else:
        df = clean_df(df)
        if "派單時間" in df.columns:
            df = df.sort_values("派單時間", ascending=False)
        display_cols = [c for c in df.columns if c != "_id"]

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

        styled = df[display_cols]
        if "案件狀態" in styled.columns:
            st.dataframe(
                styled.style.map(style_status, subset=["案件狀態"]),
                use_container_width=True, hide_index=True,
            )
        else:
            st.dataframe(styled, use_container_width=True, hide_index=True)

# ── Footer ────────────────────────────────────────────────────
st.markdown(
    "<div style='text-align:center;color:#aaa;margin-top:20px;font-size:12px'>"
    "Myke Agent Dashboard · SUPERIOR PDR · 資料來源：Airtable + Telegram</div>",
    unsafe_allow_html=True
)
