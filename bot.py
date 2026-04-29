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
from collections import deque
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# simple in-memory dedupe for incoming message ids to avoid duplicate processing
_PROCESSED_MSG_IDS = deque(maxlen=200)


def rewrite_intent(text: str, entity_context: str = '', recent=None) -> str:
    """Safe no-op rewrite_intent fallback.

    Keep minimal so upstream routing can call safely when richer rewrite isn't available.
    """
    try:
        return text
    except Exception:
        logger.exception('rewrite_intent fallback error')
        return text

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


async def _log_meta_router_decision_async(update, last_route_decision):
    """Best-effort: call meta_router.should_distill for the user's conversation and log the decision.
    This is non-blocking and intended to be called after successful tool executions only.
    """
    try:
        from meta_router import should_distill, log_distill_decision
        try:
            from memory import memory as conv_memory
            user_id = str(update.effective_user.id)
            conv_msgs = conv_memory.get_messages(user_id)
        except Exception:
            conv_msgs = []
        decision = should_distill(conv_msgs, last_route_decision=last_route_decision)
        # log length and decision
        log_distill_decision(decision, len(conv_msgs))
    except Exception:
        logger.exception('[META_ROUTER] failed to log distill decision')


def format_image_confirmation(result: dict) -> str:
    """緣一語氣回覆 — 廣東話口語 + emoji"""
    try:
        logger.info("DEBUG format_image_confirmation: input=%s", str(result)[:200])
    except Exception:
        pass
    try:
        # Support both new full-context shape and legacy extracted_json shape
        img_type = result.get("type") or (result.get("extracted_json") or {}).get("type") or "unknown"
        # prefer 'extracted' key, fallback to 'extracted_json' or legacy nested structures
        extracted = result.get("extracted")
        if extracted is None:
            extracted = result.get("extracted_json") or {}
            if isinstance(extracted, dict) and "extracted" in extracted:
                # flatten if someone passed {'extracted': {..., 'extracted': {...}}}
                nested = extracted.get('extracted')
                if isinstance(nested, dict):
                    extracted = nested
        if not isinstance(extracted, dict):
            extracted = {}
        summary = result.get("summary") or extracted.get("summary", "")

        if img_type == "receipt":
            merchant = extracted.get("merchant", "")
            amount = extracted.get("amount", 0)
            if merchant and amount:
                return f"🧾 收到！{merchant} ${amount}，我記低咗。"
            elif amount:
                return f"🧾 收到一張單，${amount}。商戶我睇唔太清，你補返？"
            else:
                return "🧾 好似係張單，但我睇唔到金額。你可以話我知幾錢？"

        elif img_type == "screenshot":
            return f"📱 Screenshot 收到：{summary}" if summary else "📱 Screenshot 收到，我記低咗。"

        elif img_type == "photo":
            return f"📸 靚相！{summary}" if summary else "📸 收到張相，我記低咗。"

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
    # dedupe: ignore duplicate update.message.message_id seen recently
    try:
        mid = update.message.message_id
        if mid in _PROCESSED_MSG_IDS:
            logger.info('[ON_TEXT] duplicate message_id %s ignored', mid)
            return
        _PROCESSED_MSG_IDS.append(mid)
    except Exception:
        # if no message id available, continue
        pass
    text = (update.message.text or "").strip()
    # Conversation memory: add user message to per-user buffer
    try:
        from memory import memory
        user_id = str(update.effective_user.id)
        memory.add_user_message(user_id, text)
    except Exception:
        logger.exception('failed to append to memory')
    await update.message.reply_chat_action("typing")
    append_to_daily("Hopan", text)
    # Pass text to intake.process_text for E2E handling (classification -> expense store -> reply)
    # handle possible feedback message first
    handled = await handle_feedback(update, _)
    if handled:
        return

    # New intent routing v0.1 flow: entity_lookup -> rewrite -> classify -> confidence gate -> dispatch
    try:
        from router import route as router_route, _load_recent_history
        from skills.entity_lookup import lookup_entities
    except Exception:
        logger.exception('[ROUTE] failed to import routing helpers')
        # fallback to existing intake pipeline
        try:
            result = await intake.process_text(text, source='telegram')
        except Exception as e:
            await update.message.reply_text(f"處理時發生錯誤：{e}")
            return
        if result.get('ok'):
            await send_reply(update, result.get('message', '已儲存。'))
        else:
            await send_reply(update, result.get('message', '處理失敗。'))
        return

    # 1) entity lookup
    step = 'entity_lookup'
    entities_res = lookup_entities(text)
    logger.info(f"[ROUTE] step=%s, result=%s", step, entities_res)

    # 2) rewrite intent (RECAP) using recent daily context as recent_turns
    step = 'rewrite'
    recent = load_today_context(10).splitlines() if load_today_context() else []
    try:
        # use recap.recap_rewrite if available to get distilled fields
        try:
            from recap import recap_rewrite
            recap_out = recap_rewrite(text, entities_res.get('entity_context',''), recent)
            rewritten = recap_out.get('rewritten_text', text)
            distilled = recap_out.get('distilled_fields')
            logger.info(f"[RECAP] distilled_fields=%s", distilled)
        except Exception:
            # fallback to existing rewrite_intent
            rewritten = rewrite_intent(text, entities_res.get('entity_context',''), recent)
            distilled = None
    except Exception:
        logger.exception('[ROUTE] rewrite_intent / recap_rewrite failed, fallback to original text')
        rewritten = text
        distilled = None
    logger.info(f"[ROUTE] step=%s, result=%s", step, rewritten)

    # Short-circuit heuristics removed — routing delegated to LLM-native router
    # Any deterministic intent routing was intentionally removed to let the
    # model choose tools based on system prompt + entity context + memory.

    # 3) route via function-calling router (OpenRouter)
    step = 'route'
    try:
        recent_ctx = _load_recent_history(10)
        # include conversation memory as history for model context
        try:
            from memory import memory as conv_memory
            user_id = str(update.effective_user.id)
            history_msgs = conv_memory.get_messages(user_id)
        except Exception:
            history_msgs = []
        # pass recap object (rewritten + distilled) so router can see distilled_fields
        recap_obj = {'rewritten_text': rewritten, 'distilled_fields': distilled}
        route_res = router_route(recap_obj, entities_res.get('entity_context',''), recent_ctx, history=history_msgs)
        # route_res is expected to be a route_decision shaped dict from router.route
        # shape: {'action':'route_decision', 'tool':..., 'args':..., 'confidence':...}
        try:
            if isinstance(route_res, dict) and route_res.get('action') == 'route_decision':
                tool = route_res.get('tool')
                args = route_res.get('args') or {}
                conf = route_res.get('confidence')
                # fallback if model didn't provide numeric confidence
                if conf is None:
                    conf = 0.9
                logger.info('[ROUTE] suggested tool=%s conf=%s args=%s', tool, conf, args)
                # Confidence gating (dynamic thresholding via CG-3)
                try:
                    detected_mode = route_res.get('detected_mode') if isinstance(route_res, dict) else None
                    # fallback: detect mode from conversation memory if router didn't provide
                    if not detected_mode:
                        try:
                            from router import detect_mode
                            detected_mode = detect_mode(history_msgs if history_msgs else None, window=5)
                        except Exception:
                            detected_mode = 'mixed'
                    from router import adjust_threshold
                    adjusted_threshold = adjust_threshold(0.8, detected_mode or 'mixed', tool)
                except Exception:
                    adjusted_threshold = 0.8

                if tool and conf >= adjusted_threshold:
                    # execute directly
                    from router import execute_tool
                    if tool == 'learn_from_correction':
                        from learning import learn_from_correction as _lfc
                        res = _lfc(args.get('original_input',''), args.get('correct_tool',''), args.get('lesson',''), args.get('wrong_tool'))
                        await send_reply(update, str(res))
                        return
                    res = await asyncio.to_thread(execute_tool, tool, args)
                    await send_reply(update, str(res))
                    return
                elif tool and conf >= 0.5:
                    # clarify with user
                    from router import generate_clarification
                    msg = generate_clarification(rewritten, tool)
                    # store this clarification as assistant reply so follow-up can reference
                    await send_reply(update, msg)
                    # note: follow-up user reply will re-enter routing with the same recent/history
                    return
                else:
                    # low confidence -> treat as chat
                    from jarvis.chat import chat_reply
                    chatr = chat_reply(text)
                    await send_reply(update, chatr)
                    return
            # else: fallback to legacy behavior if router returned tool_calls or tool field
            # (handled below in original dispatch)
        except Exception:
            logger.exception('[ROUTE] route decision handling failed, falling back to legacy dispatch')
    except Exception:
        logger.exception('[ROUTE] router_route failed, fallback to intake')
        route_res = {'tool': None, 'args': None, 'assistant': None}
    logger.info(f"[ROUTE] step=%s, result=%s", step, route_res)

    # 4) dispatch based on tool calls
    step = 'dispatch'
    try:
        # Fast rule-based short-circuit: explicit -<number> or +<number> prefix
        m = re.match(r'^\s*([+-])(\d+(?:\.\d+)?)\s*(.*)$', text)
        if m:
            sign, amt_s, rest = m.groups()
            amt = float(amt_s)
            if sign == '-':
                # direct expense record
                rc = {
                    'timestamp': datetime.datetime.now().isoformat(),
                    'amount': abs(amt),
                    'currency': 'HKD',
                    'category': rest.split()[0] if rest else None,
                    'merchant': ' '.join(rest.split()[1:]) if len(rest.split())>1 else '',
                    'date': datetime.date.today().isoformat(),
                    'note': '',
                    'source': 'telegram',
                }
                rowid = await asyncio.to_thread(expense.store_expense, rc)
                await send_reply(update, expense.format_expense_confirmation(rc))
                return
            else:
                # income
                # reuse expense.store_expense but negative logic: store as income via intake or similar; fallback to chat reply
                await send_reply(update, f"已記收入：{amt} HKD。")
                return

        if route_res.get('tool'):
            tool = route_res['tool']
            args = route_res.get('args') or {}
            logger.info(f"[ROUTE] tool_call detected: %s %s", tool, args)
            # Post-router sanity guards: LLM may choose wrong tool or miss args.
            # If model chose schedule but didn't provide date, treat as a find_student query instead.
            if tool in ('schedule_next_lesson', 'schedule_next') and not args.get('date'):
                # try locate student name from args or text
                candidate = args.get('student_name') or args.get('name') or args.get('student')
                if not candidate:
                    # try best-effort from message text
                    try:
                        mm = re.match(r'(.+?)(?:上到邊|幾時上堂|上堂進度)', (update.message.text or ''))
                        candidate = mm.group(1).strip() if mm else None
                    except Exception:
                        candidate = None
                if candidate:
                    try:
                        from router import execute_tool
                        res = await asyncio.to_thread(execute_tool, 'find_student', {'name': candidate})
                        if res:
                            # format as student info
                            await send_reply(update, f"我睇到 {candidate}，資料：{res.get('properties',{}).get('上堂日') or res.get('properties',{}).get('開始日期') or '（資料不足）'}")
                            return
                    except Exception:
                        pass
                # fallback: ask user for clarification to avoid wrong schedule
                await send_reply(update, '請提供學生名同日期，例如：「sophia 下禮拜三 4 點」。')
                return
            # map tool names to actions
            if tool in ('record_expense', 'log_expense'):
                rec = {
                    'timestamp': datetime.datetime.now().isoformat(),
                    'amount': float(args.get('amount', 0)),
                    'currency': args.get('currency','HKD'),
                    'category': args.get('category') or None,
                    'merchant': args.get('vendor') or args.get('merchant') or args.get('description',''),
                    'date': datetime.date.today().isoformat(),
                    'note': '',
                    'source': 'telegram',
                }
                rowid = await asyncio.to_thread(expense.store_expense, rec)
                await send_reply(update, expense.format_expense_confirmation(rec))
                # meta-router: log decision after successful tool execution
                await _log_meta_router_decision_async(update, route_res)
                return
            elif tool in ('record_income', 'log_income'):
                # simple acknowledge for income
                await send_reply(update, f"已記收入：{args.get('amount')} {args.get('currency','HKD')} · {args.get('description','')}")
                await _log_meta_router_decision_async(update, route_res)
                return
            elif tool in ('query_student','find_student','list_students','new_student','update_student_progress','log_lesson','schedule_next_lesson','schedule_next'):
                # Centralized student tools dispatch via router.execute_tool
                try:
                    from router import execute_tool
                    # execute_tool is sync; run in thread
                    res = await asyncio.to_thread(execute_tool, tool, args)
                    # handle structured error
                    if isinstance(res, dict) and res.get('error'):
                        await send_reply(update, f"操作失敗: {res.get('error')}")
                        return

                    # format responses per tool
                    if tool in ('query_student','find_student'):
                        if not res:
                            await send_reply(update, f"搵唔到 {args.get('name') or args.get('student_name','')}。")
                            await _log_meta_router_decision_async(update, route_res)
                        else:
                            # res expected: {'id','name','properties'}
                            name = res.get('name') if isinstance(res, dict) else str(res)
                            await send_reply(update, f"學生資料：{name}")
                            await _log_meta_router_decision_async(update, route_res)
                        return

                    if tool == 'list_students':
                        if not res:
                            await send_reply(update, "學生清單：冇學生。")
                            await _log_meta_router_decision_async(update, route_res)
                        else:
                            if isinstance(res, list):
                                names = [s.get('name','') for s in res]
                                await send_reply(update, "學生清單：\n" + "\n".join(names))
                                await _log_meta_router_decision_async(update, route_res)
                            else:
                                await send_reply(update, str(res))
                                await _log_meta_router_decision_async(update, route_res)
                        return

                    if tool == 'new_student':
                        # new_student returns page_id/lesson_db_id or error dict
                        if isinstance(res, dict) and res.get('page_id'):
                            await send_reply(update, f"已新增學生：{res.get('page_id')}")
                            await _log_meta_router_decision_async(update, route_res)
                        else:
                            await send_reply(update, str(res))
                            await _log_meta_router_decision_async(update, route_res)
                        return

                    if tool in ('update_student_progress','log_lesson'):
                        await send_reply(update, str(res))
                        await _log_meta_router_decision_async(update, route_res)
                        return

                    if tool in ('schedule_next_lesson','schedule_next'):
                        await send_reply(update, str(res))
                        await _log_meta_router_decision_async(update, route_res)
                        return

                except Exception:
                    logger.exception('[ROUTE] student tool dispatch failed')
                    await send_reply(update, '學生工具操作失敗。')
                    return
            elif tool == 'query_expenses':
                # lightweight: return daily summary from expenses table
                try:
                    period = args.get('period','today')
                    conn = sqlite3.connect(str(expense.DB_PATH))
                    c = conn.cursor()
                    if period == 'today':
                        today = datetime.date.today().isoformat()
                        q = "SELECT amount, currency, category, merchant FROM expenses WHERE date=?"
                        rows = c.execute(q, (today,)).fetchall()
                        total = sum([r[0] for r in rows]) if rows else 0
                        await send_reply(update, f"今日共 {total} HKD，{len(rows)} 筆。")
                        await _log_meta_router_decision_async(update, route_res)
                        conn.close()
                        return
                except Exception:
                    logger.exception('[ROUTE] query_expenses failed')
                    conn.close()
                    res = await intake.process_text(text, source='telegram')
                    await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
                    return
            elif tool == 'correct_last_entry':
                try:
                    # Minimal correction implementation: update latest expense or intake row
                    field = args.get('field')
                    new_value = args.get('new_value')
                    if field == 'amount':
                        # update last expense amount
                        conn = sqlite3.connect(str(expense.DB_PATH))
                        cur = conn.cursor()
                        cur.execute('SELECT id FROM expenses ORDER BY id DESC LIMIT 1')
                        row = cur.fetchone()
                        if row:
                            eid = row[0]
                            try:
                                amt = float(new_value)
                                cur.execute('UPDATE expenses SET amount=? WHERE id=?', (amt, eid))
                                conn.commit()
                                conn.close()
                                await send_reply(update, f'已更新最近一筆金額為 {amt}。')
                                await _log_meta_router_decision_async(update, route_res)
                                return
                            except Exception:
                                conn.close()
                    # fallback
                    await send_reply(update, '我試過改最近一筆，但出咗問題。')
                    return
                except Exception:
                    logger.exception('[ROUTE] correct_last_entry failed')
                    await send_reply(update, '修改失敗。')
                    return
            elif tool == 'chat_reply':
                try:
                    from jarvis.chat import chat_reply
                    reply = await chat_reply(args.get('message',''))
                    await send_reply(update, reply)
                    await _log_meta_router_decision_async(update, route_res)
                    return
                except Exception:
                    logger.exception('[ROUTE] chat_reply failed')
                    res = await intake.process_text(text, source='telegram')
                    await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
                    return
        else:
            # no tool -> if assistant text provided, send it; else fallback to intake
            if route_res.get('assistant'):
                await send_reply(update, route_res.get('assistant'))
                return
            logger.info('[ROUTE] no tool call, fallback to intake')
            res = await intake.process_text(text, source='telegram')
            await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
            return
    except Exception:
        logger.exception('[ROUTE] unexpected error in dispatch')
        res = await intake.process_text(text, source='telegram')
        await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
        return
        # handy debug for intent routing
        logger.info(f"Intent routing: intent={intent}")
        if confidence >= 0.9 and intent == 'expense':
            # expense auto-store via existing intake pipeline
            logger.info('[ROUTE] auto expense branch')
            res = await intake.process_text(text, source='telegram')
            await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
            return
        elif 0.6 <= confidence < 0.9 and intent == 'expense':
            # RECAP confirmation path
            logger.info('[ROUTE] recap confirm branch')
            await send_reply(update, f"我聽到似係：{rewritten}。我幫你做咗，如果唔啱話我知。")
            return
        elif intent == 'student' and confidence >= 0.7:
            # student query dispatch
            logger.info('[ROUTE] student dispatch')
            # call student handlers in jarvis.student
            try:
                from jarvis.student import find_student, log_lesson, schedule_next
                # simple heuristic: if message contains '點' or '近' -> query
                if '點' in text or '近' in text:
                    stud_name = text.split()[0]
                    stud = find_student(stud_name)
                    await send_reply(update, f"我搵到: {stud}")
                    return
            except Exception:
                logger.exception('[ROUTE] student handler failed')
            # fallback to intake
            res = await intake.process_text(text, source='telegram')
            await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
            return
        elif confidence < 0.6:
            # low confidence => general chat
            logger.info('[ROUTE] low-confidence chat branch')
            try:
                from jarvis.chat import chat_reply
                reply = chat_reply(text)
                await send_reply(update, reply)
                return
            except Exception:
                logger.exception('[ROUTE] chat reply failed, fallback to intake')
                res = await intake.process_text(text, source='telegram')
                await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
                return
        # explicit routing for non-expense intents with sufficient confidence
        elif intent == 'chat':
            logger.info('[ROUTE] explicit chat dispatch')
            try:
                from jarvis.chat import chat_reply
                reply = chat_reply(text)
                await send_reply(update, reply)
                return
            except Exception:
                logger.exception('[ROUTE] chat dispatch failed, fallback to intake')
                res = await intake.process_text(text, source='telegram')
                await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
                return
        elif intent == 'recap':
            logger.info('[ROUTE] recap dispatch')
            try:
                await send_reply(update, f"我聽到似係：{rewritten}。我幫你做咗，如果唔啱話我知。")
                return
            except Exception:
                logger.exception('[ROUTE] recap dispatch failed, fallback to intake')
                res = await intake.process_text(text, source='telegram')
                await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
                return
        elif intent == 'entity':
            logger.info('[ROUTE] entity dispatch')
            try:
                # entities_res captured earlier from lookup_entities
                ctx = entities_res.get('entity_context','') if isinstance(entities_res, dict) else str(entities_res)
                await send_reply(update, f"我偵測到實體：{ctx}")
                return
            except Exception:
                logger.exception('[ROUTE] entity dispatch failed, fallback to intake')
                res = await intake.process_text(text, source='telegram')
                await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
                return
        elif intent in ('correction', 'corrections'):
            logger.info('[ROUTE] correction dispatch')
            try:
                # minimal correction handling: acknowledge and record via intake fallback
                await send_reply(update, '✅ 收到更正，我已記低。')
                return
            except Exception:
                logger.exception('[ROUTE] correction dispatch failed, fallback to intake')
                res = await intake.process_text(text, source='telegram')
                await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
                return
        else:
            # default fallback to intake pipeline (covers expense with low confidence etc.)
            logger.info('[ROUTE] default fallback to intake')
            res = await intake.process_text(text, source='telegram')
            await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
            return
    except Exception:
        logger.exception('[ROUTE] unexpected error in dispatch')
        res = await intake.process_text(text, source='telegram')
        await send_reply(update, res.get('message', '已儲存。') if res.get('ok') else res.get('message','處理失敗。'))
        return


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
            # classify.classify was removed; use classify_intent which returns (intent, confidence)
            try:
                intent, conf = classify_intent(summary)
                # map intent to parsed['type'] when meaningful
                if intent == 'expense':
                    parsed['type'] = 'receipt'
                elif intent and intent != 'chat':
                    parsed['type'] = intent
            except Exception:
                # fallback: do nothing
                pass
    except Exception:
        pass

    # confidence-driven flow
    # use the confidence already computed above (from parsed / extracted), avoid reassigning
    ex = parsed.get('extracted_json', {}) if isinstance(parsed, dict) else {}
    conf = float(confidence or 0.0)

    # DEBUG: parsed keys and confidence
    try:
        logger.info("DEBUG on_photo: parsed keys=%s, confidence=%.2f, threshold=%.2f",
                    list(parsed.keys()) if isinstance(parsed, dict) else str(type(parsed)),
                    float(confidence or 0.0), intake.CONFIDENCE_THRESHOLD)
    except Exception:
        logger.exception("DEBUG on_photo: failed to log parsed keys")

    # DEBUG: which flow we're going to use
    try:
        logger.info("DEBUG on_photo: will use %s flow", "auto-confirm" if float(confidence or 0.0) >= intake.CONFIDENCE_THRESHOLD else "ask_user")
    except Exception:
        pass

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
            # pass full context to formatter: include type, extracted, summary, confidence
            reply = format_image_confirmation({
            "type": parsed.get("type", "unknown"),
                "extracted": ex,
                "summary": parsed.get("summary", ""),
                "confidence": float(confidence or 0.0),
            })
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
    return



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
    "1": "receipt", "收據": "receipt", "單": "receipt", "收据": "receipt",
    "2": "screenshot", "截圖": "screenshot", "截图": "screenshot",
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


def build_application():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    # register photo handler
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    # generic text handler (registry-driven)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def main_async():
    app = build_application()
    session_n = ensure_session_header()
    print(f"\U0001F431 緣一 Jarvis v0.1 running... (Session {session_n})")
    # await run_polling to ensure asyncio loop is properly used
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import asyncio, threading
    # Ensure there is an event loop set for this thread (fixes nohup/background cases)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # If an event loop is already running (e.g. interactive), schedule and block.
    if loop.is_running():
        loop.create_task(main_async())
        threading.Event().wait()
    else:
        # Run in main thread synchronously via Application.run_polling which
        # expects to be called from the main thread and will manage the loop.
        app = build_application()
        session_n = ensure_session_header()
        print(f"\U0001F431 緣一 Jarvis v0.1 running... (Session {session_n})")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
