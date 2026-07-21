"""
KSEB Dam Water Level Scraper (regex/PDF-only, no AI required)
================================================================
Source: PDF linked from https://sdma.kerala.gov.in/dam-water-level/
(filename pattern "KSEB-SITE-N.pdf", changes daily - found automatically).

NOTE: an earlier version of this script used dams.kseb.in's WordPress REST
API to find the latest post. That API can return an empty/blocked response
(security plugins commonly disable REST API access for non-browser
requests), so this version instead parses the KSDMA-hosted PDF directly -
the same reliable pattern as irrigation_dam_scraper.py.

IMPORTANT QUIRK handled here: many dams only publish SOME of their
Rule/Blue/Orange/Red threshold levels - and critically, when fewer than
4 are present, they are RIGHT-ALIGNED (i.e. a single published value is
always Red, two values are Orange+Red, etc.), not left-aligned from
Rule level. This was verified against real government data where e.g.
Moozhiyar/Kallarkutty/Erattayar each publish only ONE threshold, and it
is always their Red alert level - never Blue. See _split_numeric_tokens
and map_number_tokens for the general (0-4 value) handling.

Usage:
  pip install requests pdfplumber
  python dam_scraper.py
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
STATE_FILE = os.path.join(os.path.dirname(__file__), "dam_state.json")
COLORS_FILE = os.path.join(os.path.dirname(__file__), "dam_colors.json")

IST = timezone(timedelta(hours=5, minutes=30))

# Coordinates for the 18 major KSEB reservoirs (sourced from a verified
# real data export - see project history).
DAM_COORDINATES = {
    "IDUKKI": (9.8436, 76.9762),
    "IDAMALAYAR": (10.221867602366947, 76.70603684268934),
    "KAKKI (ANATHODE)": (9.341667, 77.15),
    "BANASURASAGAR": (11.6709, 75.9504),
    "SHOLAYAR": (10.3178, 76.7342),
    "MADUPETTY": (10.1063, 77.1238),
    "ANAYIRANKAL": (10.009515341318457, 77.20724298186308),
    "PONMUDI": (9.9604, 77.0565),
    "KUTTIYADI": (11.551, 75.925),
    "PAMBA": (9.3906, 77.1598),
    "PORINGALKUTHU": (10.3152, 76.6344),
    "KUNDALA": (10.14358754366575, 77.19868256414041),
    "KALLARKUTTY": (9.98, 77.001389),
    "ERATTAYAR": (9.8103, 77.106),
    "LOWER PERIYAR": (9.962, 76.9568),
    "MOOZHIYAR": (9.308, 77.0656),
    "KALLAR": (9.8255, 77.1562),
    "SENGULAM": (10.010833, 77.0325),
}

FRIENDLY_NAME_OVERRIDES = {
    "SENGULAM": "Chenkulam",
}

PLACEHOLDER_TOKENS = {"-", "_", "N/A", "NA", "\u2013"}


# ---------------------------------------------------------------------------
# 1. Find + download today's PDF
# ---------------------------------------------------------------------------

def find_kseb_pdf_url() -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; mazha-live-bot/1.0)"}
    resp = requests.get(DAM_PAGE_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    html = resp.text
    matches = re.findall(r'href="([^"]*kseb[^"]*\.pdf)"', html, re.IGNORECASE)
    if not matches:
        raise RuntimeError("Could not find KSEB PDF link on dam-water-level page")
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
# 2. Line classification helpers (same approach as irrigation_dam_scraper.py)
# ---------------------------------------------------------------------------

def _ascii_ratio(line: str) -> float:
    if not line:
        return 0.0
    ascii_chars = sum(1 for c in line if ord(c) < 128)
    return ascii_chars / len(line)


def _is_english_line(line: str) -> bool:
    return _ascii_ratio(line) > 0.7 and bool(re.search(r"[A-Za-z]", line))


NUMBERISH_RE = re.compile(r"^[\d.]+%?$|^(N/A|NA|-|_|\u2013)$", re.IGNORECASE)


def _strip_units(line: str) -> str:
    """Remove standalone unit words ('m', 'ft') that appear as separate
    tokens (e.g. '981.46 m' -> '981.46'), so positional token-counting
    isn't thrown off by units some dams report in feet vs metres."""
    return re.sub(r"\b(m|ft)\b", "", line, flags=re.IGNORECASE)


MAX_EXPECTED_TOKENS = 10  # FRL, WL, rule, blue, orange, red, gross, live, pct, spillway


def _split_numeric_tokens(line: str):
    """Extracts the leading run of numeric/placeholder tokens (after
    stripping unit words), returning (tokens, trailing_remainder_text) -
    same pattern as irrigation_dam_scraper.py, since remarks sometimes
    follow on the same line as the numbers. Capped at MAX_EXPECTED_TOKENS
    so a stray leaked digit from garbled remarks text can't get wrongly
    absorbed as data and shift the field mapping."""
    cleaned = _strip_units(line)
    tokens_all = cleaned.split()
    numeric_tokens = []
    remainder_idx = None
    for idx, t in enumerate(tokens_all):
        if len(numeric_tokens) >= MAX_EXPECTED_TOKENS:
            remainder_idx = idx
            break
        if NUMBERISH_RE.match(t):
            numeric_tokens.append(t)
        else:
            remainder_idx = idx
            break
    remainder = " ".join(tokens_all[remainder_idx:]) if remainder_idx is not None else ""
    return numeric_tokens, remainder


def _is_numbers_line(line: str) -> bool:
    numeric_tokens, _ = _split_numeric_tokens(line)
    return len(numeric_tokens) >= 6


def _clean_token(tok) -> str:
    if tok is None:
        return ""
    t = str(tok).strip().rstrip("%")
    return "" if t.upper() in PLACEHOLDER_TOKENS or t == "" else t


def map_number_tokens(tokens: list) -> dict:
    """FRL, WaterLevel, [0-4 threshold values], Gross, Live, Pct, Spillway.

    The threshold values (Rule/Blue/Orange/Red) are RIGHT-ALIGNED when
    fewer than 4 are present - verified against real data where a single
    published threshold is always Red, never Blue. See module docstring.
    """
    if len(tokens) < 6:
        return None

    frl = tokens[0]
    wl = tokens[1]
    rest = tokens[2:]

    # Last 4 tokens are always Gross, Live, Pct, Spillway
    tail = rest[-4:] if len(rest) >= 4 else rest[:]
    while len(tail) < 4:
        tail.append("")
    gross, live, pct, spillway = tail[0], tail[1], tail[2], tail[3]

    # Whatever's left (0-4 tokens) are the thresholds, RIGHT-aligned into
    # [ruleLevel, blueLevel, orangeLevel, redLevel]
    threshold_tokens = rest[:-4] if len(rest) > 4 else []
    slots = ["", "", "", ""]  # rule, blue, orange, red
    n = min(len(threshold_tokens), 4)
    for i in range(n):
        slots[4 - n + i] = threshold_tokens[len(threshold_tokens) - n + i]
    rule_level, blue_level, orange_level, red_level = slots

    return {
        "FRL": _clean_token(frl),
        "waterLevel": _clean_token(wl),
        "ruleLevel": _clean_token(rule_level),
        "blueLevel": _clean_token(blue_level),
        "orangeLevel": _clean_token(orange_level),
        "redLevel": _clean_token(red_level),
        "liveStorageAtFRL": _clean_token(gross),
        "liveStorage": _clean_token(live),
        "storagePercentage": _clean_token(pct),
        "spillwayRelease": _clean_token(spillway),
    }


# ---------------------------------------------------------------------------
# 3. Main line-by-line parser
# ---------------------------------------------------------------------------

def _extract_line1_remarks(line: str) -> str:
    """Line 1 (Malayalam name+district) sometimes has stray English remarks
    text glued onto it due to PDF layout overlap (seen in real data for one
    dam whose remarks line visually overlapped the name column). Strips
    (cid:NNN) placeholder glyphs and Malayalam-range Unicode, then returns
    whatever real English text (3+ letters) remains, or "" if none."""
    cleaned = re.sub(r"\(cid:\d+\)", "", line)
    cleaned = re.sub(r"[\u0D00-\u0D7F]", "", cleaned)
    cleaned = re.sub(r"[()]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not re.search(r"[A-Za-z]{3,}", cleaned):
        return ""
    return cleaned


def _split_name_district(line3: str):
    """Parses 'Kakki (Anathode) (Pathanamthitta)' -> name='Kakki (Anathode)',
    district='Pathanamthitta', trailing=''.
    Also handles '(Banasurasagar) (Wayanad) Tunnel discharge- Nil' ->
    name='Banasurasagar', district='Wayanad', trailing='Tunnel discharge- Nil'
    (some rows have remarks-overflow text after the district group, not
    anchored to end of line - greedy match finds the LAST paren group
    wherever it falls, treating anything after it as trailing overflow)."""
    m = re.match(r"^(.*)\(([^)]*)\)(.*)$", line3.strip())
    if not m:
        return line3.strip(), "", ""
    name_part, district_part, trailing = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    return name_part, district_part, trailing


def parse_dam_table(raw_text: str, last_update: str) -> dict:
    """Real structure (verified against actual pdfplumber output) is 3 lines
    per dam:
      line1: Malayalam name + Malayalam district (glyph/cid-encoded, ignored)
      line2: "{index} {FRL} {WaterLevel} [0-4 thresholds] {Gross} {Live} {Pct} {Spillway} [remarks]"
      line3: "EnglishName (EnglishDistrict)"
    Detected by scanning for a line matching '^{expected_index}\\s+...' —
    the line BEFORE it is line1, the line AFTER it is line3.
    """
    lines = [ln.strip() for ln in raw_text.split("\n")]
    lines = [ln for ln in lines if ln]

    dams = []
    expected_index = 1
    max_index = 30
    i = 0

    while i < len(lines):
        m = re.match(r"^(\d{1,2})\s+(.*)$", lines[i])
        if m and int(m.group(1)) == expected_index and expected_index <= max_index:
            line1 = lines[i - 1] if i - 1 >= 0 else ""
            numbers_text = m.group(2)
            line3 = lines[i + 1] if i + 1 < len(lines) else ""

            tokens, inline_remainder = _split_numeric_tokens(numbers_text)
            numbers_dict = map_number_tokens(tokens)

            name_raw, district_en, line3_trailing = _split_name_district(line3)
            name_stripped = name_raw.strip()
            if name_stripped.startswith("(") and name_stripped.endswith(")"):
                name_stripped = name_stripped[1:-1].strip()
            official_name = name_stripped.upper()

            line1_remarks = _extract_line1_remarks(line1)
            remarks = " ".join(p for p in [line1_remarks, inline_remainder, line3_trailing] if p).strip()

            if numbers_dict is not None and official_name:
                lat, lng = DAM_COORDINATES.get(official_name, (None, None))
                friendly = FRIENDLY_NAME_OVERRIDES.get(official_name, official_name.title())

                dams.append({
                    "id": str(expected_index),
                    "name": friendly,
                    "officialName": official_name,
                    "district": district_en,
                    "MWL": numbers_dict["FRL"],
                    "FRL": numbers_dict["FRL"],
                    "liveStorageAtFRL": numbers_dict["liveStorageAtFRL"],
                    "ruleLevel": numbers_dict["ruleLevel"],
                    "blueLevel": numbers_dict["blueLevel"],
                    "orangeLevel": numbers_dict["orangeLevel"],
                    "redLevel": numbers_dict["redLevel"],
                    "latitude": lat,
                    "longitude": lng,
                    "remarks": remarks,
                    "data": [{
                        "date": last_update,
                        "waterLevel": numbers_dict["waterLevel"],
                        "liveStorage": numbers_dict["liveStorage"],
                        "storagePercentage": numbers_dict["storagePercentage"],
                        "spillwayRelease": numbers_dict["spillwayRelease"],
                    }],
                })
            expected_index += 1
            i += 2  # skip past line3 too
        else:
            i += 1

    return {"lastUpdate": last_update, "dams": dams}


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


def compute_alert_color(dam: dict) -> str:
    if not dam.get("data"):
        return "green"
    latest = dam["data"][-1]
    water_level = _to_float(latest.get("waterLevel"))
    if water_level is None:
        return "green"

    red = _to_float(dam.get("redLevel"))
    orange = _to_float(dam.get("orangeLevel"))
    blue = _to_float(dam.get("blueLevel"))

    if red is not None and water_level >= red:
        return "red"
    if orange is not None and water_level >= orange:
        return "orange"
    if blue is not None and water_level >= blue:
        return "blue"
    return "green"


def build_dam_colors(data: dict) -> dict:
    return {dam["name"]: compute_alert_color(dam) for dam in data.get("dams", [])}


# ---------------------------------------------------------------------------
# 5. Save state
# ---------------------------------------------------------------------------

def save_state(data: dict):
    scraped_at = datetime.now(IST).isoformat()
    colors = build_dam_colors(data)

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
    pdf_url = find_kseb_pdf_url()
    print(f"[info] Found PDF: {pdf_url}")

    pdf_bytes = download_pdf(pdf_url)
    raw_text = extract_pdf_text(pdf_bytes)
    last_update = extract_last_update_date(raw_text)

    data = parse_dam_table(raw_text, last_update)
    data["sourceUrl"] = pdf_url

    if not data["dams"]:
        debug_path = os.path.join(os.path.dirname(__file__), "debug_kseb_raw_text.txt")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
        raise RuntimeError(
            f"Parsed 0 dams - PDF structure may have changed. "
            f"Raw extracted text saved to {debug_path} - please share its contents so the parser can be fixed against the real output."
        )

    print(json.dumps(data, ensure_ascii=False, indent=2))

    colors = build_dam_colors(data)
    print("\n=== Dam alert colors (for map) ===")
    print(json.dumps(colors, ensure_ascii=False, indent=2))

    save_state(data)
    return data


if __name__ == "__main__":
    run()
