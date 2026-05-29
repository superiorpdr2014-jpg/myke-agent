"""
Build SUPERIOR_ECHO_Prompt_0529.docx
從 0526 版本新增：
  1. [SHOW_SERVICE_MENU]  — 取得稱呼後觸發服務選單字卡
  2. [SHOW_SERVICE_OPTIONS_PDR / _PAINT / _BUMPER] — 照片分析後觸發服務選項字卡
"""

import copy, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from lxml import etree

SRC  = r"C:\Users\User\Desktop\ECHO AI建置\SUPERIOR_ECHO_Prompt_0526.docx"
DEST = r"C:\Users\User\Desktop\ECHO AI建置\SUPERIOR_ECHO_Prompt_0529.docx"

doc = Document(SRC)

# ── helpers ──────────────────────────────────────────────────────────────────

def para_text(p):
    return "".join(r.text for r in p.runs)

def clone_style(src_para):
    """Return a new <w:p> element that copies pPr from src_para."""
    new_p = OxmlElement("w:p")
    if src_para._p.pPr is not None:
        new_p.append(copy.deepcopy(src_para._p.pPr))
    return new_p

def insert_paragraphs_before(ref_para, lines, bold_first=True):
    """Insert a block of paragraphs directly before ref_para in the body XML."""
    parent = ref_para._p.getparent()
    idx    = list(parent).index(ref_para._p)
    for i, line in enumerate(lines):
        new_p = OxmlElement("w:p")
        r     = OxmlElement("w:r")
        rPr   = OxmlElement("w:rPr")
        if i == 0 and bold_first:
            b = OxmlElement("w:b"); rPr.append(b)
        r.append(rPr)
        t = OxmlElement("w:t")
        t.text = line
        if line.startswith(" ") or line.endswith(" "):
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(t)
        new_p.append(r)
        parent.insert(idx + i, new_p)

def insert_paragraphs_after(ref_para, lines, bold_first=True):
    """Insert a block of paragraphs directly after ref_para in the body XML."""
    parent = ref_para._p.getparent()
    idx    = list(parent).index(ref_para._p)
    for i, line in enumerate(lines):
        new_p = OxmlElement("w:p")
        r     = OxmlElement("w:r")
        rPr   = OxmlElement("w:rPr")
        if i == 0 and bold_first:
            b = OxmlElement("w:b"); rPr.append(b)
        r.append(rPr)
        t = OxmlElement("w:t")
        t.text = line
        if line.startswith(" ") or line.endswith(" "):
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(t)
        new_p.append(r)
        parent.insert(idx + 1 + i, new_p)

# ── locate anchors ────────────────────────────────────────────────────────────

para_step3      = None   # 第三步，詢問車款廠牌與型號
para_photo_ask  = None   # 第六步，詢問照片…（anchor for service options insertion）
para_must_list  = None   # 必收清單 section

for p in doc.paragraphs:
    txt = para_text(p)
    if "第三步，詢問車款廠牌與型號" in txt and para_step3 is None:
        para_step3 = p
    if "第六步，詢問照片或補充照片" in txt and para_photo_ask is None:
        para_photo_ask = p
    if "必收清單，優先順序如下" in txt and para_must_list is None:
        para_must_list = p

print(f"step3      found: {para_step3 is not None}")
print(f"photo_ask  found: {para_photo_ask is not None}")
print(f"must_list  found: {para_must_list is not None}")

# ── INSERTION 1：[SHOW_SERVICE_MENU] — before 第三步 ──────────────────────────

SERVICE_MENU_BLOCK = [
    "━━━━━━━━━━",
    "【第二步半：顯示服務選單字卡 — 取得稱呼後立即觸發】",
    "━━━━━━━━━━",
    "",
    "當客戶提供稱呼後，ECHO 的下一則回覆必須引導客戶選擇服務類型，並在回覆最後一行加上：",
    "[SHOW_SERVICE_MENU]",
    "",
    "ECHO 回覆範例：",
    "「{稱呼}，你好。請問今天需要什麼服務呢？」",
    "",
    "[SHOW_SERVICE_MENU] 觸發規則：",
    "- 字卡包含三個選項：🔍 車輛凹痕評估 ｜ 📍 分店資訊查詢 ｜ 📞 客訴處理",
    "- 客戶點選「車輛凹痕評估」→ 繼續進入第三步（詢問車款）",
    "- 客戶點選「分店資訊查詢」→ ECHO 詢問需要哪家分店資訊並直接回答，不進入車輛評估流程",
    "- 客戶點選「客訴處理」→ ECHO 提供免付費客訴專線 0800-889-365，並在回覆最後加上 [SEND_TO_JAY]",
    "- 每段對話最多觸發一次",
    "- 客戶不會看到此標記，這是系統觸發圖卡用途",
    "",
    "注意：即使客戶在提供稱呼時已說明需求（如「我想問凹痕修復」），仍須顯示服務選單字卡，讓客戶透過按鈕確認。",
    "",
    "━━━━━━━━━━",
    "",
]

if para_step3:
    insert_paragraphs_before(para_step3, SERVICE_MENU_BLOCK, bold_first=False)
    print("✅ [SHOW_SERVICE_MENU] 插入完成")
else:
    print("❌ 找不到第三步錨點")

# ── INSERTION 2：[SHOW_SERVICE_OPTIONS] — after 第六步 ────────────────────────

# Insert BEFORE the 必收清單 section (which comes after step 6)
SERVICE_OPTIONS_BLOCK = [
    "",
    "━━━━━━━━━━",
    "【第七步：AI 照片分析 → 觸發服務選項字卡】",
    "━━━━━━━━━━",
    "",
    "當客戶傳送照片後，ECHO 根據照片損傷類型判斷，並在回覆最後一行加上對應觸發碼：",
    "",
    "【分析結果 A：無掉漆（烤漆完好）】",
    "ECHO 回覆：「感謝您提供的照片，根據初步評估，您的烤漆狀況良好，以下是適合您的服務方案：」",
    "觸發碼（回覆最後一行）：[SHOW_SERVICE_OPTIONS_PDR]",
    "字卡內容：① 免烤漆凹痕修復（PDR）★推薦 ｜ ② 免烤漆板金大概修 ｜ ③ 傳統板金+烤漆",
    "",
    "【分析結果 B：有掉漆（烤漆受損）】",
    "ECHO 回覆：「感謝您提供的照片，您的烤漆看起來已有受損，以下是適合您的服務方案：」",
    "觸發碼（回覆最後一行）：[SHOW_SERVICE_OPTIONS_PAINT]",
    "字卡內容：② 免烤漆板金大概修 ｜ ③ 傳統板金+烤漆 ｜ ④ 高品質凹痕修復+烤漆 ★推薦",
    "",
    "【分析結果 C：保險桿損傷】",
    "ECHO 回覆：「感謝您提供的照片，保險桿是塑膠材質，需依實際狀況評估，以下是我們的服務選項：」",
    "觸發碼（回覆最後一行）：[SHOW_SERVICE_OPTIONS_BUMPER]",
    "字卡內容：① 免烤漆凹痕修復（需評估）｜ ⑦ 保險桿受損專業處理",
    "",
    "硬性規定：",
    "- 客戶不會看到觸發碼，這是系統觸發圖卡用途",
    "- 每次照片分析後最多觸發一次服務選項字卡",
    "- 無法判斷損傷類型時，預設觸發 [SHOW_SERVICE_OPTIONS_PDR]",
    "- 觸發後等待客戶透過按鈕選擇服務類型，選擇後更新 CRM 案件記錄",
    "",
    "━━━━━━━━━━",
    "",
]

if para_must_list:
    insert_paragraphs_before(para_must_list, SERVICE_OPTIONS_BLOCK, bold_first=False)
    print("✅ [SHOW_SERVICE_OPTIONS] 插入完成")
elif para_photo_ask:
    insert_paragraphs_after(para_photo_ask, SERVICE_OPTIONS_BLOCK, bold_first=False)
    print("✅ [SHOW_SERVICE_OPTIONS] 插入完成（錨點用 photo_ask）")
else:
    print("❌ 找不到第六步錨點")

# ── save ──────────────────────────────────────────────────────────────────────

doc.save(DEST)
print(f"\n✅ 儲存完成：{DEST}")
