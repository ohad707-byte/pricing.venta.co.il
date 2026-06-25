# -*- coding: utf-8 -*-
"""
extraction.py
חילוץ פריטים מתוכניות PDF באמצעות OCR (Tesseract + חבילת שפה עברית).

מנדר כל עמוד PDF לתמונה ברזולוציה גבוהה, מחלק לאריחים, מריץ Tesseract+heb
על כל אריח, ומפעיל regex על הטקסט שחזר כדי לבנות רשימת ExtractedItem
(תעלות / מפוחים ומשתיקים / ונטות לפי יעד - ראו categories.py).

עצמאי לחלוטין: לא תלוי בשום API חיצוני, לא דורש רשת בזמן הריצה (רק
בהתקנה החד-פעמית של הספריות), ולכן לא נתקל בחסימות רשת/פרוקסי ארגוניות.

תלוי באיכות זיהוי-התווים של Tesseract על טקסט מוטה/קטן/צפוף - יש לבדוק
בפועל על תוכניות אמיתיות ולהשוות לתוצאה ידנית לפני הסתמכות מלאה.

*** דורש התקנת מערכת (לא רק pip): tesseract-ocr + חבילת שפה heb ***
ראו README.md לפרטי התקנה ב-Windows / Linux / macOS.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
from typing import List

import fitz  # PyMuPDF
from PIL import Image

from categories import (
    ExtractedItem,
    TOP_CATEGORY_DUCTS,
    TOP_CATEGORY_FANS,
    RE_DUCT_RECT,
    RE_DUCT_ROUND_CM,
    RE_DUCT_ROUND_INCH,
    FAN_KEYWORDS,
    SILENCER_KEYWORDS,
    VENT_KEYWORDS,
    classify_vent_target,
    extract_nearby_specs,
)

TILE_COLS_DEFAULT = 6
RENDER_DPI_DEFAULT = 150  # רזולוציה גבוהה - קריטי לקריאת תוויות קטנות/מוטות


def tesseract_heb_available() -> bool:
    """בודק אם Tesseract מותקן וחבילת השפה העברית קיימת בפועל.
    בודק גם PATH (shutil.which) וגם מיקומי התקנה נפוצים ב-Windows, כי
    מתקין Tesseract ל-Windows לא תמיד מוסיף את עצמו אוטומטית ל-PATH."""
    tesseract_cmd = shutil.which("tesseract")
    if tesseract_cmd is None:
        # מיקומי התקנה נפוצים ב-Windows (UB-Mannheim installer)
        common_windows_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for path in common_windows_paths:
            if os.path.isfile(path):
                tesseract_cmd = path
                try:
                    import pytesseract
                    pytesseract.pytesseract.tesseract_cmd = path
                except ImportError:
                    pass
                break
    if tesseract_cmd is None:
        return False
    try:
        out = subprocess.run([tesseract_cmd, "--list-langs"], capture_output=True, text=True, timeout=10)
        return "heb" in out.stdout
    except Exception:
        return False


def render_pdf_page_tiles(pdf_bytes: bytes, page_index: int = 0, dpi: int = RENDER_DPI_DEFAULT,
                           cols: int = TILE_COLS_DEFAULT) -> List[Image.Image]:
    """מרנדר עמוד PDF יחיד לתמונה ברזולוציה גבוהה, ומחלק לאריחים אנכיים.
    אריחים (לא העמוד השלם) חשובים כי עמודי AutoCAD A0 גדולים מדי לקריאה/OCR
    מדויקת כתמונה אחת - גם לבני אדם וגם למודלים."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    w, h = img.size
    tiles = []
    for i in range(cols):
        box = (i * w // cols, 0, (i + 1) * w // cols, h)
        tiles.append(img.crop(box))
    return tiles


# ---------------------------------------------------------------------------
# מסלול 1: OCR (Tesseract עברית) - עצמאי, ללא תלות חיצונית
# ---------------------------------------------------------------------------

def _ocr_tile(tile: Image.Image) -> str:
    """מריץ Tesseract+heb+eng על אריח בודד ומחזיר את הטקסט שזוהה."""
    import pytesseract
    config = "--psm 11"  # sparse text - מתאים לתוויות מפוזרות על שרטוט
    return pytesseract.image_to_string(tile, lang="heb+eng", config=config)


def _parse_text_to_items(text: str, source_file: str, section: str, floor_multiplier: int) -> List[ExtractedItem]:
    """מפעיל regex על טקסט (מ-OCR או ממקור אחר) ובונה ExtractedItem עבור כל
    קטגוריה: תעלות, מפוחים/משתיקים, ונטות לפי יעד."""
    items: List[ExtractedItem] = []
    window = 60  # תווים לפני/אחרי כל התאמה, לחיפוש ספיקה/לחץ/הספק סמוכים

    # --- תעלות מלבניות ---
    for m in RE_DUCT_RECT.finditer(text):
        w_mm, h_mm = float(m.group(1)), float(m.group(2))
        ctx = text[max(0, m.start() - window):m.end() + window]
        specs = extract_nearby_specs(ctx)
        items.append(ExtractedItem(
            top_category=TOP_CATEGORY_DUCTS,
            sub_type="תעלה מלבנית",
            duct_w_cm=w_mm / 10.0, duct_h_cm=h_mm / 10.0,
            cfm=specs.get("cfm"), pressure_pa=specs.get("pressure_pa"),
            quantity=1, floor_multiplier=floor_multiplier,
            source_file=source_file, section=section,
            confidence="בינוני",
            note="זוהה לפי OCR - לאמת מידה (יח' מ\"מ מקור) וכמות מול השרטוט",
        ))

    # --- תעלות עגולות ---
    for rex in (RE_DUCT_ROUND_CM, RE_DUCT_ROUND_INCH):
        for m in rex.finditer(text):
            d = float(m.group(1))
            ctx = text[max(0, m.start() - window):m.end() + window]
            specs = extract_nearby_specs(ctx)
            items.append(ExtractedItem(
                top_category=TOP_CATEGORY_DUCTS,
                sub_type="תעלה עגולה",
                diameter_cm=d if rex is RE_DUCT_ROUND_CM else d * 2.54,
                cfm=specs.get("cfm"), pressure_pa=specs.get("pressure_pa"),
                quantity=1, floor_multiplier=floor_multiplier,
                source_file=source_file, section=section,
                confidence="בינוני",
                note="זוהה לפי OCR - לאמת קוטר וכמות מול השרטוט",
            ))

    # --- מפוחים ומשתיקים ---
    # קיבוץ התאמות סמוכות (לדוגמה "מפוח" + "שחרור עשן" + "EMD-SQ" באותו משפט)
    # לפריט בודד אחד, כדי לא לספור פעמיים/שלוש פעמים את אותו מפוח בפועל.
    fan_matches = list(FAN_KEYWORDS.finditer(text))
    merge_distance = 80  # תווים - התאמות קרובות מזה נחשבות לאותו פריט
    merged_spans = []
    for m in fan_matches:
        if merged_spans and m.start() - merged_spans[-1][1] <= merge_distance:
            merged_spans[-1] = (merged_spans[-1][0], m.end())
        else:
            merged_spans.append((m.start(), m.end()))
    for start, end in merged_spans:
        ctx = text[max(0, start - window):end + window]
        specs = extract_nearby_specs(ctx)
        is_silencer = bool(SILENCER_KEYWORDS.search(ctx))
        items.append(ExtractedItem(
            top_category=TOP_CATEGORY_FANS,
            sub_type="משתיק" if is_silencer else "מפוח",
            cfm=specs.get("cfm"), pressure_pa=specs.get("pressure_pa"),
            power_kw=specs.get("power_kw"), noise_dba=specs.get("noise_dba"),
            quantity=1, floor_multiplier=floor_multiplier,
            source_file=source_file, section=section,
            confidence="בינוני" if specs.get("cfm") else "לאימות",
            note="זוהה לפי OCR - לאמת דגם מדויק מול השרטוט",
        ))

    # --- ונטות (מחולק לפי יעד) ---
    for m in VENT_KEYWORDS.finditer(text):
        ctx = text[max(0, m.start() - window):m.end() + window]
        specs = extract_nearby_specs(ctx)
        target_category = classify_vent_target(ctx)
        items.append(ExtractedItem(
            top_category=target_category,
            sub_type="ונטה",
            cfm=specs.get("cfm"), pressure_pa=specs.get("pressure_pa"),
            quantity=1, floor_multiplier=floor_multiplier,
            source_file=source_file, section=section,
            confidence="בינוני" if specs.get("cfm") else "לאימות",
            note="זוהה לפי OCR - יעד (שירותים/מקלחת/מטבח) משוער, יש לאמת מול השרטוט",
        ))

    return items


def extract_items_ocr(pdf_bytes: bytes, source_file: str, section: str,
                       floor_multiplier: int = 1, dpi: int = RENDER_DPI_DEFAULT,
                       cols: int = TILE_COLS_DEFAULT,
                       progress_cb=None) -> List[ExtractedItem]:
    """מסלול OCR מלא: רינדור עמודים -> אריחים -> Tesseract -> regex -> ExtractedItem."""
    if not tesseract_heb_available():
        raise RuntimeError(
            "Tesseract OCR לא מותקן, או שחבילת השפה העברית (heb) חסרה. "
            "התקן עם: sudo apt-get install tesseract-ocr tesseract-ocr-heb "
            "(או brew install tesseract-lang ב-Mac), ואז התקן pytesseract: pip install pytesseract"
        )
    import pytesseract  # noqa: F401  (יזרוק ImportError ברור אם חסר)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n_pages = len(doc)
    all_items: List[ExtractedItem] = []
    for page_idx in range(n_pages):
        tiles = render_pdf_page_tiles(pdf_bytes, page_index=page_idx, dpi=dpi, cols=cols)
        for t_idx, tile in enumerate(tiles):
            text = _ocr_tile(tile)
            items = _parse_text_to_items(text, source_file, section, floor_multiplier)
            all_items.extend(items)
            if progress_cb:
                progress_cb(page_idx, n_pages, t_idx, len(tiles))
    return all_items


# ---------------------------------------------------------------------------
# נקודת כניסה - app.py קורא רק לפונקציה הזו
# ---------------------------------------------------------------------------

def extract_items(pdf_bytes: bytes, source_file: str, section: str, floor_multiplier: int = 1,
                   mode: str = "ocr", dpi: int = RENDER_DPI_DEFAULT, cols: int = TILE_COLS_DEFAULT,
                   progress_cb=None) -> List[ExtractedItem]:
    """נקודת כניסה לחילוץ. כרגע נתמך מסלול 'ocr' בלבד (Tesseract+heb, מקומי)."""
    if mode != "ocr":
        raise ValueError(f"מסלול חילוץ לא נתמך בגרסה הזו: {mode!r} (רק 'ocr' נתמך)")
    return extract_items_ocr(pdf_bytes, source_file, section, floor_multiplier, dpi, cols, progress_cb)
