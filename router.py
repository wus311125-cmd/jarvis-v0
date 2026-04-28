import os
import json
import requests
import sqlite3
from typing import Any, Dict, List

from skills import intake

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
MODEL = os.environ.get('OPENROUTER_MODEL', 'gpt-5-mini')


TOOLS = [
    {
        "name": "log_expense",
        "description": "記錄一筆支出：當用戶講到買嘢、食飯、花費。常見格式：-金額 描述，例如「-88 大快活」",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "金額（正數）"},
                "description": {"type": "string", "description": "消費描述"},
                "vendor": {"type": "string", "description": "商戶名稱（如有）"},
                "category": {"type": "string", "description": "分類（food/transport/shopping/other）"}
            },
            "required": ["amount", "description"]
        }
    },
    {
        "name": "log_income",
        "description": "記錄一筆收入：當用戶講到收款、學費、人工等。常見格式：+金額 描述，例如「+3000 學費」",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "金額（正數）"},
                "description": {"type": "string", "description": "收入描述"},
                "source": {"type": "string", "description": "收入來源"}
            },
            "required": ["amount", "description"]
        }
    },
    {
        "name": "find_student",
        "description": "查詢學生資料：用戶問某位學生嘅上堂時間、進度、聯絡方法時用",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "學生名（中文或英文）"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "log_lesson",
        "description": "記錄一堂課內容：當用戶講「幫我記低今日教咗乜」時使用",
        "parameters": {
            "type": "object",
            "properties": {
                "student_name": {"type": "string", "description": "學生名"},
                "content": {"type": "string", "description": "課堂內容"},
                "date": {"type": "string", "description": "日期（YYYY-MM-DD，預設今日）"}
            },
            "required": ["student_name", "content"]
        }
    },
    {
        "name": "query_expenses",
        "description": "查詢支出總額或明細，例如「今個月使咗幾多」",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "時間範圍（today/this_week/this_month/last_month）"},
                "category": {"type": "string", "description": "分類篩選（可選）"}
            },
            "required": ["period"]
        }
    },
    {
        "name": "correct_last_entry",
        "description": "修改最近一筆記錄：當用戶講「改返」「唔係，應該係」等時使用",
        "parameters": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "要改嘅欄位（amount/description/vendor/category）"},
                "new_value": {"type": "string", "description": "新值"}
            },
            "required": ["field", "new_value"]
        }
    }
]


def _load_recent_history(limit: int = 10) -> List[str]:
    out: List[str] = []
    try:
        db = sqlite3.connect(str(intake.DB_PATH))
        cur = db.cursor()
        cur.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        for r in reversed(rows):
            role, content = r
            out.append(f"{role}: {content}")
        db.close()
    except Exception:
        # fallback empty
        return []
    return out


def _build_system_prompt(recent: List[str]) -> str:
    profile = (
        "You are Jarvis - an assistant for a guitar teacher Hopan. "
        "Default currency is HKD. Students managed in Notion. "
    )
    history = "\n".join(recent)
    guidance = (
        "You have access to tools. When user asks to record expenses or incomes, call the corresponding tool with structured args. "
        "Prefer tools over free-form text. For conversational queries, use chat_reply tool. "
        "Respect the following common accounting input formats: e.g. '-88 lunch McCafe' (expense), '+3000 tuition' (income), or natural language. "
    )
    parts = [profile, guidance]
    if history:
        parts.append("Recent conversation history:\n" + history)
    return "\n\n".join(parts)


def route(text: str, entity_context: str = '', recent: List[str] = None) -> Dict[str, Any]:
    """Send user text to OpenRouter with function definitions.
    Returns: { 'tool': name | None, 'args': dict | None, 'assistant': str | None }
    If OPENROUTER_API_KEY is not set, use lightweight local heuristics as fallback to enable offline testing.
    """
    if recent is None:
        recent = _load_recent_history(10)
    system = _build_system_prompt(recent)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text}
    ]

    # Local heuristic fallback when no API key (allows offline E2E smoke tests)
    if OPENROUTER_API_KEY is None:
        # explicit -amount / +amount
        m = re.match(r'^\s*([+-])(\d+(?:\.\d+)?)\s*(.*)$', text)
        if m:
            sign, amt_s, rest = m.groups()
            amt = float(amt_s)
            if sign == '-':
                return {'tool': 'log_expense', 'args': {'amount': amt, 'description': rest.strip(), 'vendor': ''}, 'assistant': None}
            else:
                return {'tool': 'log_income', 'args': {'amount': amt, 'description': rest.strip(), 'source': ''}, 'assistant': None}
        # simple queries
        if '今個月' in text or '本月' in text or '今個 月' in text:
            return {'tool': 'query_expenses', 'args': {'period': 'this_month'}, 'assistant': None}
        if '幾時上堂' in text or '上堂' in text:
            # try extract name
            parts = text.split()
            name = parts[0] if parts else text
            return {'tool': 'find_student', 'args': {'name': name}, 'assistant': None}
        # default: treat as chat reply
        return {'tool': None, 'args': None, 'assistant': '嗯，收到，我記低。'}

    payload = {
        "model": MODEL,
        "messages": messages,
        "functions": TOOLS,
        "function_call": "auto",
        "temperature": 0.0,
    }

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    choice = data.get('choices', [])[0]
    msg = choice.get('message', {})
    # if tool call
    if msg.get('function_call'):
        fc = msg.get('function_call')
        name = fc.get('name')
        args_raw = fc.get('arguments') or '{}'
        try:
            args = json.loads(args_raw)
        except Exception:
            args = {}
        return {'tool': name, 'args': args, 'assistant': None}
    # else assistant content
    assistant_text = msg.get('content')
    return {'tool': None, 'args': None, 'assistant': assistant_text}
