import os
import sqlite3
import datetime
import json
from pathlib import Path
from typing import Dict, Any

VAULT = Path(os.environ.get("OBSIDIAN_VAULT", "~/ObsidianVault.main")).expanduser()
DB_PATH = Path(os.environ.get("JARVIS_DB", "~/jarvis-v0/jarvis.db")).expanduser()

EXPENSE_SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'HKD',
    category TEXT,
    merchant TEXT,
    date TEXT,
    note TEXT,
    source TEXT DEFAULT 'telegram',
    synced_notion INTEGER DEFAULT 0
);
"""


def init_db(path: Path = DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(EXPENSE_SCHEMA)
    conn.commit()
    conn.close()


def store_expense(record: Dict[str, Any], db_path: Path = DB_PATH) -> int:
    """Store expense into SQLite. record keys: timestamp, amount, currency, category, merchant, date, note, source"""
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO expenses (timestamp, amount, currency, category, merchant, date, note, source, synced_notion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (
            record.get("timestamp"),
            record.get("amount"),
            record.get("currency", "HKD"),
            record.get("category"),
            record.get("merchant"),
            record.get("date"),
            record.get("note"),
            record.get("source", "telegram"),
        ),
    )
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    append_to_daily_expense(record)
    return rowid


def append_to_daily_expense(record: Dict[str, Any]):
    today = datetime.date.today().isoformat()
    path = VAULT / "05-Daily" / f"{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = record.get("timestamp") or datetime.datetime.now().isoformat()
    entry = f"\n- [{ts}] expense {record.get('amount')} {record.get('currency','HKD')} {record.get('category','')} {record.get('merchant','')} — {record.get('note','')}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def parse_expense_text(text: str) -> Dict[str, Any]:
    """Very small parser: expected format: <amount> [currency] [category] [merchant] [date YYYY-MM-DD] [note...]
    Examples:
      12.5 HKD lunch McCafe 2026-04-27 "iced latte"
      9.5 lunch
    Returns dict with amount (float) and other optional fields.
    """
    parts = text.strip().split()
    out: Dict[str, Any] = {}
    try:
        out['amount'] = float(parts[0])
    except Exception:
        raise ValueError('invalid amount')
    idx = 1
    # optional currency if all-caps length 3
    if idx < len(parts) and parts[idx].isalpha() and len(parts[idx]) <= 4 and parts[idx].isupper():
        out['currency'] = parts[idx]
        idx += 1
    # next is category
    if idx < len(parts):
        out['category'] = parts[idx]
        idx += 1
    # merchant if looks like alphanumeric and not date
    if idx < len(parts) and not parts[idx].count('-') == 2:
        out['merchant'] = parts[idx]
        idx += 1
    # date if matches YYYY-MM-DD
    if idx < len(parts) and len(parts[idx]) == 10 and parts[idx][4] == '-' and parts[idx][7] == '-':
        out['date'] = parts[idx]
        idx += 1
    # rest as note
    if idx < len(parts):
        out['note'] = ' '.join(parts[idx:])
    return out


def format_expense_confirmation(record: Dict[str, Any]) -> str:
    return f"已記低：{record.get('amount')} {record.get('currency','HKD')} · {record.get('category','')} · {record.get('merchant','')} · {record.get('date','')}"
