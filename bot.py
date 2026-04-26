import os, asyncio, subprocess, datetime, re
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes,
)

load_dotenv()

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

    # match text to type via registry patterns
    t = classify.match_text_to_type(text)
    if not t:
        # friendly fallback
        await update.message.reply_text("唔好意思，我暫時未識處理呢類訊息。試下傳相或用 'expense 12.5 lunch' 格式。")
        return

    # find registry entry
    reg = classify.load_registry()
    entry = next((x for x in reg.get('types', []) if x.get('id') == t), None)
    if not entry:
        await update.message.reply_text("Internal: registry mismatch。")
        return

    handler = entry.get('handler')
    # dispatch to handler module
    if handler == 'expense':
        # treat as expense_text
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
            "source": 'text',
        }
        rowid = await asyncio.to_thread(expense.store_expense, rec)
        await update.message.reply_text(expense.format_expense_confirmation(rec))
        return

    if handler == 'intake':
        # create a manual intake record from text summary
        rec = {
            "timestamp": datetime.datetime.now().isoformat(),
            "type": entry.get('id') if entry.get('id') in ('receipt','screenshot','photo') else 'photo',
            "raw_input": text,
            "extracted_json": {"summary": text},
            "source": 'manual',
        }
        rowid = await asyncio.to_thread(intake.store_intake, rec)
        await update.message.reply_text(intake.format_confirmation(rec))
        return

    # other handlers not implemented yet
    await update.message.reply_text("這種類型已設定但 handler 未實作。")


async def on_photo(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    # show typing ASAP (AC-1 requirement: start processing within 3s)
    await update.message.reply_chat_action("typing")
    # download highest-res photo
    photo = update.message.photo[-1]
    bio = await photo.get_file()
    img_bytes = await bio.download_as_bytearray()
    # classify and extract
    record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "source": "telegram",
        "raw_input": "<binary omitted>",
    }
    parsed = await asyncio.to_thread(intake.classify_and_extract, bytes(img_bytes))
    # After extraction, run async classify for type validation (LLM fallback possible)
    try:
        # call classify.classify (async) with extracted summary if available
        summary = parsed.get('extracted_json', {}).get('summary') or parsed.get('extracted_json', {}).get('description') or ''
        if summary:
            cls_res = await classify.classify(summary)
            if cls_res and cls_res.type != 'unknown':
                parsed['type'] = cls_res.type
    except Exception:
        # be conservative: ignore LLM errors and continue with parsed result
        pass
    record.update(parsed)
    rowid = await asyncio.to_thread(intake.store_intake, record)
    reply = intake.format_confirmation(record)
    await update.message.reply_text(reply)


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
