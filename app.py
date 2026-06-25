# -*- coding: utf-8 -*-
"""
app.py
Venta Auto Pricer v3 (OCR בלבד) - ממשק Streamlit לחילוץ ותמחור פריטי
אוורור/פינוי עשן מתוכניות PDF, מפוצל לקטגוריות: תעלות / מפוחים ומשתיקים /
ונטות לפי יעד.

חילוץ הנתונים מתבצע במלואו באמצעות Tesseract OCR (חבילת שפה עברית) -
עצמאי לחלוטין, רץ מקומית על המחשב, לא תלוי בשום API חיצוני ולא דורש רשת
בזמן הריצה (מעבר להתקנה החד-פעמית של הספריות).
"""
import re

import pandas as pd
import streamlit as st

from categories import ALL_TOP_CATEGORIES, TOP_CATEGORY_OTHER
from excel_export import items_to_dataframe, make_excel
from extraction import extract_items, tesseract_heb_available
from pricing import default_pricing_df, find_price, load_pricing_from_excel

st.set_page_config(page_title="Venta | פינוי עשן ואוורור", layout="wide")

RTL_CSS = """
<style>
html, body, [class*="css"] { direction: rtl; text-align: right; }
.stDataFrame, .stTable { direction: rtl; }
.block-container { padding-top: 1.5rem; }
.small-note { color:#666; font-size:0.9rem; }
</style>
"""
st.markdown(RTL_CSS, unsafe_allow_html=True)

SECTION_KEYWORDS = {
    "גגות": ["גג", "גגות", "עליון"],
    "מרתפים / חניון": ["מרתף", "חניון"],
    "קומות טיפוסיות": ["טיפוסית", "8-25", "קומה 7", "קומה 26", "2-6"],
    "מסחר": ["מסחר"],
    "קרקע": ["קרקע"],
    "פנטהאוז": ["פנטהאוז"],
}


def infer_section(filename: str) -> str:
    for sec, keys in SECTION_KEYWORDS.items():
        if any(k in filename for k in keys):
            return sec
    return "כללי"


def floor_multiplier(filename: str) -> int:
    m = re.search(r"(\d+)\s*-\s*(\d+)", filename)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b >= a:
            return b - a + 1
    return 1


# ---------------------------------------------------------------------------
# סיידבר: פרטי פרויקט + הגדרות חילוץ
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("פרטי פרויקט")
    project = {
        "name": st.text_input("שם פרויקט", "מגרש 16 אשדוד"),
        "client": st.text_input("קבלן / לקוח", "אברהם עמרם"),
        "consultant": st.text_input("יועץ", "מארו"),
    }
    margin = st.number_input("אחוז העמסה למכירה", min_value=0.0, max_value=100.0, value=25.0, step=1.0)

    st.divider()
    st.subheader("חילוץ נתונים (OCR עברית)")
    ocr_ready = tesseract_heb_available()
    extraction_mode = "ocr"

    if ocr_ready:
        st.success("Tesseract + חבילת שפה עברית מותקנים. ✓")
    else:
        st.error(
            "Tesseract OCR או חבילת השפה העברית (heb) לא מותקנים במחשב הזה.\n\n"
            "כדי להתקין:\n"
            "1. הורד והרץ את המתקין מ: "
            "https://github.com/UB-Mannheim/tesseract/wiki\n"
            "2. בזמן ההתקנה, חובה לסמן את חבילת השפה **Hebrew** "
            "ברשימת ה-Additional language data.\n"
            "3. סגור ופתח מחדש את האפליקציה (Ctrl+C בטרמינל, ואז `streamlit run app.py` מחדש)."
        )
        st.stop()

    render_dpi = st.slider("רזולוציית רינדור (DPI)", min_value=100, max_value=250, value=150, step=10,
                            help="רזולוציה גבוהה יותר = קריאה מדויקת יותר של תוויות קטנות, אך איטי יותר.")
    tile_cols = st.slider("חלוקת כל עמוד למספר אריחים", min_value=2, max_value=12, value=6)

st.title("Venta | פינוי עשן ואוורור - חילוץ ותמחור לפי קטגוריות")
st.caption("מעלים תוכניות PDF → המערכת מחלצת ומפצלת ל: תעלות, מפוחים ומשתיקים, "
           "וונטות (שירותים / מקלחת / מטבח בנפרד) - עם ספיקה, לחץ וקוטר לכל פריט.")

pdfs = st.file_uploader("העלה תוכניות PDF", type=["pdf"], accept_multiple_files=True)
pricing_file = st.file_uploader("מחירון Excel אופציונלי", type=["xlsx", "xlsm", "xls"])
st.info("מסלול חילוץ: **OCR עברית (Tesseract, רץ מקומית)**")

if "items" not in st.session_state:
    st.session_state["items"] = []  # List[ExtractedItem]
if "cost_blocks" not in st.session_state:
    st.session_state["cost_blocks"] = default_pricing_df()

st.subheader("קוביות עלויות לפרויקט")
with st.expander("פתח / ערוך קוביות עלויות", expanded=True):
    st.session_state["cost_blocks"] = st.data_editor(
        st.session_state["cost_blocks"],
        width="stretch",
        num_rows="dynamic",
        column_config={
            "category": st.column_config.TextColumn("קטגוריה"),
            "match": st.column_config.TextColumn("התאמה לפי דגם/תיאור (ריק = ברירת מחדל לקטגוריה)"),
            "unit": st.column_config.TextColumn("יחידה"),
            "buy_price": st.column_config.NumberColumn("עלות קנייה", min_value=0.0, step=1.0),
            "sell_price": st.column_config.NumberColumn("מחיר מכירה", min_value=0.0, step=1.0),
            "notes": st.column_config.TextColumn("הערות"),
        },
        key="cost_blocks_editor",
    )

col1, col2 = st.columns([1, 1])
with col1:
    run = st.button("נתח תוכניות והפק תמחור", type="primary", width="stretch")
with col2:
    clear = st.button("נקה", width="stretch")
if clear:
    st.session_state["items"] = []

if run:
    if not pdfs:
        st.error("צריך להעלות לפחות תוכנית PDF אחת.")
    else:
        pricing = pd.concat([st.session_state["cost_blocks"], load_pricing_from_excel(pricing_file)], ignore_index=True)
        all_items = []
        progress = st.progress(0.0, text="מתחיל...")
        n_files = len(pdfs)
        for f_idx, pdf in enumerate(pdfs):
            pdf_bytes = pdf.read()
            pdf.seek(0)
            section = infer_section(pdf.name)
            mult = floor_multiplier(pdf.name)

            def _cb(page_idx, n_pages, tile_idx, n_tiles, _f=pdf.name, _fi=f_idx):
                frac = (_fi + (page_idx + tile_idx / max(n_tiles, 1)) / max(n_pages, 1)) / n_files
                progress.progress(min(frac, 0.99), text=f"מעבד {_f} (עמוד {page_idx + 1}/{n_pages}, אריח {tile_idx + 1}/{n_tiles})")

            try:
                items = extract_items(
                    pdf_bytes, source_file=pdf.name, section=section, floor_multiplier=mult,
                    mode="ocr", dpi=render_dpi, cols=tile_cols, progress_cb=_cb,
                )
                all_items.extend(items)
            except Exception as exc:
                st.error(f"שגיאה בעיבוד {pdf.name}: {exc}")
        progress.progress(1.0, text="הושלם")
        st.session_state["items"] = all_items
        st.session_state["pricing_snapshot"] = pricing
        st.success(f"הניתוח הסתיים. נמצאו {len(all_items)} פריטים גולמיים (לפני סינון/איחוד).")

# ---------------------------------------------------------------------------
# תצוגת תוצאות - טאב נפרד לכל קטגוריה
# ---------------------------------------------------------------------------
if st.session_state["items"]:
    pricing = st.session_state.get("pricing_snapshot", st.session_state["cost_blocks"])

    def _lookup(top_category, sub_type, model):
        return find_price(pricing, top_category, sub_type, model, margin)

    df_all = items_to_dataframe(st.session_state["items"], _lookup)

    st.subheader("תוצאות לפי קטגוריה")
    tabs = st.tabs(ALL_TOP_CATEGORIES)
    for tab, cat in zip(tabs, ALL_TOP_CATEGORIES):
        with tab:
            sub = df_all[df_all["_top_category"] == cat].drop(columns=["_top_category"])
            if sub.empty:
                st.info("לא נמצאו פריטים בקטגוריה זו.")
                continue
            st.dataframe(sub, width="stretch", hide_index=True)
            c1, c2 = st.columns(2)
            c1.metric("סהכ קנייה", f"{sub['סהכ קנייה'].sum():,.0f} ₪")
            c2.metric("סהכ מכירה", f"{sub['סהכ מכירה'].sum():,.0f} ₪")
            missing_specs = sub[sub["הערה"].astype(str).str.contains("חסר:", na=False)]
            if len(missing_specs):
                st.warning(f"{len(missing_specs)} פריטים בקטגוריה זו חסרים שדה חובה (ספיקה/לחץ/מידה) - "
                           f"ראו עמודת הערה, ויש להשלים לפני סגירת התמחור.")

    st.divider()
    total_buy = df_all["סהכ קנייה"].sum()
    total_sell = df_all["סהכ מכירה"].sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("סהכ קנייה (הכל)", f"{total_buy:,.0f} ₪")
    c2.metric("סהכ מכירה (הכל)", f"{total_sell:,.0f} ₪")
    c3.metric("רווח", f"{total_sell - total_buy:,.0f} ₪")

    excel_bytes = make_excel(df_all, project)
    st.download_button(
        "הורד קובץ Excel מלא (טאב לכל קטגוריה)",
        data=excel_bytes,
        file_name="venta_pricing_by_category.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        type="primary",
    )
else:
    st.info("לא בוצע ניתוח עדיין. העלה תוכניות PDF ולחץ על 'נתח תוכניות והפק תמחור'.")
