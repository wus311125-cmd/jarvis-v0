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
        "name": "record_expense",
        "description": "Record an expense with amount, description and currency",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "description": {"type": "string"},
                "currency": {"type": "string"}
            },
            "required": ["amount"]
        }
    },
    {
        "name": "record_income",
        "description": "Record an income with amount, description and currency",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "description": {"type": "string"},
                "currency": {"type": "string"}
            },
            "required": ["amount"]
        }
    },
    {
        "name": "query_student",
        "description": "Query a student by name and return summary info",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_student_progress",
        "description": "Update student progress notes",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "notes": {"type": "string"}
            },
            "required": ["name","notes"]
        }
    },
    {
        "name": "query_expenses",
        "description": "Query expenses for a given period (e.g. today, 2026-04-27, last 7 days)",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {"type": "string"}
            },
            "required": ["period"]
        }
    },
    {
        "name": "chat_reply",
        "description": "Produce a chat reply for conversational messages",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"}
            },
            "required": ["message"]
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
    """
    if recent is None:
        recent = _load_recent_history(10)
    system = _build_system_prompt(recent)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text}
    ]

    if OPENROUTER_API_KEY is None:
        raise RuntimeError('OPENROUTER_API_KEY not set')

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
