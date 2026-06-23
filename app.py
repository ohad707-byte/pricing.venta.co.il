import io
import re
from typing import Dict, List, Tuple

import fitz
import pandas as pd
import streamlit as st
from PIL import Image

st.set_page_config(page_title="Venta | תמחור אוטומטי", layout="wide")

RTL_CSS = """
<style>
html, body, [class*="css"] { direction: rtl; text-align: right; }
.stDataFrame, .stTable { direction: rtl; }
.block-container { padding-top: 1.5rem; }
.small-note { color:#666; font-size:0.9rem; }
</style>
"""
st.markdown(RTL_CSS, unsafe_allow_html=True)

# מחירון פנימי התחלתי. אפשר לעדכן אותו בהמשך לפי מחירון ונטה אמיתי.
DEFAULT_PRICE_ROWS = [
    {"key": "EMD-SQ-40T", "category": "יחידת מיזוג", "description": "EMD-SQ-40T 36000 BTU", "unit": "יח'", "buy_price": 0.0},
    {"key": "EMD-SQ-50T", "category": "יחידת מיזוג", "description": "EMD-SQ-50T 48000 BTU", "unit": "יח'", "buy_price": 0.0},
    {"key": "EMD-SQ-60T", "category": "יחידת מיזוג", "description": "EMD-SQ-60T 56000 BTU", "unit": "יח'", "buy_price": 0.0},
    {"key": "ELVOMV4PI-8", "category": "יחידת VRF חוץ", "description": "ELVOMV4PI-8", "unit": "יח'", "buy_price": 0.0},
    {"key": "ELVOMV4PI-12", "category": "יחידת VRF חוץ", "description": "ELVOMV4PI-12", "unit": "יח'", "buy_price": 0.0},
    {"key": "ELVOMV4PI-14", "category": "יחידת VRF חוץ", "description": "ELVOMV4PI-14", "unit": "יח'", "buy_price": 0.0},
    {"key": "ELVIDSLD-40", "category": "יחידת VRF פנים", "description": "ELVIDSLD-40", "unit": "יח'", "buy_price": 0.0},
    {"key": "ELVIDSHD-80", "category": "יחידת VRF פנים", "description": "ELVIDSHD-80", "unit": "יח'", "buy_price": 0.0},
    {"key": "ELVIHWD25-M9", "category": "יחידת VRF פנים", "description": "ELVIHWD25-m9", "unit": "יח'", "buy_price": 0.0},
    {"key": "ELVIHWD40-M9", "category": "יחידת VRF פנים", "description": "ELVIHWD40-m9", "unit": "יח'", "buy_price": 0.0},
    {"key": "ARNU", "category": "יחידת LG פנים", "description": "LG ARNU - לפי דגם", "unit": "יח'", "buy_price": 0.0},
    {"key": "CO", "category": "גלאי CO", "description": "גלאי CO", "unit": "יח'", "buy_price": 0.0},
    {"key": "GAS", "category": "צנרת גז", "description": "נקודת צנרת גז", "unit": "נק'", "buy_price": 0.0},
    {"key": "CFM", "category": "מפוח / ספיקה", "description": "מפוח לפי CFM", "unit": "יח'", "buy_price": 0.0},
    {"key": "DUCT", "category": "תעלות / שרשור", "description": "תעלה / שרשור לפי מידה", "unit": "יח'", "buy_price": 0.0},
    {"key": "TRT", "category": "תרמוסטט", "description": "תרמוסטט / בקר", "unit": "יח'", "buy_price": 0.0},
]

DEFAULT_PATTERNS = [
    ("יחידת מיזוג", r"EMD[-\s]*A?[-\s]*SQ[-\s]*(?:40|50|60)\s*T", "יח'"),
    ("יחידת VRF חוץ", r"ELVOMV4PI[-\s]*(?:8|12|14)", "יח'"),
    ("יחידת VRF פנים", r"ELVID(?:S|H)?[A-Z0-9\-]*|ELVIHWD\d+[-\s]*m9", "יח'"),
    ("יחידת LG פנים", r"ARNU\d+[A-Z0-9]+", "יח'"),
    ("מזגן Electra", r"Electra\s+aaa\s+INV\s+180", "יח'"),
    ("גלאי CO", r"\bCO\b", "יח'"),
    ("צנרת גז", r"\bGAS\b", "נק'"),
    ("מפוח / ספיקה", r"\d{3,6}\s*cfm", "יח'"),
    ("תעלות / שרשור", r"Ø\s*\d+\s*(?:cm|\")|\d+\s*/\s*\d+", "יח'"),
    ("תרמוסטט", r"\bTrT\b|\bT[1-4]\b", "יח'"),
]

SECTION_KEYWORDS = {
    "גגות": ["גג", "גגות", "עליון"],
    "מרתפים / חניון": ["מרתף", "חניון", "CO"],
    "קומות טיפוסיות": ["טיפוסית", "8-25", "קומה 7", "קומה 26"],
    "מסחר": ["מסחר"],
    "קרקע": ["קרקע"],
    "פנטהאוז": ["פנטהאוז"],
}


def normalize_model(text: str) -> str:
    clean = re.sub(r"\s+", "", str(text)).upper()
    clean = clean.replace("EMDASQ", "EMD-SQ-").replace("EMD-SQ", "EMD-SQ-")
    clean = clean.replace("--", "-")
    clean = clean.replace("-T", "T")
    return clean


def floor_multiplier(filename: str) -> int:
    name = filename.replace(" ", "")
    m = re.search(r"(\d+)\s*-\s*(\d+)", filename)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b >= a:
            return b - a + 1
    if "8-25" in name:
        return 18
    return 1


def infer_section(filename: str, text: str) -> str:
    blob = f"{filename} {text[:1200]}"
    for sec, keys in SECTION_KEYWORDS.items():
        if any(k in blob for k in keys):
            return sec
    return "כללי"


def extract_pdf_text(uploaded) -> Tuple[str, int, Image.Image | None]:
    data = uploaded.read()
    uploaded.seek(0)
    doc = fitz.open(stream=data, filetype="pdf")
    texts = []
    preview = None
    for i, page in enumerate(doc):
        texts.append(page.get_text("text"))
        if i == 0:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3), alpha=False)
            preview = Image.open(io.BytesIO(pix.tobytes("png")))
    return "\n".join(texts), len(doc), preview


def default_pricing_df() -> pd.DataFrame:
    return pd.DataFrame(DEFAULT_PRICE_ROWS)


def load_pricing_from_excel(uploaded) -> pd.DataFrame:
    base = default_pricing_df()
    if uploaded is None:
        return base

    xls = pd.ExcelFile(uploaded)
    frames = []
    for sh in xls.sheet_names:
        raw = pd.read_excel(uploaded, sheet_name=sh, header=None)
        for _, row in raw.iterrows():
            vals = list(row.values)
            desc = None
            for v in vals:
                if isinstance(v, str) and len(v.strip()) > 2:
                    if any(k in v for k in ["מפוח", "תריס", "ברך", "פחחות", "מדף", "לוח", "כבילה", "ונטה", "גלאי", "צנרת", "EMD", "ELVO", "ELVI", "ARNU"]):
                        desc = v.strip()
                        break
            if not desc:
                continue
            nums = [x for x in vals if isinstance(x, (int, float)) and pd.notna(x)]
            buy = nums[-1] if nums else 0
            frames.append({"key": normalize_model(desc), "category": "לפי מחירון", "description": desc, "unit": "יח'", "buy_price": float(buy)})

    if not frames:
        return base
    extra = pd.DataFrame(frames).drop_duplicates(subset=["description"]).reset_index(drop=True)
    return pd.concat([extra, base], ignore_index=True)


def find_price(pricing: pd.DataFrame, category: str, model: str) -> float:
    if pricing.empty:
        return 0.0
    model_norm = normalize_model(model)
    if model_norm:
        for _, row in pricing.iterrows():
            key = str(row.get("key", ""))
            desc = str(row.get("description", ""))
            if key and (key in model_norm or model_norm in key):
                return float(row.get("buy_price", 0) or 0)
            if desc and normalize_model(desc) in model_norm:
                return float(row.get("buy_price", 0) or 0)
    hits = pricing[pricing["category"].astype(str).str.contains(category, na=False, regex=False)]
    if len(hits):
        return float(hits.iloc[0].get("buy_price", 0) or 0)
    return 0.0


def identify_items(pdf_results: List[dict], pricing: pd.DataFrame, margin: float) -> pd.DataFrame:
    rows = []
    for res in pdf_results:
        text = res["text"]
        mult = res["multiplier"]
        for category, pattern, unit in DEFAULT_PATTERNS:
            matches = [m.group(0) for m in re.finditer(pattern, text, flags=re.I)]
            if not matches:
                continue

            # לציוד נספור לפי דגם, לפריטים כלליים נסכם כשורה אחת.
            if category in ["יחידת מיזוג", "יחידת VRF חוץ", "יחידת VRF פנים", "יחידת LG פנים", "מזגן Electra"]:
                groups = pd.Series([normalize_model(x) for x in matches]).value_counts().to_dict()
            else:
                groups = {category: len(matches)}

            for model, qty_raw in groups.items():
                qty = int(qty_raw) * mult
                desc = category if model == category else f"{category} {model}"
                buy_price = find_price(pricing, category, model)
                sell_price = round(buy_price * (1 + margin / 100), 2) if buy_price else 0.0
                confidence = "גבוה" if category not in ["צנרת גז", "תעלות / שרשור", "תרמוסטט"] else "בינוני"
                rows.append({
                    "אזור": res["section"],
                    "קובץ": res["filename"],
                    "קטגוריה": category,
                    "תיאור": desc,
                    "יחידה": unit,
                    "כמות מזוהה": int(qty_raw),
                    "מקדם קומות": mult,
                    "כמות לתמחור": qty,
                    "מחיר קנייה": buy_price,
                    "מחיר מכירה": sell_price,
                    "סהכ קנייה": round(qty * buy_price, 2),
                    "סהכ מכירה": round(qty * sell_price, 2),
                    "ביטחון": confidence,
                    "הערה": "מחיר חסר / לאימות" if buy_price == 0 else ("לאימות ידני" if confidence != "גבוה" else ""),
                })

    columns = ["אזור", "קובץ", "קטגוריה", "תיאור", "יחידה", "כמות מזוהה", "מקדם קומות", "כמות לתמחור", "מחיר קנייה", "מחיר מכירה", "סהכ קנייה", "סהכ מכירה", "ביטחון", "הערה"]
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


def make_excel(items: pd.DataFrame, project: Dict[str, str]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        total_buy = items["סהכ קנייה"].sum() if len(items) else 0
        total_sell = items["סהכ מכירה"].sum() if len(items) else 0
        summary = pd.DataFrame({
            "שדה": ["פרויקט", "לקוח/קבלן", "יועץ", "סהכ קנייה", "סהכ מכירה", "רווח גולמי", "אחוז רווח"],
            "ערך": [project.get("name", ""), project.get("client", ""), project.get("consultant", ""), total_buy, total_sell, total_sell - total_buy, ((total_sell - total_buy) / total_sell) if total_sell else 0],
        })
        summary.to_excel(writer, sheet_name="סיכום", index=False)
        items.to_excel(writer, sheet_name="כתב כמויות", index=False)
        verify = items[items["הערה"].astype(str).str.len() > 0] if len(items) else items
        verify.to_excel(writer, sheet_name="לאימות", index=False)
        wb = writer.book
        money = wb.add_format({"num_format": '#,##0 "₪"'})
        header = wb.add_format({"bold": True, "bg_color": "#D9EAD3", "border": 1})
        for sheet in ["סיכום", "כתב כמויות", "לאימות"]:
            ws = writer.sheets[sheet]
            ws.right_to_left()
            ws.freeze_panes(1, 0)
            ws.set_row(0, None, header)
            ws.set_column(0, 20, 18)
        writer.sheets["סיכום"].set_column(1, 1, 20, money)
        writer.sheets["כתב כמויות"].set_column(8, 11, 14, money)
        writer.sheets["סיכום"].write(8, 0, "הערה")
        writer.sheets["סיכום"].write(8, 1, "תוצאה ראשונית - דורשת אימות בתוכנית")
    return output.getvalue()


st.title("Venta | תמחור אוטומטי ראשוני")
st.caption("מעלים תוכניות PDF → המערכת מפיקה כתב כמויות ותמחור. מחירון Excel הוא אופציונלי בלבד.")

with st.sidebar:
    st.header("פרטי פרויקט")
    project = {
        "name": st.text_input("שם פרויקט", "מגרש 16 אשדוד"),
        "client": st.text_input("קבלן / לקוח", "אברהם עמרם"),
        "consultant": st.text_input("יועץ", "מארו"),
    }
    margin = st.number_input("אחוז העמסה למכירה", min_value=0.0, max_value=100.0, value=25.0, step=1.0)

pdfs = st.file_uploader("העלה תוכניות PDF", type=["pdf"], accept_multiple_files=True)
pricing_file = st.file_uploader("מחירון Excel אופציונלי - לא חובה", type=["xlsx", "xlsm", "xls"])
st.caption("אם לא מעלים מחירון, המערכת משתמשת במחירון פנימי ומסמנת מחירים חסרים לאימות.")

if "pdf_results" not in st.session_state:
    st.session_state["pdf_results"] = []
if "items" not in st.session_state:
    st.session_state["items"] = pd.DataFrame()

col1, col2 = st.columns([1, 1])
with col1:
    run = st.button("נתח תוכניות והפק תמחור", type="primary", use_container_width=True)
with col2:
    clear = st.button("נקה", use_container_width=True)
if clear:
    st.session_state["pdf_results"] = []
    st.session_state["items"] = pd.DataFrame()

if run:
    if not pdfs:
        st.error("צריך להעלות לפחות תוכנית PDF אחת.")
    else:
        pricing = load_pricing_from_excel(pricing_file)
        results = []
        progress = st.progress(0)
        for i, pdf in enumerate(pdfs):
            text, pages, preview = extract_pdf_text(pdf)
            results.append({
                "filename": pdf.name,
                "pages": pages,
                "text": text,
                "preview": preview,
                "multiplier": floor_multiplier(pdf.name),
                "section": infer_section(pdf.name, text),
            })
            progress.progress((i + 1) / len(pdfs))
        st.session_state["pdf_results"] = results
        st.session_state["items"] = identify_items(results, pricing, margin)
        st.success("הניתוח הסתיים. בדוק את הטבלה לפני יצוא.")

if len(st.session_state["pdf_results"]):
    st.subheader("תוכניות שנסרקו")
    meta = pd.DataFrame([{"קובץ": r["filename"], "עמודים": r["pages"], "אזור": r["section"], "מקדם קומות": r["multiplier"], "תווים שחולצו": len(r["text"])} for r in st.session_state["pdf_results"]])
    st.dataframe(meta, use_container_width=True, hide_index=True)
    with st.expander("תצוגה מקדימה - עמוד ראשון"):
        sel = st.selectbox("בחר קובץ", [r["filename"] for r in st.session_state["pdf_results"]])
        img = next((r["preview"] for r in st.session_state["pdf_results"] if r["filename"] == sel), None)
        if img is not None:
            st.image(img, use_container_width=True)

st.subheader("כתב כמויות ראשוני")
if len(st.session_state["items"]):
    edited = st.data_editor(st.session_state["items"], use_container_width=True, num_rows="dynamic")
    st.session_state["items"] = edited
    c1, c2, c3 = st.columns(3)
    buy = edited["סהכ קנייה"].sum()
    sell = edited["סהכ מכירה"].sum()
    c1.metric("סהכ קנייה", f"{buy:,.0f} ₪")
    c2.metric("סהכ מכירה", f"{sell:,.0f} ₪")
    c3.metric("רווח", f"{sell - buy:,.0f} ₪")
    excel_bytes = make_excel(edited, project)
    st.download_button("הורד Excel", data=excel_bytes, file_name="venta_auto_pricing.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
else:
    st.info("לא בוצע ניתוח עדיין.")
