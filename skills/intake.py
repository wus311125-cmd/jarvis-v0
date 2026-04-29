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
CONFIDENCE_THRESHOLD = 0.7

INTAKE_SCHEMA = """
CREATE TABLE IF NOT EXISTS intake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    raw_input TEXT,
    extracted_json TEXT NOT NULL,
    source TEXT DEFAULT 'telegram',
    synced_notion INTEGER DEFAULT 0,
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
    """Store intake record into SQLite. record keys: timestamp, type, raw_input, extracted_json, source"""
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO intake (timestamp, type, raw_input, extracted_json, source, synced_notion, needs_confirmation) VALUES (?, ?, ?, ?, ?, 0, ?)",
        (
            record.get("timestamp"),
            record.get("type"),
            record.get("raw_input"),
            json.dumps(record.get("extracted_json", {}), ensure_ascii=False),
            record.get("source", "telegram"),
            int(record.get("needs_confirmation", 0)),
        ),
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


def _call_openrouter_model(image_bytes: bytes, model: str, timeout: int = 30, caption: str = "") -> Dict[str, Any]:
    """Call OpenRouter completion with image as base64 + system/user prompt. Return parsed JSON or raise."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    url = "https://openrouter.ai/api/v1/chat/completions"
    b64 = base64.b64encode(image_bytes).decode('ascii')
    prompt = (
        "你係一個圖片分類助手。分析呢張圖片，回覆一個 JSON object。\n\n"
        "只有 3 個 type：receipt、screenshot、photo。\n\n"
        "JSON schema（嚴格跟）：\n"
        "{\n"
        "  \"type\": \"receipt\" | \"screenshot\" | \"photo\",\n"
        "  \"confidence\": 0.0 到 1.0,\n"
        "  \"extracted\": {\n"
        "    \"merchant\": \"商戶名（如有）\",\n"
        "    \"amount\": 數字（float，唔好加 $ 符號），\n"
        "    \"currency\": \"HKD\" | \"USD\" | \"CNY\"（預設 HKD），\n"
        "    \"date\": \"YYYY-MM-DD\"（如有）\n"
        "  },\n"
        "  \"summary\": \"繁體中文一句描述\"\n"
        "}\n\n"
        "規則：\n"
        "- receipt：有金額/價錢嘅單據、發票、收據。必填 merchant + amount + currency + date。\n"
        "- screenshot：手機或電腦截圖。必填 summary。extracted 可以留空值。\n"
        "- photo：普通相片。必填 summary。extracted 可以留空值。\n"
        "- 如果睇唔清楚金額或商戶，填空字串 \"\"，唔好亂估。confidence 反映你幾肯定。\n"
        "- amount 一定係正數 float（例如 45.0），唔好加貨幣符號，唔好用負數。\n"
        "- 只回覆 JSON，唔好加任何其他文字。\n\n"
        "Few-shot examples：\n\n"
        "Example 1（receipt）：\n"
        "{\"type\": \"receipt\", \"confidence\": 0.9, \"extracted\": {\"merchant\": \"大快活\", \"amount\": 45.0, \"currency\": \"HKD\", \"date\": \"2026-04-27\"}, \"summary\": \"大快活午餐收據 $45\"}\n\n"
        "Example 2（screenshot）：\n"
        "{\"type\": \"screenshot\", \"confidence\": 0.85, \"extracted\": {\"merchant\": \"\", \"amount\": 0, \"currency\": \"HKD\", \"date\": \"\"}, \"summary\": \"WhatsApp 對話截圖，討論禮拜三上堂時間\"}\n\n"
        "Example 3（photo）：\n"
        "{\"type\": \"photo\", \"confidence\": 0.95, \"extracted\": {\"merchant\": \"\", \"amount\": 0, \"currency\": \"HKD\", \"date\": \"\"}, \"summary\": \"街頭夜景，有霓虹燈招牌\"}\n"
    )
    user_content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]
    if caption:
        user_content.append({"type": "text", "text": f"Caption: {caption}"})
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content}
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # openrouter returns choices -> message -> content
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    # Log raw model response for debugging (helps capture malformed outputs)
    try:
        logger.info("RAW OPENROUTER JSON RESPONSE: %s", content)
    except Exception:
        pass
    # try parse JSON, fallback will be handled by caller
    try:
        parsed = json.loads(content)
        return parsed
    except Exception:
        raise


def classify_and_extract(image_bytes: bytes, caption: str = "") -> Dict[str, Any]:
    """Call OpenRouter / vision model to classify and extract fields.
    Returns dict with keys: type (receipt|screenshot|photo), extracted_json
    Uses primary model meta-llama/llama-4-scout with fallback meta-llama/llama-4-scout.
    """
    primary = "meta-llama/llama-4-scout"
    fallback = "meta-llama/llama-4-scout"
    # try primary then fallback; if parsing fails, return graceful photo fallback
    from skills.normalize import normalize_extracted
    # confidence threshold config
    CONFIDENCE_THRESHOLD = 0.7

    for model in (primary, fallback):
        try:
            parsed = _call_openrouter_model(image_bytes, model, timeout=30, caption=caption)
            # Normalize model output: accept either 'extracted' (new) or 'extracted_json' (old)
            if not isinstance(parsed, dict):
                continue
            parsed_type = parsed.get('type')
            extracted = parsed.get('extracted') if parsed.get('extracted') is not None else parsed.get('extracted_json')
            # ensure extracted is a dict
            if not isinstance(extracted, dict):
                extracted = {}

            # Accept only the three canonical types
            if parsed_type in ('receipt', 'screenshot', 'photo'):
                out = {
                    'type': parsed_type,
                    'extracted_json': extracted,
                    'confidence': float(parsed.get('confidence', 0.0))
                }
                # normalize before return
                try:
                    out = normalize_extracted(out)
                except Exception:
                    pass
                return out
        except Exception:
            # try next model
            continue

    # If we reach here, both attempts failed or returned unparsable content
    import traceback; traceback.print_exc()
    logger.warning('vision API failed or returned invalid JSON; falling back to unknown — error: %s')
    return {
        "type": "unknown",
        "extracted_json": {},
        "confidence": 0.0
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
    # If caller passed a dict-like RECAP object, accept it (internal integration path)
    if isinstance(text, dict):
        # normalize to use rewritten_text for downstream processing
        try:
            distilled = text.get('distilled_fields')
            text = text.get('rewritten_text', '') or ''
        except Exception:
            text = text
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
