from jarvis.expense import parse, store_expense
from jarvis.chat import chat_reply
from jarvis.history import save_message


def format_reply(amount, description, direction):
    if direction == 'income':
        return f"💰 ${int(amount) if amount is not None else ''} HKD / {description} / 收入"
    else:
        return f"💸 ${int(amount) if amount is not None else ''} HKD / {description} / 支出"


def route_text(db_conn, text, llm_client=None):
    # expense parse first
    parsed = parse(text, llm_client=llm_client)
    amt = parsed.get('amount')
    desc = parsed.get('description')
    direction = parsed.get('direction')

    # if explicit expense/income detected -> store
    if direction in ('expense', 'income') and (text.startswith('-') or parsed.get('amount') is not None):
        store_expense(db_conn, amt, desc, direction)
        reply = format_reply(amt, desc, direction)
        try:
            save_message(db_conn, 'assistant', reply)
        except Exception:
            pass
        return reply

    # fallback to general chat
    reply = chat_reply(text, db_path=db_conn.execute('PRAGMA database_list').fetchall()[0][2] if False else 'jarvis.db')
    try:
        save_message(db_conn, 'assistant', reply)
    except Exception:
        pass
    return reply
