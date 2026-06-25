# -*- coding: utf-8 -*-
"""
excel_export.py
הפקת קובץ Excel עם טאב נפרד לכל קטגוריה עילית (תעלות / מפוחים ומשתיקים /
ונטות-שירותים / ונטות-מקלחת / ונטות-מטבח), בנוסף לטאב סיכום וטאב לאימות.
"""
from __future__ import annotations

import io
from typing import Dict, List

import pandas as pd

from categories import ALL_TOP_CATEGORIES, ExtractedItem, missing_required_fields

DISPLAY_COLUMNS = [
    "אזור", "קובץ", "תת-סוג", "דגם", "מידה/קוטר", "ספיקה (CFM)", "לחץ (Pa)",
    "הספק (KW)", "רעש (dBA)", "כמות ליחידה", "מקדם קומות", "כמות כוללת",
    "מחיר קנייה", "מחיר מכירה", "סהכ קנייה", "סהכ מכירה", "ביטחון", "הערה",
]


def items_to_dataframe(items: List[ExtractedItem], pricing_lookup) -> pd.DataFrame:
    """המרת רשימת ExtractedItem ל-DataFrame מתומחר, עם כל העמודות הנדרשות."""
    rows = []
    for it in items:
        buy, sell = pricing_lookup(it.top_category, it.sub_type, it.model)
        qty_total = it.total_quantity
        missing = missing_required_fields(it)
        note = it.note
        if missing:
            note = (note + " | " if note else "") + f"חסר: {', '.join(missing)}"
        rows.append({
            "אזור": it.section,
            "קובץ": it.source_file,
            "תת-סוג": it.sub_type,
            "דגם": it.model,
            "מידה/קוטר": it.size_label,
            "ספיקה (CFM)": it.cfm,
            "לחץ (Pa)": it.pressure_pa,
            "הספק (KW)": it.power_kw,
            "רעש (dBA)": it.noise_dba,
            "כמות ליחידה": it.quantity,
            "מקדם קומות": it.floor_multiplier,
            "כמות כוללת": qty_total,
            "מחיר קנייה": buy,
            "מחיר מכירה": sell,
            "סהכ קנייה": round(qty_total * buy, 2),
            "סהכ מכירה": round(qty_total * sell, 2),
            "ביטחון": "לאימות" if missing else it.confidence,
            "הערה": note,
            "_top_category": it.top_category,
        })
    return pd.DataFrame(rows, columns=DISPLAY_COLUMNS + ["_top_category"])


def _safe_sheet_name(name: str) -> str:
    """מנקה תווים אסורים בשם גיליון Excel ומקצר ל-31 תווים."""
    for ch in ["/", "\\", "[", "]", ":", "*", "?"]:
        name = name.replace(ch, "-")
    return name[:31]


def make_excel(df: pd.DataFrame, project: Dict[str, str]) -> bytes:
    """בונה קובץ Excel: טאב לכל קטגוריה עילית + סיכום + לאימות."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        wb = writer.book
        money = wb.add_format({"num_format": '#,##0 "₪"'})
        header_fmt = wb.add_format({"bold": True, "bg_color": "#D9EAD3", "border": 1})

        # --- טאב סיכום ---
        total_buy = df["סהכ קנייה"].sum() if len(df) else 0
        total_sell = df["סהכ מכירה"].sum() if len(df) else 0
        per_cat = (
            df.groupby("_top_category")[["סהכ קנייה", "סהכ מכירה"]].sum().reset_index()
            if len(df) else pd.DataFrame(columns=["_top_category", "סהכ קנייה", "סהכ מכירה"])
        )
        per_cat.columns = ["קטגוריה", "סהכ קנייה", "סהכ מכירה"]

        summary_top = pd.DataFrame({
            "שדה": ["פרויקט", "לקוח/קבלן", "יועץ", "סהכ קנייה (הכל)", "סהכ מכירה (הכל)", "רווח גולמי"],
            "ערך": [project.get("name", ""), project.get("client", ""), project.get("consultant", ""),
                    total_buy, total_sell, total_sell - total_buy],
        })
        summary_top.to_excel(writer, sheet_name="סיכום", index=False, startrow=0)
        per_cat.to_excel(writer, sheet_name="סיכום", index=False, startrow=len(summary_top) + 2)

        # --- טאב לכל קטגוריה עילית ---
        sheet_names_used = {}
        for cat in ALL_TOP_CATEGORIES:
            sub = df[df["_top_category"] == cat].drop(columns=["_top_category"]) if len(df) else pd.DataFrame(columns=DISPLAY_COLUMNS)
            safe_name = _safe_sheet_name(cat)
            sheet_names_used[cat] = safe_name
            sub.to_excel(writer, sheet_name=safe_name, index=False)

        # --- טאב לאימות (כל הפריטים עם דגל ביטחון != גבוה) ---
        if len(df):
            verify = df[df["ביטחון"] != "גבוה"].drop(columns=["_top_category"])
        else:
            verify = pd.DataFrame(columns=DISPLAY_COLUMNS)
        verify.to_excel(writer, sheet_name="לאימות", index=False)

        # --- עיצוב כל הגיליונות ---
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            ws.right_to_left()
            ws.freeze_panes(1, 0)
            ws.set_row(0, None, header_fmt)
            ws.set_column(0, 20, 16)

        for safe_name in list(sheet_names_used.values()) + ["לאימות"]:
            ws = writer.sheets[safe_name]
            # עמודות מחיר/סה"כ בפורמט כסף - לפי המיקום הקבוע ב-DISPLAY_COLUMNS
            ws.set_column(12, 15, 14, money)

    return output.getvalue()
