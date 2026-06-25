# -*- coding: utf-8 -*-
"""
categories.py
מודול הגדרת קטגוריות, regex לזיהוי, וחילוץ תכונות טכניות (ספיקה/לחץ/קוטר).

דרישת הלקוח המרכזית:
  1. תעלות - קטגוריה נפרדת לחלוטין (קוטר/מידה, אורך/כמות)
  2. מפוחים ומשתיקים - קטגוריה נפרדת, חובה: ספיקה (CFM), לחץ (Pa), קוטר/מידה
  3. ונטות - מחולקות לפי יעד: שירותים / מקלחת / מטבח - כל אחת בנפרד,
     חובה: ספיקה, לחץ, קוטר
"""
import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# קטגוריות עיליות (top-level) - אלה למעשה "הטאבים" הנפרדים שהלקוח דרש
# ---------------------------------------------------------------------------
TOP_CATEGORY_DUCTS = "תעלות"
TOP_CATEGORY_FANS = "מפוחים ומשתיקים"
TOP_CATEGORY_VENTS_TOILET = "ונטות - שירותים"
TOP_CATEGORY_VENTS_SHOWER = "ונטות - מקלחת"
TOP_CATEGORY_VENTS_KITCHEN = "ונטות - מטבח"
TOP_CATEGORY_OTHER = "אחר / לאימות"

ALL_TOP_CATEGORIES = [
    TOP_CATEGORY_DUCTS,
    TOP_CATEGORY_FANS,
    TOP_CATEGORY_VENTS_TOILET,
    TOP_CATEGORY_VENTS_SHOWER,
    TOP_CATEGORY_VENTS_KITCHEN,
    TOP_CATEGORY_OTHER,
]


@dataclass
class ExtractedItem:
    """פריט בודד שזוהה בתוכנית - שורת בסיס לפני תמחור."""
    top_category: str            # אחת מ-ALL_TOP_CATEGORIES
    sub_type: str                # תיאור מדויק יותר (לדוגמה: "מפוח פינוי עשן צירי")
    model: str = ""              # דגם/קוד אם קיים (לדוגמה EMD-SQ-50T)
    diameter_cm: Optional[float] = None   # קוטר בס"מ (לתעלות עגולות / מפוחים)
    duct_w_cm: Optional[float] = None     # רוחב תעלה מלבנית בס"מ
    duct_h_cm: Optional[float] = None     # גובה תעלה מלבנית בס"מ
    cfm: Optional[float] = None           # ספיקה ב-CFM
    pressure_pa: Optional[float] = None   # לחץ סטטי ב-Pa
    power_kw: Optional[float] = None      # הספק חשמלי ב-KW (אם צוין)
    noise_dba: Optional[float] = None     # רמת רעש ב-dBA (אם צוין)
    quantity: int = 1
    floor_multiplier: int = 1
    source_file: str = ""
    section: str = ""
    confidence: str = "בינוני"   # גבוה / בינוני / לאימות
    note: str = ""

    @property
    def total_quantity(self) -> int:
        return int(self.quantity) * int(self.floor_multiplier or 1)

    @property
    def size_label(self) -> str:
        """תווית מידה קריאה לבני אדם - קוטר עגול או רוחב/גובה מלבני."""
        if self.duct_w_cm and self.duct_h_cm:
            return f"{int(self.duct_w_cm)}/{int(self.duct_h_cm)} ס\"מ"
        if self.diameter_cm:
            return f"Ø{int(self.diameter_cm)} ס\"מ"
        return ""


# ---------------------------------------------------------------------------
# Regex לזיהוי תעלות (מלבניות ועגולות)
# ---------------------------------------------------------------------------
# תעלה מלבנית: שתי מידות ב-mm מופרדות ב-"/" כמו 100/180, 160/60, 230/50
RE_DUCT_RECT = re.compile(r"(?<!\d)(\d{2,3})\s*/\s*(\d{2,3})(?!\d)")

# תעלה עגולה: Ø6", Ø10cm, 8" וכו'
RE_DUCT_ROUND_CM = re.compile(r"Ø\s*(\d{1,3})\s*cm", re.I)
RE_DUCT_ROUND_INCH = re.compile(r"Ø?\s*(\d{1,2})\s*\"")

# ---------------------------------------------------------------------------
# Regex לזיהוי מפוחים ומשתיקים
# ---------------------------------------------------------------------------
FAN_KEYWORDS = re.compile(
    r"מפוח|פינוי\s*עשן|שחרור\s*עשן|דיחוס|jet\s*fan|exhaust\s*fan|smoke\s*fan|EMD[-\s]?A?[-\s]?SQ|ELVO|ELVI",
    re.I,
)
SILENCER_KEYWORDS = re.compile(r"משתיק|silencer", re.I)

# ---------------------------------------------------------------------------
# Regex לזיהוי ונטות ושיוך ליעד (שירותים / מקלחת / מטבח)
# ---------------------------------------------------------------------------
VENT_KEYWORDS = re.compile(r"ונטה|מפוח\s*דירה|מפוח\s*שירותים|מפוח\s*רחצה|מפוח\s*מטבח|venta", re.I)

VENT_TARGET_TOILET = re.compile(r"שירותים|אסלה|wc", re.I)
VENT_TARGET_SHOWER = re.compile(r"מקלח|רחצה|אמבטיה|מקלחת", re.I)
VENT_TARGET_KITCHEN = re.compile(r"מטבח|kitchen", re.I)

# ---------------------------------------------------------------------------
# Regex לתכונות טכניות (ספיקה / לחץ / הספק / רעש) - לחילוץ סביב כל פריט
# ---------------------------------------------------------------------------
RE_CFM = re.compile(r"(\d{2,6})\s*cfm", re.I)
RE_PA = re.compile(r"(\d{2,4})\s*pa\b", re.I)
RE_KW = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*kw", re.I)
RE_DBA = re.compile(r"(\d{2,3})\s*db\s*\(?a\)?", re.I)
RE_RPM = re.compile(r"(\d{3,5})\s*rpm", re.I)


def extract_nearby_specs(window_text: str) -> dict:
    """מחלץ ספיקה/לחץ/הספק/רעש/סל"ד מתוך חלון טקסט סמוך לפריט (למשל 200 תווים לפני/אחרי)."""
    specs = {}
    m = RE_CFM.search(window_text)
    if m:
        specs["cfm"] = float(m.group(1))
    m = RE_PA.search(window_text)
    if m:
        specs["pressure_pa"] = float(m.group(1))
    m = RE_KW.search(window_text)
    if m:
        specs["power_kw"] = float(m.group(1))
    m = RE_DBA.search(window_text)
    if m:
        specs["noise_dba"] = float(m.group(1))
    m = RE_RPM.search(window_text)
    if m:
        specs["rpm"] = float(m.group(1))
    return specs


def classify_vent_target(window_text: str) -> str:
    """קובע לאיזה יעד (שירותים/מקלחת/מטבח) משויכת ונטה, לפי חלון הטקסט הסמוך."""
    if VENT_TARGET_KITCHEN.search(window_text):
        return TOP_CATEGORY_VENTS_KITCHEN
    if VENT_TARGET_SHOWER.search(window_text):
        return TOP_CATEGORY_VENTS_SHOWER
    if VENT_TARGET_TOILET.search(window_text):
        return TOP_CATEGORY_VENTS_TOILET
    return TOP_CATEGORY_VENTS_TOILET  # ברירת מחדל סבירה - הנפוץ ביותר; מסומן לאימות בהמשך


REQUIRED_FIELDS_BY_CATEGORY = {
    TOP_CATEGORY_FANS: ["cfm", "pressure_pa", "size_label"],
    TOP_CATEGORY_VENTS_TOILET: ["cfm", "pressure_pa", "size_label"],
    TOP_CATEGORY_VENTS_SHOWER: ["cfm", "pressure_pa", "size_label"],
    TOP_CATEGORY_VENTS_KITCHEN: ["cfm", "pressure_pa", "size_label"],
    TOP_CATEGORY_DUCTS: ["size_label"],
}


def missing_required_fields(item: ExtractedItem) -> list:
    """בודק אילו שדות חובה חסרים לפריט הזה, לפי הקטגוריה - לדגל לאימות ידני."""
    required = REQUIRED_FIELDS_BY_CATEGORY.get(item.top_category, [])
    missing = []
    for f in required:
        if f == "size_label":
            if not item.size_label:
                missing.append("מידה/קוטר")
            continue
        if getattr(item, f, None) in (None, 0):
            label = {"cfm": "ספיקה (CFM)", "pressure_pa": "לחץ (Pa)"}.get(f, f)
            missing.append(label)
    return missing
