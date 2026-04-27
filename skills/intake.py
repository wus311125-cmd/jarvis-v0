import os
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Any, Dict
from pathlib import Path
import classify
import asyncio
import base64
import requests
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

VAULT = Path(os.environ.get("OBSIDIAN_VAULT", "~/ObsidianVault.main")).expanduser()
DB_PATH = Path(os.environ.get("JARVIS_DB", "~/jarvis-v0/jarvis.db")).expanduser()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

INTAKE_SCHEMA = """
CREATE TABLE IF NOT EXISTS intake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    raw_input TEXT,
    extracted_json TEXT NOT NULL,
    source TEXT DEFAULT 'telegram',
    synced_notion INTEGER DEFAULT 0
);
"""


def init_db(path: Path = DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(INTAKE_SCHEMA)
    conn.commit()
    conn.close()


def store_intake(record: Dict[str, Any], db_path: Path = DB_PATH) -> int:
    """Store intake record into SQLite. record keys: timestamp, type, raw_input, extracted_json, source"""
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO intake (timestamp, type, raw_input, extracted_json, source, synced_notion) VALUES (?, ?, ?, ?, ?, 0)",
        (record.get("timestamp"), record.get("type"), record.get("raw_input"), json.dumps(record.get("extracted_json", {}), ensure_ascii=False), record.get("source", "telegram")),
    )
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    # append to Obsidian daily note
    append_to_daily_intake(record)
    return rowid


def append_to_daily_intake(record: Dict[str, Any]):
    today = datetime.date.today().isoformat()
    path = VAULT / "05-Daily" / f"{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = record.get("timestamp") or datetime.datetime.now().isoformat()
    entry = f"\n- [{ts}] {record.get('type')} — {json.dumps(record.get('extracted_json'), ensure_ascii=False)}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def _call_openrouter_model(image_bytes: bytes, model: str, timeout: int = 10) -> Dict[str, Any]:
    """Call OpenRouter completion with image as base64 + system/user prompt. Return parsed JSON or raise."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    url = "https://api.openrouter.ai/v1/chat/completions"
    b64 = base64.b64encode(image_bytes).decode('ascii')
    prompt = (
        "You are a vision extraction assistant. Input: base64 image string. "
        "Return a JSON object only with keys: type (receipt|screenshot|photo), extracted_json (object). "
        "For receipt: extracted_json should contain merchant, amount, date. "
        "For screenshot: title, summary. For photo: description. "
        "Date format YYYY-MM-DD. Currency HKD by default. Respond with JSON only."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": b64}
        ],
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # openrouter returns choices -> message -> content
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    # ensure we parse JSON
    parsed = json.loads(content)
    return parsed


def classify_and_extract(image_bytes: bytes) -> Dict[str, Any]:
    """Call OpenRouter / vision model to classify and extract fields.
    Returns dict with keys: type (receipt|screenshot|photo), extracted_json
    Uses primary model google/gemini-flash-1.5 with fallback openai/gpt-4o-mini.
    """
    primary = "google/gemini-flash-1.5"
    fallback = "openai/gpt-4o-mini"
    try:
        parsed = _call_openrouter_model(image_bytes, primary, timeout=10)
        return parsed
    except Exception:
        try:
            parsed = _call_openrouter_model(image_bytes, fallback, timeout=10)
            return parsed
        except Exception as e:
            # Network or API error: fall back to a safe local heuristic to allow offline dev/tests
            # Return a minimal, spec-compliant structure so downstream code can proceed.
            # offline fallback: attempt local classify via registry
            extracted = {"description": "(offline fallback) 無法呼叫 OpenRouter"}
            # use classify.get_type for offline heuristics
            t = classify.get_type(extracted)
            return {
                "type": t,
                "extracted_json": extracted
            }


def format_confirmation(record: Dict[str, Any]) -> str:
    """Format Telegram reply in Cantonese per SPEC."""
    t = record.get("type")
    if t == "receipt":
        d = record.get("extracted_json", {})
        return f"已收到收據：商戶 {d.get('merchant','?')}，金額 {d.get('amount','?')}，日期 {d.get('date','?')}。已儲存。"
    elif t == "screenshot":
        d = record.get("extracted_json", {})
        return f"已收到截圖：主題 {d.get('title','?')}。摘要：{d.get('summary','?')}。已儲存。"
    else:
        d = record.get("extracted_json", {})
        return f"已收到相片：{d.get('description','?')}。已儲存。"


async def process_text(text: str, source: str = 'telegram') -> dict:
    """End-to-end processing for text input.
    - call classify.classify(text)
    - if expense -> call llm_extract_expense -> store via expense.store_expense
    - return {ok: bool, message: str, rowid: int|None}
    """
    logger.info("process_text: received text: %s", text)
    # always write intake row first
    try:
        intake_rec = {
            "timestamp": datetime.datetime.now().isoformat(),
            "type": "unknown",
            "raw_input": text,
            "extracted_json": {},
            "source": source,
        }
        # write intake row synchronously (small op)
        _id = store_intake(intake_rec)
        logger.info("intake row saved id=%s", _id)
    except Exception:
        logger.exception("failed to write intake row")
    # classify (async)
    try:
        cls_res = await classify.classify(text)
    except Exception as e:
        logger.exception("classify failed")
        return {"ok": False, "message": f"分類失敗：{e}", "rowid": None}

    logger.info("classification result: %s (conf=%s)", getattr(cls_res, 'type', None), getattr(cls_res, 'confidence', None))

    if cls_res.type in ('expense_text', 'expense'):
        # extract expense fields
        try:
            parsed = await classify.llm_extract_expense(text)
            logger.info("llm_extract_expense -> %s", parsed)
        except Exception:
            logger.exception("llm_extract_expense failed, falling back to regex parse")
            # fallback to local parser in expense module
            from importlib import import_module
            expense_mod = import_module('skills.expense')
            try:
                parsed = expense_mod.parse_expense_text(text)
            except Exception as e:
                logger.exception("local parse_expense_text failed")
                return {"ok": False, "message": "解析費用失敗，請用格式：<金額> [貨幣] [分類] [商戶]", "rowid": None}

        # build record
        rec = {
            "timestamp": datetime.datetime.now().isoformat(),
            "amount": parsed.get('amount'),
            "currency": parsed.get('currency', 'HKD'),
            "category": parsed.get('category'),
            "merchant": parsed.get('merchant'),
            "date": parsed.get('date'),
            "note": parsed.get('description') or parsed.get('note',''),
            "source": source,
        }

        # store via expense.store_expense in thread
        try:
            from importlib import import_module
            expense_mod = import_module('skills.expense')
            rowid = await asyncio.to_thread(expense_mod.store_expense, rec)
            logger.info("expense stored rowid=%s", rowid)
            reply = expense_mod.format_expense_confirmation(rec)
            # update intake row type/extracted_json to reflect expense
            try:
                # mark intake with type expense and extracted
                intake_rec['type'] = 'expense'
                intake_rec['extracted_json'] = parsed
                # best-effort: update last intake row (id available as _id)
                conn = sqlite3.connect(str(DB_PATH))
                c = conn.cursor()
                c.execute("UPDATE intake SET type=?, extracted_json=? WHERE id=?", (intake_rec['type'], json.dumps(intake_rec['extracted_json'], ensure_ascii=False), _id))
                conn.commit()
                conn.close()
            except Exception:
                logger.exception("failed to update intake after expense store")
            return {"ok": True, "message": reply, "rowid": rowid}
        except Exception as e:
            logger.exception("store_expense failed")
            return {"ok": False, "message": f"儲存費用時出錯：{e}", "rowid": None}

    # not expense
    logger.info("text not classified as expense: %s", cls_res.type)
    return {"ok": False, "message": "唔係費用類別（expense）。我只會處理費用記錄。", "rowid": None}
