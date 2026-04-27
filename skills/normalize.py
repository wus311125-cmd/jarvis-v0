"""Normalization helpers for Jarvis intake data.

Pure functions only — no side effects, no DB access.
"""
import re
from datetime import datetime
from typing import Any


def clean_amount(raw: Any) -> float | None:
    """Strip currency prefix, convert to positive float.

    Examples:
    >>> clean_amount("HK$ 531")
    531.0
    >>> clean_amount("-350.00")
    350.0
    >>> clean_amount(None) is None
    True
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # remove common currency prefixes/symbols
    s = re.sub(r'^(HK\$|HKD|USD|US\$|CNY|CN¥|¥|\$)\s*', '', s, flags=re.IGNORECASE)
    s = s.replace(',', '')
    # find first number-like token
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    if not m:
        return None
    try:
        return abs(float(m.group(0)))
    except ValueError:
        return None


def clean_currency(raw: Any) -> str:
    """Standardize to HKD|USD|CNY, default HKD.

    Examples:
    >>> clean_currency("hkd")
    'HKD'
    >>> clean_currency("")
    'HKD'
    """
    if not raw:
        return "HKD"
    s = str(raw).strip().upper()
    mapping = {
        "HKD": "HKD", "HK$": "HKD", "USD": "USD", "US$": "USD",
        "$": "HKD", "CNY": "CNY", "CN¥": "CNY", "¥": "CNY", "RMB": "CNY"
    }
    return mapping.get(s, "HKD")


def clean_date(raw: Any) -> str | None:
    """Parse common date formats to ISO YYYY-MM-DD.

    Examples:
    >>> clean_date("27/04/2026")
    '2026-04-27'
    >>> clean_date("") is None
    True
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # try common formats
    fmts = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y")
    for fmt in fmts:
        piece = s[:10] if fmt == "%Y-%m-%d" else s
        try:
            dt = datetime.strptime(piece, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue

    # fallback: if already looks like ISO take first 10 chars
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        return s[:10]
    return None


def clean_merchant(raw: Any) -> str:
    """Strip whitespace, collapse spaces, title case.

    Examples:
    >>> clean_merchant("  some   shop  ")
    'Some Shop'
    >>> clean_merchant("")
    ''
    """
    if not raw:
        return ""
    s = str(raw).strip()
    s = re.sub(r'\s+', ' ', s)
    return s.title() if s else ""


def normalize_extracted(data: dict) -> dict:
    """Apply all cleaners to an extracted_json dict. Returns new dict.

    Handles both shapes: {"extracted": {...}} or a flat dict.
    """
    # preserve top-level keys unchanged; only clean inside `extracted` if present
    if not isinstance(data, dict):
        return data

    result = dict(data)  # shallow copy

    # If there is a nested extracted dict, clean its fields in-place
    ext = result.get("extracted")
    if isinstance(ext, dict):
        if "amount" in ext:
            cleaned = clean_amount(ext.get("amount"))
            ext["amount"] = cleaned if cleaned is not None else 0

        if "currency" in ext:
            ext["currency"] = clean_currency(ext.get("currency"))
        else:
            ext["currency"] = clean_currency(ext.get("currency"))

        if "date" in ext:
            ext_date = clean_date(ext.get("date"))
            ext["date"] = ext_date if ext_date is not None else ""

        if "merchant" in ext:
            ext["merchant"] = clean_merchant(ext.get("merchant"))

        result["extracted"] = ext

    else:
        # flat-shape fallback: if top-level has amount/currency keys, clean them but do not wrap
        if "amount" in result and "extracted" not in data:
            cleaned = clean_amount(result.get("amount"))
            result["amount"] = cleaned if cleaned is not None else 0
        if "currency" in result and "extracted" not in data:
            result["currency"] = clean_currency(result.get("currency"))

    return result


# smoke tests
if __name__ == "__main__":
    assert clean_amount("HK$ 531") == 531.0
    assert clean_amount("-350.00") == 350.0
    assert clean_amount(None) is None
    assert clean_currency("") == "HKD"
    assert clean_currency("usd") == "USD"
    assert clean_date("27/04/2026") == "2026-04-27"
    assert clean_date("2026-04-27") == "2026-04-27"
    assert clean_date("") is None
    assert clean_merchant("  some   shop  ") == "Some Shop"
    assert clean_merchant("") == ""
    print("normalize.py: all smoke tests passed ✅")
