# -*- coding: utf-8 -*-
"""
pricing.py
ניהול מחירון: ברירות מחדל לפי קטגוריה, טעינה מאקסל קיים, התאמת מחיר לפריט.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from categories import (
    TOP_CATEGORY_DUCTS, TOP_CATEGORY_FANS, TOP_CATEGORY_VENTS_TOILET,
    TOP_CATEGORY_VENTS_SHOWER, TOP_CATEGORY_VENTS_KITCHEN, TOP_CATEGORY_OTHER,
)

# שורות מחיר ברירת מחדל - אחת לכל קטגוריה עילית. המשתמש יכול לערוך/להוסיף
# שורות ייעודיות יותר (לפי דגם/קוטר ספציפי) ישירות בטבלה באפליקציה.
DEFAULT_PRICE_ROWS = [
    {"category": TOP_CATEGORY_DUCTS, "match": "", "unit": "מטר/מ\"ר", "buy_price": 0.0, "sell_price": 0.0},
    {"category": TOP_CATEGORY_FANS, "match": "", "unit": "יח'", "buy_price": 0.0, "sell_price": 0.0},
    {"category": TOP_CATEGORY_VENTS_TOILET, "match": "", "unit": "יח'", "buy_price": 0.0, "sell_price": 0.0},
    {"category": TOP_CATEGORY_VENTS_SHOWER, "match": "", "unit": "יח'", "buy_price": 0.0, "sell_price": 0.0},
    {"category": TOP_CATEGORY_VENTS_KITCHEN, "match": "", "unit": "יח'", "buy_price": 0.0, "sell_price": 0.0},
]


def default_pricing_df() -> pd.DataFrame:
    df = pd.DataFrame(DEFAULT_PRICE_ROWS)
    df["notes"] = ""
    return df[["category", "match", "unit", "buy_price", "sell_price", "notes"]]


def load_pricing_from_excel(uploaded) -> pd.DataFrame:
    """טוען מחירון קיים מאקסל. מחפש שורות עם מילות מפתח רלוונטיות
    (מפוח/תעלה/ונטה/רפפה/תריס וכו') ומנרמל אותן למבנה האחיד."""
    base = default_pricing_df()
    if uploaded is None:
        return base

    keywords = ["מפוח", "תעלה", "ונטה", "רפפה", "תריס", "משתיק", "פח", "פיר", "גריל"]
    xls = pd.ExcelFile(uploaded)
    frames = []
    for sh in xls.sheet_names:
        raw = pd.read_excel(uploaded, sheet_name=sh, header=None)
        for _, row in raw.iterrows():
            vals = list(row.values)
            desc = None
            for v in vals:
                if isinstance(v, str) and len(v.strip()) > 2 and any(k in v for k in keywords):
                    desc = v.strip()
                    break
            if not desc:
                continue
            nums = [x for x in vals if isinstance(x, (int, float)) and pd.notna(x)]
            buy = nums[-1] if nums else 0
            frames.append({
                "category": "לפי מחירון קיים", "match": desc, "unit": "יח'",
                "buy_price": float(buy), "sell_price": 0.0, "notes": "נטען מקובץ Excel",
            })

    if not frames:
        return base
    extra = pd.DataFrame(frames).drop_duplicates(subset=["match"]).reset_index(drop=True)
    return pd.concat([extra, base], ignore_index=True)


def find_price(pricing: pd.DataFrame, top_category: str, sub_type: str, model: str,
               margin_pct: float) -> Tuple[float, float]:
    """מאתר מחיר קנייה/מכירה לפריט. סדר חיפוש:
    1. התאמה מדויקת לפי 'match' (אם קיים מחירון שנטען מאקסל) על דגם/תיאור.
    2. התאמה לפי קטגוריה עילית (ברירת מחדל).
    """
    if pricing is None or pricing.empty:
        return 0.0, 0.0

    needle = f"{model} {sub_type}".strip().lower()
    if needle:
        for _, row in pricing.iterrows():
            match_val = str(row.get("match", "")).strip().lower()
            if match_val and (match_val in needle or needle in match_val):
                buy = float(row.get("buy_price", 0) or 0)
                sell_manual = float(row.get("sell_price", 0) or 0)
                sell = sell_manual if sell_manual else (round(buy * (1 + margin_pct / 100), 2) if buy else 0.0)
                return buy, sell

    hits = pricing[pricing["category"].astype(str) == top_category]
    if len(hits):
        row = hits.iloc[0]
        buy = float(row.get("buy_price", 0) or 0)
        sell_manual = float(row.get("sell_price", 0) or 0)
        sell = sell_manual if sell_manual else (round(buy * (1 + margin_pct / 100), 2) if buy else 0.0)
        return buy, sell

    return 0.0, 0.0
