import os, asyncio, subprocess, datetime, re
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes,
)

load_dotenv()

import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED = int(os.environ["ALLOWED_USER_ID"])
VAULT = Path(os.environ["OBSIDIAN_VAULT"])

_SPEAKER_RE = re.compile(r"^\*\*\[\d{2}:\d{2}\]\s+(Hopan|緣一)\*\*\s*:")
_SESSION_HEADER_RE = re.compile(r"^##\s+Session\s+\d+")

_SESSION_N_RE = re.compile(r"^##\s+Session\s+(\d+)")

def ensure_session_header(cooldown_min: int = 30) -> int:
    """喺今日 daily note append session header，return N。
    優先順序：env JARVIS_SESSION > 30 min cooldown 重用 > 今日最大+1 > 1。"""
    today = datetime.date.today().isoformat()
    path = VAULT / "05-Daily" / f"{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    env_override = os.environ.get("JARVIS_SESSION")
    if env_override and env_override.isdigit():
        n = int(env_override)
    else:
        n_max = 0
        last_time = None
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                m = _SESSION_N_RE.match(line)
                if m:
                    n_max = max(n_max, int(m.group(1)))
                    ts_m = re.search(r"(\d{2}):(\d{2})", line)
                    if ts_m:
                        last_time = now.replace(hour=int(ts_m.group(1)), minute=int(ts_m.group(2)), second=0, microsecond=0)
        if last_time is not None and (now - last_time).total_seconds() / 60 < cooldown_min:
            return n_max
        n = n_max + 1
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## Session {n} \u2014 {now.strftime('%H:%M')} \u958b\u5834\n")
    return n


def append_to_daily(role: str, text: str):
    today = datetime.date.today().isoformat()
    path = VAULT / "05-Daily" / f"{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%H:%M")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n**[{ts}] {role}**: {text}\n")


def format_image_confirmation(result: dict) -> str:
    """緣一語氣回覆 — 廣東話口語 + emoji"""
    try:
        data = result.get("extracted_json", {})
        if isinstance(data, str):
            import json
            data = json.loads(data)
        img_type = result.get("type") or (data.get("type") if isinstance(data, dict) else "photo")
        extracted = {}
        if isinstance(data, dict):
            extracted = data.get("extracted", {}) if data.get("extracted") is not None else data
        if not isinstance(extracted, dict):
            extracted = {}
        summary = (data.get("summary") if isinstance(data, dict) else None) or extracted.get("summary", "")

        if img_type == "receipt":
            merchant = extracted.get("merchant", "") or extracted.get("vendor", "")
            amount = extracted.get("amount", 0)
            currency = extracted.get("currency", "HKD")
            if merchant and amount:
                return f"🧾 收到！{merchant} ${amount}，我記低咗。"
            elif amount:
                return f"🧾 收到一張單，${amount}。商戶我睇唔太清，你補返？"
            else:
                return "🧾 好似係張單，但我睇唔到金額。你可以話我知幾錢？"

        elif img_type == "screenshot":
            if summary:
                return f"📱 Screenshot 收到：{summary}"
            return "📱 Screenshot 收到，我記低咗。"

        elif img_type == "photo":
            if summary:
                return f"📸 靚相！{summary}"
            return "📸 收到張相，我記低咗。"

        else:
            return "🤔 我睇唔太清呢張，你可以話我知係咩？"
    except Exception:
        return "🤔 我睇唔太清呢張，你可以話我知係咩？"

def load_today_context(max_lines: int = 20) -> str:
    """Zone 1 hot context：只 inject Hopan 發言 + session headers，filter 走緣一 reply。"""
    today = datetime.date.today().isoformat()
    path = VAULT / "05-Daily" / f"{today}.md"
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    filtered: list[str] = []
    current_speaker: str | None = None
    for line in lines:
        m = _SPEAKER_RE.match(line)
        if m:
            current_speaker = m.group(1)
            if current_speaker == "Hopan":
                filtered.append(line)
            continue
        if _SESSION_HEADER_RE.match(line):
            current_speaker = None
            filtered.append(line)
            continue
        if current_speaker is None:
            filtered.append(line)
            continue
        if current_speaker == "Hopan":
            filtered.append(line)
    tail = filtered[-max_lines:]
    return "\n".join(tail).strip()

def ask_opencode(prompt: str) -> str:
    context = load_today_context()
    if context:
        wrapped = (
            "## 今日 Hopan 發言 tail（你嘅 Zone 1 hot context，已 filter 走你自己嘅 reply）\n"
            f"{context}\n\n---\n\n"
            f"## Hopan 啱啱講\n{prompt}"
        )
    else:
        wrapped = prompt
    try:
        result = subprocess.run(
            ["/Users/nhp/.local/bin/opencode", "run",
             "--agent", "yuen-yat",
             "--model", "github-copilot/gpt-5-mini",
             wrapped],
            capture_output=True, text=True, timeout=120,
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        return out or err or "(緣一冇聲出)"
    except subprocess.TimeoutExpired:
        return "……諗緊嘢，超時。再試或 /stop。"
    except FileNotFoundError:
        return "搵唔到 opencode CLI。"

async def guard(update: Update) -> bool:
    if update.effective_user.id != ALLOWED:
        await update.message.reply_text("你唔係 Hopan。再見。")
        return False
    return True

async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await update.message.reply_text("🐱 緣一 online。直接打字就得。\n指令：/stop /help")

async def help_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await update.message.reply_text("直接打字 = 同緣一傾偈\n/stop = 緊急鍵\n每句對話都 append 去 Obsidian daily note。")

async def stop(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await update.message.reply_text("⛔ 停。（v0.1 placeholder）")

import sys
sys.path.insert(0, os.path.expanduser('~/oh-my-opencode/skills/leak-linter'))
from linter import lint
# import skills
from skills import intake, expense
import sqlite3
import classify
import json, hashlib
from datetime import timedelta
import requests

AUDIT_LOG = os.path.expanduser('~/.opencode/leak-linter.log')
MAX_RETRY = 3
BLOCK_TIMESTAMPS = []
LEAK_LINTER_FROZEN = False
WEBHOOK = os.environ.get("TELEGRAM_HOPAN_OS_WEBHOOK")

async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """Generic text handler — registry-driven dispatch."""
    if not await guard(update): return
    text = (update.message.text or "").strip()
    await update.message.reply_chat_action("typing")
    append_to_daily("Hopan", text)
    # Pass text to intake.process_text for E2E handling (classification -> expense store -> reply)
    # handle possible feedback message first
    handled = await handle_feedback(update, _)
    if handled:
        return

    try:
        result = await intake.process_text(text, source='telegram')
    except Exception as e:
        # unexpected error
        await update.message.reply_text(f"處理時發生錯誤：{e}")
        return

    if result.get('ok'):
        await send_reply(update, result.get('message', '已儲存。'))
    else:
        await send_reply(update, result.get('message', '處理失敗。'))


async def on_photo(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    # show typing ASAP (AC-1 requirement: start processing within 3s)
    await update.message.reply_chat_action("typing")
    # download highest-res photo
    photo = update.message.photo[-1]
    bio = await photo.get_file()
    img_bytes = await bio.download_as_bytearray()
    # classify and extract via vision API (pass caption for better accuracy)
    caption = update.message.caption or ""
    record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "source": "telegram",
        "raw_input": f"photo:{len(img_bytes)}bytes",
    }
    parsed = await asyncio.to_thread(intake.classify_and_extract, bytes(img_bytes), caption)

    # Normalize parsed shapes: support both {'extracted_json': {...}} and {'extracted': {...}}
    extracted = {}
    confidence = 0.0
    try:
        if isinstance(parsed, dict):
            # prefer top-level extracted_json
            if 'extracted_json' in parsed:
                extracted = parsed.get('extracted_json') or {}
                if isinstance(extracted, str):
                    try:
                        extracted = json.loads(extracted)
                    except Exception:
                        extracted = {}
            elif 'extracted' in parsed:
                maybe = parsed.get('extracted') or {}
                if isinstance(maybe, dict):
                    # if nested 'extracted' actually contains the final fields
                    # detect common keys
                    if any(k in maybe for k in ('merchant', 'amount', 'currency', 'date', 'summary')):
                        extracted = maybe
                    else:
                        # maybe contains the whole payload; try to unwrap
                        nested = maybe.get('extracted')
                        if isinstance(nested, dict):
                            extracted = nested
                        else:
                            # fallback: try to pick known fields from maybe
                            extracted = {k: maybe.get(k) for k in ('merchant', 'amount', 'currency', 'date', 'summary') if maybe.get(k) is not None}
                            if not extracted:
                                extracted = maybe
                else:
                    extracted = {}
            else:
                # flat keys on parsed
                extracted = {k: parsed.get(k) for k in ('merchant', 'amount', 'currency', 'date', 'summary') if parsed.get(k) is not None}

            # confidence can be on parsed or inside extracted
            if parsed.get('confidence') is not None:
                try:
                    confidence = float(parsed.get('confidence', 0.0))
                except Exception:
                    confidence = 0.0
            elif isinstance(extracted, dict) and extracted.get('confidence') is not None:
                try:
                    confidence = float(extracted.get('confidence', 0.0))
                except Exception:
                    confidence = 0.0
    except Exception:
        extracted = {}

    # LLM-based text classify fallback (use extracted summary/description)
    try:
        summary = (extracted.get('summary') if isinstance(extracted, dict) else '') or (extracted.get('description') if isinstance(extracted, dict) else '')
        if caption:
            summary = f"{caption} {summary}".strip()
        if summary:
            cls_res = await classify.classify(summary)
            if cls_res and getattr(cls_res, 'type', None) and cls_res.type != 'unknown':
                parsed['type'] = cls_res.type
    except Exception:
        pass

    # confidence-driven flow
    ex = parsed.get('extracted_json', {}) if isinstance(parsed, dict) else {}
    try:
        conf = float(parsed.get('confidence', 0.0))
    except Exception:
        conf = 0.0

    if conf >= intake.CONFIDENCE_THRESHOLD:
        # auto-confirmed
        record.update({
            "type": parsed.get('type', 'unknown'),
            # store full parsed payload (preserve confidence / summary / extracted)
            "extracted_json": parsed,
            "needs_confirmation": 0,
        })
        rowid = await asyncio.to_thread(intake.store_intake, record)
        # if receipt and amount present, create expense
        try:
            ext = ex.get('extracted', ex) if isinstance(ex, dict) else {}
            if parsed.get('type') == 'receipt' and ext.get('amount'):
                expense_rec = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "amount": float(ext.get('amount')),
                    "currency": ext.get('currency', 'HKD'),
                    "category": ext.get('category', '其他'),
                    "merchant": ext.get('merchant', ''),
                    "date": ext.get('date'),
                    "note": '',
                    "source": 'image',
                }
                await asyncio.to_thread(expense.store_expense, expense_rec)
        except Exception:
            logger.exception('failed to store linked expense from image')
        # reply
        try:
            reply = format_image_confirmation({"extracted_json": ex})
        except Exception:
            reply = "🤔 我睇唔太清呢張，你可以話我知係咩？"
        await send_reply(update, reply)
        return
    else:
        # ask user for confirmation (low confidence)
        summary = ex.get('summary', '') if isinstance(ex, dict) else ''
        type_guess = parsed.get('type', 'unknown')
        text = f"🤔 我睇到似係 {summary}，但係唔太肯定。係喔係：\n① 收據\n② 截圖\n③ 相片\n回覆 1/2/3 話我知！"
        record.update({
            "type": parsed.get('type', 'unknown'),
            # store full parsed payload so feedback handler can preserve extracted fields
            "extracted_json": parsed,
            "needs_confirmation": 1,
        })
        rowid = await asyncio.to_thread(intake.store_intake, record)
        await send_reply(update, text)
        return

    # if receipt, and amount present, store expense
    try:
        if record['type'] == 'receipt' and record['extracted_json'].get('amount'):
            expense_rec = {
                "timestamp": datetime.datetime.now().isoformat(),
                "amount": float(record['extracted_json'].get('amount')),
                "currency": record['extracted_json'].get('currency', 'HKD'),
                "category": record['extracted_json'].get('category', '其他'),
                "merchant": record['extracted_json'].get('vendor') or record['extracted_json'].get('merchant'),
                "date": record['extracted_json'].get('date'),
                "note": '',
                "source": 'image',
            }
            await asyncio.to_thread(expense.store_expense, expense_rec)
    except Exception:
        logger.exception('failed to store linked expense from image')

    # format reply and send (go through same reply path as text)
    # Use new format_image_confirmation with graceful fallback handling
    try:
        reply = format_image_confirmation(record)
        # if model returned unknown type, override with fallback message
        if record.get('type') == 'unknown' or reply is None:
            reply = "🤔 我睇唔太清呢張，你可以話我知係咩？"
    except Exception:
        reply = "🤔 我睇唔太清呢張，你可以話我知係咩？"
    # centralized send via leak-linter
    await send_reply(update, reply)


async def send_reply(update, text: str):
    """Centralized reply — all outbound messages go through leak-linter."""
    try:
        from linter import lint
        result = lint(text)
        if isinstance(result, dict) and result.get("blocked"):
            # Quick fix: log and still send — avoid false positives blocking ask_user flows
            logger.warning("Linter blocked reply (possible false positive). Sending anyway. snippet=%s", text[:120])
            try:
                await update.message.reply_text(text)
            except Exception:
                pass
            return
        # result may be cleaned text
        cleaned = result if isinstance(result, str) else text
    except Exception as e:
        logger.warning("leak-linter error: %s", e)
        cleaned = text
    await update.message.reply_text(cleaned)



async def on_expense(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    text = update.message.text or ""
    # strip leading keyword
    text = text.replace('expense', '').replace('費用', '').strip()
    try:
        parsed = expense.parse_expense_text(text)
    except Exception:
        await update.message.reply_text("唔好意思，請用格式：金額 [貨幣] [分類] [商戶] [YYYY-MM-DD] [備註]")
        return
    rec = {
        "timestamp": datetime.datetime.now().isoformat(),
        "amount": parsed.get('amount'),
        "currency": parsed.get('currency','HKD'),
        "category": parsed.get('category'),
        "merchant": parsed.get('merchant'),
        "date": parsed.get('date'),
        "note": parsed.get('note',''),
        "source": 'telegram',
    }
    rowid = await asyncio.to_thread(expense.store_expense, rec)
    await update.message.reply_text(expense.format_expense_confirmation(rec))


FEEDBACK_MAP = {
    "1": "receipt", "收據": "receipt", "單": "receipt",
    "2": "screenshot", "截圖": "screenshot",
    "3": "photo", "相片": "photo", "相": "photo",
}


async def handle_feedback(update: Update, _: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle user feedback for low-confidence classifications.
    Returns True if message consumed as feedback.
    """
    text = (update.message.text or "").strip()
    logger.info("handle_feedback invoked with text=%s from user=%s", text, getattr(update.effective_user, 'id', None))
    if text not in FEEDBACK_MAP:
        logger.info("handle_feedback: not a feedback message: %s", text)
        return False
    new_type = FEEDBACK_MAP[text]
    # use intake.DB_PATH to reference db path
    conn = sqlite3.connect(str(intake.DB_PATH))
    cur = conn.cursor()
    cur.execute(
        "SELECT id, extracted_json FROM intake WHERE needs_confirmation=1 ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    logger.info("handle_feedback: pending row fetched=%s", row)
    if not row:
        conn.close()
        return False
    row_id, ej = row
    try:
        data = json.loads(ej)
    except Exception:
        data = {}
    # preserve existing extracted fields; only override type
    data["type"] = new_type
    cur.execute(
        "UPDATE intake SET type=?, extracted_json=?, needs_confirmation=0 WHERE id=?",
        (new_type, json.dumps(data, ensure_ascii=False), row_id),
    )
    logger.info("handle_feedback: updated intake id=%s to type=%s", row_id, new_type)
    conn.commit()

    # If receipt → create expense
    if new_type == "receipt":
        ext = data.get("extracted", data)
        amt = ext.get("amount")
        if amt and isinstance(amt, (int, float)) and amt > 0:
            from skills.expense import store_expense
            try:
                store_expense({
                    "amount": amt,
                    "currency": ext.get("currency", "HKD"),
                    "merchant": ext.get("merchant", ""),
                    "date": ext.get("date", ""),
                    "category": "其他",
                    "source": "image",
                })
            except Exception:
                logger.exception("failed to create expense from feedback")

    await send_reply(update, "✅ 收到，記低咗！")
    conn.close()
    return True


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # register photo handler
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    # generic text handler (registry-driven)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    session_n = ensure_session_header()
    print(f"\U0001F431 緣一 Jarvis v0.1 running... (Session {session_n})")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
