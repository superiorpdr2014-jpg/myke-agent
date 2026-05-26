import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import json
from datetime import datetime, timezone

TOKEN = "EAAQ6o3ckxjABRs5zHPoCeEMWNrqSVKtmZB4n3a1ncNbrUmcot4qvzkQ98pWI6xt2ZBPIFmLhouUDxWkEcAZANNrgRudYmiFDBsgnTCZB4tIKLVsaWmZAGSpQ7GnNpw3Vdyo3guk0ZBrwl3JSrfCUrXnOTcptUpQRdRbqvGma3XGxtzQW48M9ZARM1yJuMZAfZCNT8lMbxKD1uGyEhSxSOx88MK4nL9ZBIc450kgssUloZB62VDIqehHpsYvWek3ZB0jxZASNYntA3CnyuEWX7KUyjXrtSGfMMRwZDZD"
IG_ID = "17841405319139027"
BASE = "https://graph.facebook.com/v25.0"

def get_account_info():
    r = requests.get(f"{BASE}/{IG_ID}", params={
        "fields": "username,followers_count,media_count",
        "access_token": TOKEN
    })
    return r.json()

def get_recent_posts(limit=10):
    r = requests.get(f"{BASE}/{IG_ID}/media", params={
        "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink",
        "limit": limit,
        "access_token": TOKEN
    })
    return r.json().get("data", [])

def get_insights():
    r = requests.get(f"{BASE}/{IG_ID}/insights", params={
        "metric": "impressions,reach,profile_views,follower_count",
        "period": "day",
        "access_token": TOKEN
    })
    return r.json().get("data", [])

def generate_report():
    print(f"\n{'='*50}")
    print(f"📊 @superiorpdrtaiwan IG 日報 — {datetime.now().strftime('%Y/%m/%d')}")
    print(f"{'='*50}")

    info = get_account_info()
    print(f"\n👤 帳號狀態")
    print(f"   粉絲：{info.get('followers_count', 'N/A'):,}")
    print(f"   總貼文：{info.get('media_count', 'N/A')}")

    posts = get_recent_posts(5)
    print(f"\n📱 最新 5 則貼文")
    for i, p in enumerate(posts, 1):
        ts = datetime.fromisoformat(p['timestamp'].replace('+0000', '+00:00'))
        ts_tw = ts.astimezone(timezone.utc)
        caption = p.get('caption', '')[:50].replace('\n', ' ')
        print(f"\n   [{i}] {ts_tw.strftime('%m/%d')} {p['media_type']}")
        print(f"   ❤️  {p.get('like_count', 0):,}  💬 {p.get('comments_count', 0)}")
        print(f"   {caption}...")
        print(f"   🔗 {p.get('permalink', '')}")

    insights = get_insights()
    if insights:
        print(f"\n📈 昨日洞察")
        for m in insights:
            print(f"   {m['name']}: {m['values'][-1]['value'] if m.get('values') else 'N/A'}")

    print(f"\n{'='*50}\n")

if __name__ == "__main__":
    generate_report()
