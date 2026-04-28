import os
import json
from typing import List

from jarvis.llm_prompts import LLM_CLASSIFY_PROMPT
import requests
from types import SimpleNamespace
import re

OPENROUTER_KEY = os.getenv('OPENROUTER_API_KEY')
MODEL = os.getenv('CLASSIFY_MODEL', 'gpt-5-mini')
ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'


def rewrite_intent(message: str, entity_context: str, recent_turns: List[str]) -> str:
    """Call LLM to rewrite user message into a structured intent sentence."""
    system = "你係一個 intent rewriter。將用戶嘅廣東話訊息 rewrite 成一句結構化嘅意圖描述（中文）。"
    prompt = f"""{system}\n用戶訊息: {message}\nEntity context: {entity_context}\n最近對話: {recent_turns[-3:]}\n\nOutput 一句話描述用戶想做咩，格式：「用戶想 [動作]（[細節]）」\n如果唔確定，保留原意，唔好猜。"""
    if not OPENROUTER_KEY:
        # fallback: very simple rule
        return message

    headers = {'Authorization': f'Bearer {OPENROUTER_KEY}', 'Content-Type': 'application/json'}
    payload = {'model': MODEL, 'messages': [{'role':'system','content':system},{'role':'user','content':prompt}], 'max_tokens': 120}
    try:
        r = requests.post(ENDPOINT, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        if 'choices' in data and len(data['choices'])>0:
            msg = data['choices'][0].get('message') or data['choices'][0]
            return msg.get('content') if isinstance(msg, dict) else str(msg)
        return message
    except Exception:
        return message


def classify_intent(rewritten: str):
    """Placeholder classifier: return (intent, confidence). Real classifier already exists elsewhere; v0.1 simple heuristics."""
    text = rewritten.lower()
    # expense patterns
    if any(k in text for k in ['記', '收', '花', '付', '蚊', 'hk', '$']):
        return ('expense', 0.95)
    if any(k in text for k in ['學', '課', '上堂', '約']):
        return ('student', 0.85)
    # fallback
    return ('chat', 0.5)


async def classify(text: str):
    """Compatibility coroutine for legacy callers.
    Returns an object with attributes: type, confidence
    """
    intent, confidence = classify_intent(text)
    # keep compatibility: older code expects cls_res.type in ('expense_text','expense')
    # classify_intent returns 'expense' for expense-like texts
    return SimpleNamespace(type=intent, confidence=confidence)


async def llm_extract_expense(text: str) -> dict:
    """Lightweight expense extractor used as fallback for LLM extraction.
    Tries simple regex to pull an amount and a short description.
    """
    # quick amount regex: capture optional minus, optional currency symbol, number
    m = re.search(r"(-)?\s*(?:HKD|\$|USD|CNY)?\s*([0-9]+(?:\.[0-9]+)?)", text)
    amount = None
    currency = 'HKD'
    if m:
        # if there is a leading '-', treat as expense
        amt = float(m.group(2))
        amount = abs(amt)
        # detect currency token if present
        cur_token = re.search(r"\b(HKD|USD|CNY)\b", text, re.IGNORECASE)
        if cur_token:
            currency = cur_token.group(1).upper()

    # naive merchant/description: remove amount token
    desc = re.sub(r"(-)?\s*(?:HKD|\$|USD|CNY)?\s*[0-9]+(?:\.[0-9]+)?", "", text).strip()
    # category heuristic: look for common keywords
    category = None
    if any(k in text.lower() for k in ['食', '午餐', '晚餐', '餐', 'coffee', '麥當勞']):
        category = 'food'
    elif any(k in text.lower() for k in ['uber', '的士', 'taxi', '交通']):
        category = 'transport'

    return {
        'amount': amount,
        'currency': currency,
        'category': category,
        'merchant': None,
        'date': None,
        'description': desc,
    }
