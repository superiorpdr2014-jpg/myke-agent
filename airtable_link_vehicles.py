"""
自動把案件記錄的「所屬車輛」欄位補上。
邏輯：
  - 一個客戶只有 1 台車 → 自動連結
  - 一個客戶有多台車   → 列出，需手動選
  - 案件已有車輛       → 跳過
"""

import requests, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import tomllib, pathlib
_secrets = tomllib.loads(pathlib.Path(__file__).parent.joinpath(".streamlit/secrets.toml").read_text())
TOKEN   = _secrets["AT_TOKEN"]
BASE    = _secrets["AT_BASE"]
API     = f"https://api.airtable.com/v0/{BASE}"
HDR     = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

TBL_CASE    = "tblKQfzgfLg8AYiuQ"   # 案件記錄
TBL_CAR     = "tblck9rVDwxf3oeoE"   # 車輛資料
FLD_CASE_CUSTOMER = "fldgh3oVna0XGXvAj"   # 案件.所屬客戶
FLD_CASE_CAR      = "fldVRFnHODo6RaoPN"   # 案件.所屬車輛
FLD_CAR_CUSTOMER  = "fldU33OxpepoS0CJo"   # 車輛.所屬客戶


def fetch_all(table_id: str) -> list:
    records, offset = [], None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        r = requests.get(f"{API}/{table_id}", headers=HDR, params=params)
        data = r.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            break
    return records


def main():
    print("=== 讀取案件記錄 ===")
    cases = fetch_all(TBL_CASE)
    print(f"共 {len(cases)} 筆案件")

    print("\n=== 讀取車輛資料 ===")
    cars = fetch_all(TBL_CAR)
    print(f"共 {len(cars)} 台車輛")

    # 建立 customer_id → [car_record_id] 對照表
    customer_to_cars: dict[str, list[str]] = {}
    car_labels: dict[str, str] = {}
    for car in cars:
        car_id = car["id"]
        fields = car.get("fields", {})
        label = fields.get("車輛識別名稱", car_id)
        plate = fields.get("車牌號碼", "")
        car_labels[car_id] = f"{label} ({plate})" if plate else label
        for cust_id in fields.get("所屬客戶", []):
            customer_to_cars.setdefault(cust_id, []).append(car_id)

    auto_linked   = []
    need_manual   = []
    already_done  = []
    no_vehicle    = []

    for case in cases:
        case_id = case["id"]
        fields  = case.get("fields", {})
        case_no = fields.get("案件編號", case_id)

        # 已有車輛 → 跳過
        if fields.get("所屬車輛"):
            already_done.append(case_no)
            continue

        cust_list = fields.get("所屬客戶", [])
        if not cust_list:
            no_vehicle.append(f"案件 #{case_no} — 沒有所屬客戶")
            continue

        cust_id = cust_list[0]
        car_ids = customer_to_cars.get(cust_id, [])

        if len(car_ids) == 0:
            no_vehicle.append(f"案件 #{case_no} — 客戶尚無車輛資料")
        elif len(car_ids) == 1:
            # 自動連結
            car_id = car_ids[0]
            payload = {"fields": {"所屬車輛": [car_id]}}
            resp = requests.patch(f"{API}/{TBL_CASE}/{case_id}", headers=HDR, json=payload)
            if resp.status_code == 200:
                auto_linked.append(f"案件 #{case_no} → {car_labels[car_id]}")
            else:
                auto_linked.append(f"案件 #{case_no} → 更新失敗：{resp.text}")
            time.sleep(0.25)  # 避免打爆 API rate limit
        else:
            options = ", ".join([car_labels[c] for c in car_ids])
            need_manual.append(f"案件 #{case_no} — 客戶有多台車，請手動選：{options}")

    # ── 輸出結果 ────────────────────────────────────────
    print(f"\n✅ 自動連結成功（{len(auto_linked)} 筆）：")
    for line in auto_linked:
        print(f"   {line}")

    print(f"\n⚠️  需要手動處理（{len(need_manual)} 筆）：")
    for line in need_manual:
        print(f"   {line}")

    print(f"\n❌ 無車輛資料（{len(no_vehicle)} 筆）：")
    for line in no_vehicle:
        print(f"   {line}")

    print(f"\n⏭️  已有車輛，跳過（{len(already_done)} 筆）：{already_done}")


if __name__ == "__main__":
    main()
