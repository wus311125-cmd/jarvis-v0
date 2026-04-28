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
        "type": "function",
        "function": {
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
        }
    },
    {
        "type": "function",
        "function": {
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
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_student",
            "description": "查詢學生資料：用戶問某位學生嘅上堂時間、進度、聯絡方法時用",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "學生名（中文或英文）"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
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
        }
    },
    {
        "type": "function",
        "function": {
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
        }
    },
    {
        "type": "function",
        "function": {
            "name": "correct_last_entry",
            "description": "修改最近一筆記錄嘅金額或內容。當用戶說『改做XX』、『改返』、『頭先嗰筆』等修正類語句時使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "description": "要改嘅欄位（amount/description/vendor/category）"},
                    "new_value": {"type": "string", "description": "新值"}
                },
                "required": ["field", "new_value"]
            }
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
    # New concise Cantonese system prompt per request
    system = (
        "你係 Jarvis，Hopan 嘅私人AI助手。你講嘢簡潔、有少少幽默、用廣東話口語。"
        "如果用戶嘅訊息唔需要 call 任何 tool，直接用自然嘅廣東話回覆，保持 1-2 句就好。"
    )
    # append recent history if present
    history = "\n".join(recent)
    if history:
        system = system + "\n\nRecent conversation history:\n" + history
    return system


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
        # OpenRouter expects the newer 'tools' key (not 'functions')
        "tools": TOOLS,
        # use new key name for tool selection
        "tool_choice": "auto",
        "temperature": 0.0,
    }

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    # Debug logs to help E2E diagnose function-calling issues
    try:
        print("[OPENROUTER DEBUG] Sending request to:", OPENROUTER_URL)
        print("[OPENROUTER DEBUG] Payload keys:", list(payload.keys()))
        print("[OPENROUTER DEBUG] API_KEY length:", len(OPENROUTER_API_KEY) if OPENROUTER_API_KEY else 0)
    except Exception:
        pass

    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=15)
    # CRITICAL DEBUG: print raw response text immediately, before any parsing
    try:
        print("[RAW RESPONSE]", resp.text[:500])
    except Exception:
        pass
    resp.raise_for_status()
    data = resp.json()
    choices = data.get('choices') or []
    if not choices:
        # empty response from model — fallback to no tool
        return {'tool': None, 'args': None, 'assistant': None}
    choice = choices[0]
    msg = choice.get('message', {})

    # New/OpenRouter format: 'tool_calls' array
    if msg.get('tool_calls'):
        try:
            tc = msg['tool_calls'][0]
            tool_name = tc['function']['name']
            tool_args_raw = tc['function'].get('arguments') or '{}'
            try:
                tool_args = json.loads(tool_args_raw)
            except Exception:
                tool_args = {}
            return {'tool': tool_name, 'args': tool_args, 'assistant': None}
        except Exception:
            # fallthrough to other parsing strategies
            pass

    # Backwards-compatible fallbacks: 'function_call' or 'tool_call'
    fc = msg.get('function_call') or msg.get('tool_call')
    if fc:
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
