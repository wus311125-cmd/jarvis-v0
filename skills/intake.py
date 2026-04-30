import os
import sqlite3
import json
import datetime
from pathlib import Path
from typing import Any, Dict

VAULT = Path(os.environ.get("OBSIDIAN_VAULT", "~/ObsidianVault.main")).expanduser()
DB_PATH = Path(os.environ.get("JARVIS_DB", "~/jarvis-v0/jarvis.db")).expanduser()
CONFIDENCE_THRESHOLD = 0.7


INTAKE_SCHEMA = """
CREATE TABLE IF NOT EXISTS intake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    source TEXT,
    raw_input TEXT,
    type TEXT,
    extracted_json TEXT,
    needs_confirmation INTEGER DEFAULT 0
);
"""


def init_db(path: Path = DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(INTAKE_SCHEMA)
    conn.commit()
    conn.close()


def store_intake(record: Dict[str, Any], db_path: Path = DB_PATH) -> int:
    """Store an intake record and return row id."""
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    ts = record.get("timestamp") or datetime.datetime.now().isoformat()
    src = record.get("source", "telegram")
    raw = record.get("raw_input", "")
    typ = record.get("type")
    ej = record.get("extracted_json")
    ej_s = json.dumps(ej, ensure_ascii=False) if ej is not None else None
    needs = int(record.get("needs_confirmation", 0))
    cur.execute(
        "INSERT INTO intake (timestamp, source, raw_input, type, extracted_json, needs_confirmation) VALUES (?,?,?,?,?,?)",
        (ts, src, raw, typ, ej_s, needs),
    )
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    return rowid


def classify_and_extract(img_bytes: bytes, caption: str | None = None) -> Dict[str, Any]:
    """Lightweight classifier used in tests. Returns a dict shaped like parsed extraction.

    For offline tests we keep confidence low so the code goes through confirmation flow.
    """
    # minimal stub: return empty extracted_json and low confidence
    return {"extracted_json": {"summary": caption or "", "amount": None}, "confidence": 0.0}


def process_text(text: str, source: str = "telegram") -> Dict[str, Any]:
    """Simple handler to support E2E tests used by bot fallbacks.

    - handles leading + / - amounts and stores expenses via skills.expense
    - otherwise returns ok=False
    """
    from skills import expense

    t = text.strip()
    # match leading +/-amount
    import re
    m = re.match(r"^\s*([+-])(\d+(?:\.\d+)?)(?:\s+(.*))?$", t)
    if m:
        sign, amt_s, rest = m.groups()
        try:
            amt = float(amt_s)
        except Exception:
            return {"ok": False, "message": "invalid amount"}
        rec = {
            "timestamp": datetime.datetime.now().isoformat(),
            "amount": abs(amt),
            "currency": "HKD",
            "category": None,
            "merchant": (rest or "").strip(),
            "date": datetime.date.today().isoformat(),
            "note": "",
            "source": source,
        }
        if sign == '+':
            rec["direction"] = 'income'
            # store as income (use expense table with direction)
            rowid = expense.store_expense(rec)
            return {"ok": True, "message": f"已記收入：{rec['amount']} HKD。", "rowid": rowid}
        else:
            rec["direction"] = 'expense'
            rowid = expense.store_expense(rec)
            return {"ok": True, "message": expense.format_expense_confirmation(rec), "rowid": rowid}

    # try parse free-form expense like '65 食飯'
    try:
        parsed = expense.parse_expense_text(t)
        rec = {
            "timestamp": datetime.datetime.now().isoformat(),
            "amount": parsed.get('amount'),
            "currency": parsed.get('currency','HKD'),
            "category": parsed.get('category'),
            "merchant": parsed.get('merchant',''),
            "date": parsed.get('date', datetime.date.today().isoformat()),
            "note": parsed.get('note',''),
            "source": source,
        }
        rowid = expense.store_expense(rec)
        return {"ok": True, "message": expense.format_expense_confirmation(rec), "rowid": rowid}
    except Exception:
        return {"ok": False, "message": "處理失敗。"}
