# -*- coding: utf-8 -*-
"""
extraction.py
שני מסלולי חילוץ חלופיים לאותו ממשק. בוחרים מסלול ב-EXTRACTION_MODE.

  "ocr"    - מנדר כל עמוד PDF לתמונה ברזולוציה גבוהה, מריץ Tesseract+heb על
             אריחים, ומפעיל regex על הטקסט שחזר. עצמאי לחלוטין, לא תלוי באף
             API חיצוני, אך תלוי באיכות ה-OCR על תוויות עבריות מוטות/קטנות.
             *** דורש: tesseract-ocr + חבילת שפה heb מותקנת במערכת ***

  "claude" - שולח אריחי תמונה ל-Claude (Anthropic API) עם פרומפט שמבקש
             להחזיר JSON מובנה של הפריטים שזוהו באריח. יותר מדויק על תוויות
             מוטות/Leader-lines, אך תלוי במפתח API ובעלות לפי בקשה.

שני המסלולים מחזירים את אותו טיפוס פלט: List[ExtractedItem] (ראו categories.py)
כך שכל שאר האפליקציה (תמחור, תצוגה, ייצוא Excel) לא משתנה בין מסלול למסלול.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
from typing import List, Tuple

import fitz  # PyMuPDF
from PIL import Image

from categories import (
    ExtractedItem,
    TOP_CATEGORY_DUCTS,
    TOP_CATEGORY_FANS,
    TOP_CATEGORY_OTHER,
    RE_DUCT_RECT,
    RE_DUCT_ROUND_CM,
    RE_DUCT_ROUND_INCH,
    FAN_KEYWORDS,
    SILENCER_KEYWORDS,
    VENT_KEYWORDS,
    classify_vent_target,
    extract_nearby_specs,
)

# ברירת מחדל; אפשר לשנות מתוך app.py לפי בחירת המשתמש בסיידבר
EXTRACTION_MODE = os.environ.get("VENTA_EXTRACTION_MODE", "ocr")

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
# מסלול 2: Claude API - חזותי, מדויק יותר על תוויות מוטות/leader-lines
# ---------------------------------------------------------------------------

CLAUDE_EXTRACTION_SYSTEM_PROMPT = """אתה יועץ אוורור ופינוי עשן שמנתח תמונה של חלק מתוכנית הנדסית (AutoCAD).
זהה את כל הפריטים הבאים בתמונה, אם קיימים:
1. תעלות (מלבניות - שתי מידות ב-ס"מ; עגולות - קוטר ב-ס"מ)
2. מפוחים ומשתיקים (ציין דגם אם מצוין, ספיקה ב-CFM, לחץ ב-Pa, קוטר/מידה, הספק ב-KW, רעש ב-dBA אם מצוין)
3. ונטות - וצריך לקבוע את היעד שלהן: שירותים / מקלחת / מטבח, לפי הטקסט/החדר הסמוך בתמונה.
   לכל ונטה ציין ספיקה (CFM), לחץ (Pa), קוטר/מידה.

החזר רק JSON תקני (בלי טקסט נוסף, בלי markdown), במבנה:
{"items": [
  {"top_category": "תעלות"|"מפוחים ומשתיקים"|"ונטות - שירותים"|"ונטות - מקלחת"|"ונטות - מטבח",
   "sub_type": "string", "model": "string או ריק", "diameter_cm": number או null,
   "duct_w_cm": number או null, "duct_h_cm": number או null,
   "cfm": number או null, "pressure_pa": number או null, "power_kw": number או null,
   "noise_dba": number או null, "quantity": integer, "confidence": "גבוה"|"בינוני"|"לאימות",
   "note": "string"}
]}
אם אין פריטים רלוונטיים בתמונה, החזר {"items": []}. אל תמציא מספרים - אם שדה לא ברור מהתמונה, החזר null ושים confidence "לאימות".
"""


def _image_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _call_claude_on_tile(tile: Image.Image, api_key: str, model: str = "claude-sonnet-4-6") -> dict:
    """קורא ל-Anthropic API עם תמונת אריח בודד, ומבקש JSON מובנה.
    דורש: pip install anthropic, ומפתח API תקין (ANTHROPIC_API_KEY)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    img_b64 = _image_to_base64(tile)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=CLAUDE_EXTRACTION_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": "זהה את כל הפריטים הרלוונטיים בתמונה הזו והחזר JSON בלבד."},
            ],
        }],
    )
    raw_text = "".join(block.text for block in response.content if hasattr(block, "text"))
    raw_text = re.sub(r"^```json\s*|\s*```$", "", raw_text.strip())
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {"items": [], "_parse_error": raw_text[:500]}


def extract_items_claude(pdf_bytes: bytes, source_file: str, section: str, api_key: str,
                          floor_multiplier: int = 1, dpi: int = RENDER_DPI_DEFAULT,
                          cols: int = TILE_COLS_DEFAULT, model: str = "claude-sonnet-4-6",
                          progress_cb=None) -> List[ExtractedItem]:
    """מסלול Claude API מלא: רינדור עמודים -> אריחים -> קריאת API -> ExtractedItem.
    יותר יקר ואיטי ממסלול OCR, אך מדויק משמעותית על טקסט מוטה/leader-lines."""
    if not api_key:
        raise RuntimeError("חסר מפתח Anthropic API. הגדר משתנה סביבה ANTHROPIC_API_KEY או הזן בסיידבר.")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    n_pages = len(doc)
    all_items: List[ExtractedItem] = []
    for page_idx in range(n_pages):
        tiles = render_pdf_page_tiles(pdf_bytes, page_index=page_idx, dpi=dpi, cols=cols)
        for t_idx, tile in enumerate(tiles):
            try:
                result = _call_claude_on_tile(tile, api_key, model=model)
            except Exception as exc:
                all_items.append(ExtractedItem(
                    top_category=TOP_CATEGORY_OTHER, sub_type="שגיאת API",
                    source_file=source_file, section=section,
                    confidence="לאימות", note=f"שגיאה בקריאת Claude API: {exc}",
                ))
                continue
            for raw in result.get("items", []):
                all_items.append(ExtractedItem(
                    top_category=raw.get("top_category", TOP_CATEGORY_OTHER),
                    sub_type=raw.get("sub_type", ""),
                    model=raw.get("model", "") or "",
                    diameter_cm=raw.get("diameter_cm"),
                    duct_w_cm=raw.get("duct_w_cm"),
                    duct_h_cm=raw.get("duct_h_cm"),
                    cfm=raw.get("cfm"),
                    pressure_pa=raw.get("pressure_pa"),
                    power_kw=raw.get("power_kw"),
                    noise_dba=raw.get("noise_dba"),
                    quantity=int(raw.get("quantity") or 1),
                    floor_multiplier=floor_multiplier,
                    source_file=source_file, section=section,
                    confidence=raw.get("confidence", "בינוני"),
                    note=raw.get("note", ""),
                ))
            if progress_cb:
                progress_cb(page_idx, n_pages, t_idx, len(tiles))
    return all_items


# ---------------------------------------------------------------------------
# נקודת כניסה משותפת - app.py קורא רק לפונקציה הזו
# ---------------------------------------------------------------------------

def extract_items(pdf_bytes: bytes, source_file: str, section: str, floor_multiplier: int = 1,
                   mode: str = None, api_key: str = "", model: str = "claude-sonnet-4-6",
                   dpi: int = RENDER_DPI_DEFAULT, cols: int = TILE_COLS_DEFAULT,
                   progress_cb=None) -> List[ExtractedItem]:
    """נקודת כניסה אחת לשני המסלולים. mode=None -> משתמש ב-EXTRACTION_MODE הגלובלי."""
    chosen = mode or EXTRACTION_MODE
    if chosen == "ocr":
        return extract_items_ocr(pdf_bytes, source_file, section, floor_multiplier, dpi, cols, progress_cb)
    elif chosen == "claude":
        return extract_items_claude(pdf_bytes, source_file, section, api_key, floor_multiplier,
                                     dpi, cols, model, progress_cb)
    else:
        raise ValueError(f"מסלול חילוץ לא מוכר: {chosen!r} (צריך 'ocr' או 'claude')")
