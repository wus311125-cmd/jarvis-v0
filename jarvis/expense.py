import re
from jarvis.llm_prompts import LLM_CLASSIFY_PROMPT

def parse(text, llm_client=None):
    """Parse text into amount, description, direction.
    If text has leading '-', direction=expense. Else ask LLM (if provided) or fallback expense.
    """
    text = text.strip()
    # detect explicit minus
    if text.startswith('-'):
        t = text[1:].strip()
        amount = _extract_amount(t)
        desc = _extract_desc(t)
        return {'amount': abs(amount) if amount is not None else None, 'description': desc, 'direction': 'expense'}

    # try to extract amount locally
    amount = _extract_amount(text)
    desc = _extract_desc(text)

    # if no llm provided -> default expense
    if llm_client is None:
        return {'amount': amount, 'description': desc, 'direction': 'expense'}

    # call LLM classifier (assume llm_client.classify returns parsed json according to prompt)
    try:
        resp = llm_client.classify(text, prompt=LLM_CLASSIFY_PROMPT)
        # expected fields: amount, currency, description, direction
        direction = resp.get('direction') if resp.get('direction') in ('expense','income') else 'expense'
        amount = resp.get('amount') if resp.get('amount') is not None else amount
        description = resp.get('description') or desc
        return {'amount': amount, 'description': description, 'direction': direction}
    except Exception:
        return {'amount': amount, 'description': desc, 'direction': 'expense'}


def _extract_amount(text):
    m = re.search(r"-?\s*([0-9]+(?:\.[0-9]{1,2})?)", text)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    return None


def _extract_desc(text):
    # remove amount and minus
    desc = re.sub(r"-?\s*[0-9]+(?:\.[0-9]{1,2})?", "", text).strip()
    return desc


def store_expense(db_conn, amount, description, direction='expense'):
    cur = db_conn.cursor()
    cur.execute("INSERT INTO expenses (amount, description, direction) VALUES (?,?,?)", (amount, description, direction))
    db_conn.commit()

    # Also save to chat history so Jarvis can reference recent expense in conversation
    try:
        from jarvis.history import save_message
        save_message(db_conn, 'assistant', f"記低: {direction} ${int(amount) if amount is not None else ''} / {description}", tool_used='log_expense')
    except Exception:
        pass
