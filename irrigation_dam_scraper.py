"""
Irrigation Department Reservoir Scraper (regex/PDF-only, no AI required)
==========================================================================
Source: PDF linked from https://sdma.kerala.gov.in/dam-water-level/
(filename pattern "Irr-Site-N.pdf", changes daily - found automatically,
same approach as the rain scraper).

This covers Kerala's IRRIGATION DEPARTMENT reservoirs (Neyyar, Kallada,
Malampuzha, Peechi, Walayar, Kuttiyadi, Pazhassi, etc.) - a DIFFERENT set
of dams from the KSEB ones in dam_scraper.py (KSEB = power-generation
reservoirs; Irrigation Dept = irrigation/drinking-water reservoirs).
Together, dam_scraper.py + irrigation_dam_scraper.py cover Kerala's major
dams from both departments.

Unlike the KSEB PDF, this one extracts to genuinely readable English text
(Malayalam glyph lines still render as mojibake, but are simply skipped -
no OCR/AI needed).

IMPORTANT QUIRK handled here: several entries are barrages/regulators
(Maniyar, Bhoothathankettu, Siruvani, Moolathara, Pazhassi) that don't have
Blue/Orange/Red alert levels published at all - their numbers line has 6
tokens instead of the usual 9. This parser detects and handles both cases
generically (see _split_numeric_tokens).

Usage:
  pip install requests pdfplumber
  python irrigation_dam_scraper.py
"""

import os
import re
import json
import io
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
import pdfplumber

DAM_PAGE_URL = "https://sdma.kerala.gov.in/dam-water-level/"
STATE_FILE = os.path.join(os.path.dirname(__file__), "irrigation_dam_state.json")
COLORS_FILE = os.path.join(os.path.dirname(__file__), "irrigation_dam_colors.json")

IST = timezone(timedelta(hours=5, minutes=30))

# The Irrigation Dept publishes these 20 reservoirs in this EXACT fixed
# order every day (verified against real government PDF output). Using a
# fixed lookup by position is deliberately more robust than parsing
# name/district from the PDF text, because for 3 of the 20 rows (Malankara,
# Kuttiyadi, Pazhassi) the PDF's text extraction interleaves individual
# characters from overlapping columns (a rendering artifact) - the name text
# becomes literally unparseable (e.g. "Ma \u0d2e l \u0d32 an..."), while the
# NUMERIC data on those same rows extracts cleanly. So: trust the fixed
# order for name/district/coordinates, and only parse numbers from the text.
RESERVOIR_ORDER = [
    ("Neyyar", "Thiruvananthapuram"),
    ("Kallada", "Kollam"),
    ("Maniyar (Barrage)", "Pathanamthitta"),
    ("Malankara", "Idukki"),
    ("Bhoothathankettu (Barrage)", "Ernakulam"),
    ("Vazhani", "Thrissur"),
    ("Chimoni", "Thrissur"),
    ("Peechi", "Thrissur"),
    ("Siruvani (Inter state waters)", "Palakkad"),
    ("Kanjirappuzha", "Palakkad"),
    ("Meenkara", "Palakkad"),
    ("Walayar", "Palakkad"),
    ("Malampuzha", "Palakkad"),
    ("Pothundy", "Palakkad"),
    ("Chulliyar", "Palakkad"),
    ("Mangalam", "Palakkad"),
    ("Moolathara (Regulator)", "Palakkad"),
    ("Kuttiyadi", "Kozhikode"),
    ("Karapuzha", "Wayanad"),
    ("Pazhassi (Barrage)", "Kannur"),
]

DAM_COORDINATES = {
    "Neyyar": (8.4029, 77.1494),
    "Kallada": (9.1319, 76.8494),
    "Maniyar (Barrage)": (9.3372, 76.9328),
    "Malankara": (9.7194, 76.8756),
    "Bhoothathankettu (Barrage)": (10.1667, 76.5833),
    "Vazhani": (10.5833, 76.2667),
    "Chimoni": (10.5333, 76.4167),
    "Peechi": (10.5333, 76.3667),
    "Siruvani (Inter state waters)": (10.9167, 76.6667),
    "Kanjirappuzha": (10.8333, 76.5833),
    "Meenkara": (10.85, 76.6833),
    "Walayar": (10.85, 76.75),
    "Malampuzha": (10.8283, 76.6825),
    "Pothundy": (10.6833, 76.5833),
    "Chulliyar": (10.7333, 76.65),
    "Mangalam": (10.7667, 76.55),
    "Moolathara (Regulator)": (10.9667, 76.6833),
    "Kuttiyadi": (11.6167, 75.85),
    "Karapuzha": (11.6833, 76.1167),
    "Pazhassi (Barrage)": (11.9833, 75.6),
}

FRIENDLY_NAMES_OVERRIDE = {
    "Maniyar (Barrage)": "Maniyar",
    "Bhoothathankettu (Barrage)": "Bhoothathankettu",
    "Siruvani (Inter state waters)": "Siruvani",
    "Moolathara (Regulator)": "Moolathara",
    "Pazhassi (Barrage)": "Pazhassi",
}

# These reservoirs are known (from real government data patterns) to never
# publish Blue/Orange/Red thresholds at all (barrages/regulators/inter-state
# water sharing points, not monitored the same way as proper reservoirs).
# Hardcoding this avoids relying on token-count inference for these specific
# rows - which matters because Pazhassi's row has a stray leaked digit from
# a PDF character-interleaving artifact that would otherwise get miscounted
# as if it were threshold data.
KNOWN_ZERO_THRESHOLD_RESERVOIRS = {
    "Maniyar (Barrage)",
    "Bhoothathankettu (Barrage)",
    "Siruvani (Inter state waters)",
    "Moolathara (Regulator)",
    "Pazhassi (Barrage)",
}

PLACEHOLDER_TOKENS = {"-", "_", "N/A", "NA", "–"}


# ---------------------------------------------------------------------------
# 1. Find + download today's PDF
# ---------------------------------------------------------------------------

def find_irrigation_pdf_url() -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; mazha-live-bot/1.0)"}
    resp = requests.get(DAM_PAGE_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    html = resp.text
    matches = re.findall(r'href="([^"]*irr[^"]*\.pdf)"', html, re.IGNORECASE)
    if not matches:
        raise RuntimeError("Could not find Irrigation Dept PDF link on dam-water-level page")
    return urljoin(DAM_PAGE_URL, matches[0])  # handles both relative ("/wp-content/...") and absolute URLs


def download_pdf(url: str) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; mazha-live-bot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content


def extract_pdf_text(pdf_bytes: bytes) -> str:
    parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 2. Line classification helpers
# ---------------------------------------------------------------------------

def _ascii_ratio(line: str) -> float:
    if not line:
        return 0.0
    ascii_chars = sum(1 for c in line if ord(c) < 128)
    return ascii_chars / len(line)


def _is_english_line(line: str) -> bool:
    """Heuristic: mostly ASCII letters/digits/punctuation = readable English line."""
    return _ascii_ratio(line) > 0.7 and bool(re.search(r"[A-Za-z]", line))


NUMBERISH_TOKEN_RE = re.compile(r"^[\d.]+%?$|^(N/A|NA|-|_|–)$", re.IGNORECASE)


MAX_EXPECTED_TOKENS = 9  # FRL, WL, blue, orange, red, gross, today, pct, outflow


def _split_numeric_tokens(line: str):
    """Takes only the LEADING run of numeric/placeholder tokens (handles
    rows where remarks text is appended on the same line as the numbers,
    e.g. '...41% 30.04 Outflow for power generation, URL - 106.68 m').
    Capped at MAX_EXPECTED_TOKENS: for 3 known rows the PDF's text
    extraction interleaves characters from garbled remarks with the data
    (a rendering artifact - see RESERVOIR_ORDER comment), and a stray bare
    digit from that garbled text can otherwise get wrongly absorbed as if
    it were part of the numeric data, shifting every field after it by one.
    Returns (numeric_tokens, trailing_remainder_text).
    """
    tokens = line.split()
    numeric_tokens = []
    remainder_idx = None
    for idx, t in enumerate(tokens):
        if len(numeric_tokens) >= MAX_EXPECTED_TOKENS:
            remainder_idx = idx
            break
        if NUMBERISH_TOKEN_RE.match(t):
            numeric_tokens.append(t)
        else:
            remainder_idx = idx
            break
    remainder = " ".join(tokens[remainder_idx:]) if remainder_idx is not None else ""
    return numeric_tokens, remainder


def _is_numbers_line(line: str) -> bool:
    """A line whose leading tokens are mostly numeric = the data row,
    regardless of whether trailing remarks text follows on the same line."""
    numeric_tokens, _ = _split_numeric_tokens(line)
    return len(numeric_tokens) >= 6


def _extract_line1_remarks(line: str) -> str:
    """Strips (cid:NNN) placeholder glyphs and Malayalam-range Unicode from
    a glyph-continuation line, returning whatever real English text (3+
    letters) remains, or '' if none. Best-effort remarks recovery."""
    cleaned = re.sub(r"\(cid:\d+\)", "", line)
    cleaned = re.sub(r"[\u0D00-\u0D7F]", "", cleaned)
    cleaned = re.sub(r"[()]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not re.search(r"[A-Za-z]{3,}", cleaned):
        return ""
    return cleaned


def _clean_token(tok) -> str:
    if tok is None:
        return ""
    t = str(tok).strip().rstrip("%")
    return "" if t.upper() in PLACEHOLDER_TOKENS or t == "" else t


def map_number_tokens(tokens: list) -> dict:
    """Maps a variable-length token list to named fields. Handles both the
    'full' 9-token row (FRL, WL, Blue, Orange, Red, Gross, Today, Pct, Outflow)
    and the 'barrage' 6-token row (FRL, WL, Gross, Today, Pct, Outflow) —
    and anything in between — generically, rather than hardcoding two cases.
    """
    if len(tokens) < 6:
        return None  # too malformed to trust

    frl = tokens[0]
    wl = tokens[1]
    remaining = tokens[2:]
    r = len(remaining)

    # Last 4 remaining tokens are always Gross, Today, Pct, Outflow.
    # Whatever's left before that (0 to 3 tokens) are Blue/Orange/Red.
    middle_count = max(0, min(3, r - 4))
    middle = remaining[:middle_count]
    tail = remaining[middle_count:middle_count + 4]

    while len(middle) < 3:
        middle.append("")
    while len(tail) < 4:
        tail.append("")

    blue, orange, red = middle[0], middle[1], middle[2]
    gross, today, pct, outflow = tail[0], tail[1], tail[2], tail[3]

    return {
        "FRL": _clean_token(frl),
        "waterLevel": _clean_token(wl),
        "blueLevel": _clean_token(blue),
        "orangeLevel": _clean_token(orange),
        "redLevel": _clean_token(red),
        "grossStorage": _clean_token(gross),
        "todayStorage": _clean_token(today),
        "storagePercentage": _clean_token(pct),
        "outflow": _clean_token(outflow),
    }


# ---------------------------------------------------------------------------
# 3. Main line-by-line parser
# ---------------------------------------------------------------------------

FIRST_NUMBER_RE = re.compile(r"\d+\.\d+|\d+%")


def parse_irrigation_reservoirs(raw_text: str, last_update: str) -> dict:
    """Real structure (verified against actual pdfplumber output): each
    reservoir is 2 lines - line A: '{index} {name/district text} {numbers} [remarks]',
    line B: Malayalam glyph continuation (sometimes with English remarks
    overflow). Name/district text on line A is UNRELIABLE for 3 of the 20
    rows (character-interleaving artifact - see RESERVOIR_ORDER comment),
    so this only extracts the index + numeric data from line A, and uses
    the fixed RESERVOIR_ORDER list for name/district/coordinates.
    """
    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]

    reservoirs = []
    expected_index = 1
    i = 0

    while i < len(lines) and expected_index <= len(RESERVOIR_ORDER):
        m = re.match(rf"^{expected_index}\s+(.*)$", lines[i])
        if m:
            rest_of_line = m.group(1)

            # Everything from the FIRST proper decimal number onward is the
            # numbers+remarks blob; whatever precedes it (name/district text)
            # is deliberately ignored - see docstring.
            num_match = FIRST_NUMBER_RE.search(rest_of_line)
            if num_match:
                numbers_and_remarks = rest_of_line[num_match.start():]
            else:
                numbers_and_remarks = rest_of_line

            tokens, inline_remainder = _split_numeric_tokens(numbers_and_remarks)

            # For known barrages/regulators (no thresholds published), trust
            # that domain knowledge over token-count inference - truncate to
            # exactly [FRL, WL, Gross, Today, Pct, Outflow] (6 tokens) and
            # push anything beyond back into the remainder/remarks, rather
            # than risking a stray leaked digit (interleaving artifact) being
            # miscounted as real data.
            name_for_check, _ = RESERVOIR_ORDER[expected_index - 1]
            if name_for_check in KNOWN_ZERO_THRESHOLD_RESERVOIRS and len(tokens) > 6:
                leftover = tokens[6:]
                tokens = tokens[:6]
                inline_remainder = " ".join(leftover + ([inline_remainder] if inline_remainder else []))

            numbers_dict = map_number_tokens(tokens)

            # Line B: Malayalam continuation, occasionally with English
            # remarks overflow - best-effort extraction, may be imperfect
            # for the same 3 rows affected by the interleaving artifact.
            line_b_remarks = ""
            if i + 1 < len(lines) and not re.match(r"^\d{1,2}\s", lines[i + 1]):
                line_b_remarks = _extract_line1_remarks(lines[i + 1])
                i += 1  # consume line B

            remarks = " ".join(p for p in [inline_remainder, line_b_remarks] if p).strip()

            if numbers_dict is not None:
                name, district = RESERVOIR_ORDER[expected_index - 1]
                lat, lng = DAM_COORDINATES.get(name, (None, None))
                friendly = FRIENDLY_NAMES_OVERRIDE.get(name, name.split("(")[0].strip())

                reservoirs.append({
                    "id": str(expected_index),
                    "name": friendly,
                    "officialName": name,
                    "district": district,
                    "FRL": numbers_dict["FRL"],
                    "blueLevel": numbers_dict["blueLevel"],
                    "orangeLevel": numbers_dict["orangeLevel"],
                    "redLevel": numbers_dict["redLevel"],
                    "latitude": lat,
                    "longitude": lng,
                    "remarks": remarks,
                    "data": [{
                        "date": last_update,
                        "waterLevel": numbers_dict["waterLevel"],
                        "grossStorage": numbers_dict["grossStorage"],
                        "todayStorage": numbers_dict["todayStorage"],
                        "storagePercentage": numbers_dict["storagePercentage"],
                        "outflow": numbers_dict["outflow"],
                    }],
                })
            expected_index += 1
        i += 1

    return {"lastUpdate": last_update, "reservoirs": reservoirs}


def extract_last_update_date(raw_text: str) -> str:
    m = re.search(r"(\d{2}/\d{2}/\d{4})", raw_text)
    if m:
        return m.group(1).replace("/", ".")
    return datetime.now(IST).strftime("%d.%m.%Y")


# ---------------------------------------------------------------------------
# 4. Alert color computation
# ---------------------------------------------------------------------------

def _to_float(val):
    if val is None or val == "":
        return None
    cleaned = re.sub(r"[a-zA-Z]", "", str(val)).strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def compute_alert_color(reservoir: dict) -> str:
    if not reservoir.get("data"):
        return "green"
    latest = reservoir["data"][-1]
    water_level = _to_float(latest.get("waterLevel"))
    if water_level is None:
        return "green"

    red = _to_float(reservoir.get("redLevel"))
    orange = _to_float(reservoir.get("orangeLevel"))
    blue = _to_float(reservoir.get("blueLevel"))

    if red is not None and water_level >= red:
        return "red"
    if orange is not None and water_level >= orange:
        return "orange"
    if blue is not None and water_level >= blue:
        return "blue"
    return "green"  # includes barrages with no published thresholds


def build_colors(data: dict) -> dict:
    return {r["name"]: compute_alert_color(r) for r in data.get("reservoirs", [])}


# ---------------------------------------------------------------------------
# 5. Save state
# ---------------------------------------------------------------------------

def save_state(data: dict):
    scraped_at = datetime.now(IST).isoformat()
    colors = build_colors(data)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({**data, "scraped_at": scraped_at}, f, ensure_ascii=False, indent=2)

    with open(COLORS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": scraped_at,
            "lastUpdate": data.get("lastUpdate"),
            "colors": colors,
        }, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    print(f"[info] Fetching {DAM_PAGE_URL} ...")
    pdf_url = find_irrigation_pdf_url()
    print(f"[info] Found PDF: {pdf_url}")

    pdf_bytes = download_pdf(pdf_url)
    raw_text = extract_pdf_text(pdf_bytes)
    last_update = extract_last_update_date(raw_text)

    data = parse_irrigation_reservoirs(raw_text, last_update)
    data["sourceUrl"] = pdf_url

    if not data["reservoirs"]:
        debug_path = os.path.join(os.path.dirname(__file__), "debug_irrigation_raw_text.txt")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
        raise RuntimeError(
            f"Parsed 0 reservoirs - PDF structure may have changed. "
            f"Raw extracted text saved to {debug_path} - please share its contents so the parser can be fixed against the real output."
        )

    print(json.dumps(data, ensure_ascii=False, indent=2))

    colors = build_colors(data)
    print("\n=== Irrigation reservoir colors (for map) ===")
    print(json.dumps(colors, ensure_ascii=False, indent=2))

    save_state(data)
    return data


if __name__ == "__main__":
    run()
