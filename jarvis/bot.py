from jarvis.expense import parse, store_expense
from jarvis.chat import chat_reply
from jarvis.history import save_message
from skills.entity_lookup import lookup_entities
from classify import rewrite_intent, classify_intent
import re
import sqlite3


def format_reply(amount, description, direction):
    if direction == 'income':
        return f"💰 ${int(amount) if amount is not None else ''} HKD / {description} / 收入"
    else:
        return f"💸 ${int(amount) if amount is not None else ''} HKD / {description} / 支出"


def route_text(db_conn, text, llm_client=None):
    # Step 1: Entity lookup
    entities = lookup_entities(text)
    entity_context = entities.get('entity_context','')

    # Step 2: Rewrite intent
    # build recent turns
    try:
        recent = []
        cur = db_conn.cursor()
        for row in cur.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT 6"):
            recent.append(f"{row[0]}: {row[1]}")
        recent.reverse()
    except Exception:
        recent = []

    rewritten = rewrite_intent(text, entity_context, recent)

    # Step 3: classify
    intent, conf = classify_intent(rewritten)

    # Step 4: confidence gate
    if conf > 0.9:
        # execute directly
        if intent == 'expense':
            parsed = parse(text, llm_client=llm_client)
            store_expense(db_conn, parsed.get('amount'), parsed.get('description'), parsed.get('direction'))
            reply = format_reply(parsed.get('amount'), parsed.get('description'), parsed.get('direction'))
        elif intent == 'student':
            # for v0.1, route to chat/student handler: use chat_reply fallback
            reply = chat_reply(text)
        else:
            reply = chat_reply(text)
        try:
            save_message(db_conn, 'assistant', reply)
        except Exception:
            pass
        return reply
    elif conf >= 0.6:
        # execute + notify
        if intent == 'expense':
            parsed = parse(text, llm_client=llm_client)
            store_expense(db_conn, parsed.get('amount'), parsed.get('description'), parsed.get('direction'))
            reply = format_reply(parsed.get('amount'), parsed.get('description'), parsed.get('direction'))
            notify = f"我幫你做咗：{reply}。如果唔啱話我知。"
            full_reply = reply + '\n' + notify
        else:
            # fallback to chat but inform
            chatr = chat_reply(text)
            full_reply = chatr + '\n' + '我估你係想做上面嘅事，我已執行。如果唔啱話我知。'
        try:
            save_message(db_conn, 'assistant', full_reply)
        except Exception:
            pass
        return full_reply
    else:
        # low confidence -> ask clarification (list top 2 intents in v0.1 simulated)
        clar = '我唔係好肯定你係咪想：1) 記帳；2) 查學生資料。你係想邊樣？'
        try:
            save_message(db_conn, 'assistant', clar)
        except Exception:
            pass
        return clar


def handle_user_message(db_conn, text, llm_client=None):
    # main entrypoint for messages
    # run routing
    reply = route_text(db_conn, text, llm_client=llm_client)
    # detect corrections referencing previous assistant reply
    # get latest assistant message
    try:
        cur = db_conn.cursor()
        row = cur.execute("SELECT content FROM chat_history WHERE role='assistant' ORDER BY id DESC LIMIT 1").fetchone()
        recent_assistant = row[0] if row else ''
    except Exception:
        recent_assistant = ''
    detect_and_record_correction(db_conn, text, recent_assistant)
    return reply


def detect_and_record_correction(db_conn, user_text, recent_assistant_reply):
    """Detect user corrections like '唔係，我想 X' and record into corrections table."""
    if re.search(r"唔係|錯咗|我想", user_text):
        try:
            conn = db_conn
            cur = conn.cursor()
            cur.execute('INSERT INTO corrections (original, message, context) VALUES (?,?,?)', (
                recent_assistant_reply, user_text, 'auto'
            ))
            conn.commit()
            return True
        except Exception:
            return False
    return False
