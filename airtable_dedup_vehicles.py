"""
車輛資料去重工具
找出同一客戶下廠牌+型號相同的重複車輛，列出並自動刪除多餘的。
執行前先用 --dry-run 預覽，確認後再去掉 --dry-run 實際刪除。
"""

import sys, io, requests, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import tomllib, pathlib
_secrets = tomllib.loads(pathlib.Path(__file__).parent.joinpath(".streamlit/secrets.toml").read_text())
TOKEN  = _secrets["AT_TOKEN"]
BASE   = _secrets["AT_BASE"]
API    = f"https://api.airtable.com/v0/{BASE}"
HDR    = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
TBL_CAR  = "tblck9rVDwxf3oeoE"
TBL_CASE = "tblKQfzgfLg8AYiuQ"


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


def main(dry_run: bool):
    mode = "[預覽模式 DRY RUN]" if dry_run else "[實際執行]"
    print(f"=== 車輛去重 {mode} ===\n")

    cars  = fetch_all(TBL_CAR)
    cases = fetch_all(TBL_CASE)

    # 哪些車輛有被案件引用？
    car_in_cases: set[str] = set()
    for case in cases:
        for car_id in case.get("fields", {}).get("所屬車輛", []):
            car_in_cases.add(car_id)

    # 以 (customer_id, 廠牌, 型號) 分組
    groups: dict[tuple, list] = {}
    for car in cars:
        flds = car.get("fields", {})
        cust = (flds.get("所屬客戶") or [""])[0]
        key  = (cust, flds.get("廠牌","").strip(), flds.get("型號","").strip())
        groups.setdefault(key, []).append(car)

    dups = {k: v for k, v in groups.items() if len(v) > 1}

    if not dups:
        print("沒有發現重複車輛！")
        return

    print(f"發現 {len(dups)} 組重複，共 {sum(len(v) for v in dups.values())} 筆記錄\n")

    keep_count   = 0
    delete_ids   = []
    no_cust_dups = []

    for (cust_id, brand, model), recs in dups.items():
        label = f"{brand} {model}" if (brand or model) else "(無廠牌/型號)"
        cust_label = cust_id or "(無客戶)"

        # 優先保留有案件引用的那筆，或有車牌的那筆，其餘刪除
        has_case = [r for r in recs if r["id"] in car_in_cases]
        has_plate = [r for r in recs if r.get("fields", {}).get("車牌號碼")]

        if has_case:
            keeper = has_case[0]
        elif has_plate:
            keeper = has_plate[0]
        else:
            keeper = recs[0]

        to_delete = [r for r in recs if r["id"] != keeper["id"]]

        plate = keeper.get("fields", {}).get("車牌號碼", "無車牌")
        print(f"  [{label}]  客戶:{cust_label}")
        print(f"    保留：{keeper['id']} ({plate})")
        for r in to_delete:
            p = r.get("fields", {}).get("車牌號碼", "無車牌")
            flag = " ⚠️ 有案件引用！" if r["id"] in car_in_cases else ""
            print(f"    刪除：{r['id']} ({p}){flag}")
            delete_ids.append(r["id"])
        keep_count += 1
        print()

    print(f"共保留 {keep_count} 筆，刪除 {len(delete_ids)} 筆\n")

    if dry_run:
        print("👆 以上為預覽，確認沒問題後執行：")
        print("   python airtable_dedup_vehicles.py --execute\n")
        return

    # 實際刪除（Airtable 最多一次 10 筆）
    deleted = 0
    for i in range(0, len(delete_ids), 10):
        batch = delete_ids[i:i+10]
        params = "&".join(f"records[]={rid}" for rid in batch)
        r = requests.delete(f"{API}/{TBL_CAR}?{params}", headers=HDR)
        data = r.json()
        if "deletedRecords" in data:
            deleted += len(data["deletedRecords"])
            print(f"  已刪除 {deleted} 筆...")
        else:
            print(f"  刪除時發生錯誤：{data}")

    print(f"\n完成！共刪除 {deleted} 筆重複車輛記錄。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="實際執行刪除（預設為預覽模式）")
    args = parser.parse_args()
    main(dry_run=not args.execute)
