import os
import json
from typing import List
import logging

from jarvis.llm_prompts import LLM_CLASSIFY_PROMPT
import httpx
import json as _json
import ast
from types import SimpleNamespace
import re
import subprocess

# Tools registry for function-calling compatibility. We'll add search_memory here
# so the router/LLM can call it via function-calling. Each tool is described simply.
TOOLS = [
    {
        'name': 'search_memory',
        'description': '搜尋 Obsidian vault 記憶，用語意相似度返回最相關結果。',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string'},
                'top_k': {'type': 'integer'}
            },
            'required': ['query']
        }
    }
]

OPENROUTER_KEY = os.getenv('OPENROUTER_API_KEY')
# Use S51 RECAP model by default
MODEL = os.getenv('CLASSIFY_MODEL', 'qwen/qwen3-30b-a3b')
ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'


def rewrite_intent(message: str, entity_context: str, recent_turns: List[str]) -> str:
    """Call LLM to rewrite user message into a structured intent sentence."""
    system = "你必須用繁體中文（香港廣東話口語）回覆。唔好用普通話、簡體中文或英文。Technical term 可以用英文。\n你係一個 intent rewriter。將用戶嘅廣東話訊息 rewrite 成一句結構化嘅意圖描述（中文）。"
    prompt = f"""{system}\n用戶訊息: {message}\nEntity context: {entity_context}\n最近對話: {recent_turns[-3:]}\n\nOutput 一句話描述用戶想做咩，格式：「用戶想 [動作]（[細節]）」\n如果唔確定，保留原意，唔好猜。"""
    if not OPENROUTER_KEY:
        # fallback: very simple rule
        # also emit a small distill log for offline fallback
        try:
            dl = logging.getLogger('distill')
            dl.info(json.dumps({"ts": __import__('datetime').datetime.utcnow().isoformat(), "layer": "classify_fallback", "message": message}, ensure_ascii=False))
        except Exception:
            pass
        return message

    headers = {'Authorization': f'Bearer {OPENROUTER_KEY}', 'Content-Type': 'application/json'}
    payload = {'model': MODEL, 'messages': [{'role':'system','content':system},{'role':'user','content':prompt}], 'max_tokens': 120}
    try:
        r = httpx.post(ENDPOINT, headers=headers, json=payload, timeout=10.0)
        r.raise_for_status()
        data = r.json()
        if 'choices' in data and len(data['choices'])>0:
            msg = data['choices'][0].get('message') or data['choices'][0]
            return msg.get('content') if isinstance(msg, dict) else str(msg)
        return message
    except Exception:
        return message


def classify_intent(rewritten: str):
    """Lightweight heuristic classifier fallback.

    Returns (intent, confidence).
    Known intents: 'expense_text', 'expense', 'chat', 'unknown'
    """
    text = (rewritten or '').strip()
    # direct negative-prefixed amount (e.g., "-85") -> explicit expense_text with full confidence
    if re.match(r'^\s*-[0-9]+(?:\.[0-9]+)?\s*$', text):
        return ('expense_text', 1.0)

    # explicit numeric anywhere -> expense with high confidence
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if m:
        # if text contains common food/meal keywords, treat as ask_user (need confirmation)
        if any(k in text for k in ['午餐', '晚餐', '餐', 'coffee', '麥當勞', '午飯', '晚飯', 'brunch', 'lunch']):
            return ('ask_user', 0.7)
        return ('expense', 0.95)

    # otherwise unknown (be conservative)
    return ('unknown', 0.0)


async def classify(text: str):
    """Compatibility coroutine for legacy callers.

    Prefer LLM-based classification when possible (calls requests.post).
    Fallback to heuristic classify_intent when remote call not possible or parsing fails.
    Returns SimpleNamespace(type=..., confidence=...)
    """
    # quick heuristic fast-paths
    if isinstance(text, str) and re.match(r'^\s*-[0-9]+(?:\.[0-9]+)?\s*$', text):
        return SimpleNamespace(type='expense_text', confidence=1.0)

    # attempt remote LLM classify
    system = "你必須用繁體中文（香港廣東話口語）回覆。唔好用普通話、簡體中文或英文。Technical term 可以用英文。\nYou are a classifier. Return a JSON object with keys: type, confidence"
    payload = {
        'model': MODEL,
        'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': text}],
        'max_tokens': 60,
    }
    try:
        headers = {'Authorization': f'Bearer {OPENROUTER_KEY}', 'Content-Type': 'application/json'}
        r = httpx.post(ENDPOINT, headers=headers, json=payload, timeout=10.0)
        r.raise_for_status()
        data = r.json()
        # extract content
        content = None
        if isinstance(data, dict) and data.get('choices'):
            ch = data['choices'][0]
            msg = ch.get('message') or ch
            if isinstance(msg, dict):
                content = msg.get('content')
            else:
                content = str(msg)
        if not content:
            # try raw json body
            content = _json.dumps(data)

        # try parse JSON first
        parsed = None
        try:
            parsed = _json.loads(content)
        except Exception:
            try:
                parsed = ast.literal_eval(content)
            except Exception:
                # try to find JSON substring
                m = re.search(r'\{[\s\S]*\}', content)
                if m:
                    try:
                        parsed = _json.loads(m.group(0))
                    except Exception:
                        try:
                            parsed = ast.literal_eval(m.group(0))
                        except Exception:
                            parsed = None

        if isinstance(parsed, dict) and parsed.get('type') is not None:
            t = parsed.get('type')
            conf = float(parsed.get('confidence') or 0.0)
            # map low-confidence unknown -> ask_user (per tests)
            if t == 'unknown' and conf >= 0.6:
                t = 'ask_user'
            return SimpleNamespace(type=t, confidence=conf)
    except Exception:
        # ignore and fallback
        pass

    # fallback heuristic
    intent, confidence = classify_intent(text)
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


def search_memory(query: str, top_k: int = 5) -> list:
    """Wrapper around local memsearch CLI. Returns list of dicts: {text, source_file, score}.

    Non-destructive: only reads existing memsearch index under ~/.memsearch.
    """
    ms = os.path.expanduser('~/.local/bin/memsearch')
    if not os.path.exists(ms):
        # try fallback in PATH
        ms = 'memsearch'
    cmd = [ms, 'search', query, '-k', str(top_k), '-j', '--source-prefix', os.path.expanduser('~/.memsearch/memory')]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = proc.stdout.strip()
        if not out:
            return []
        # memsearch returns JSON array
        parsed = _json.loads(out)
        results = []
        for item in parsed:
            # expected fields: score, chunk, source
            text = item.get('chunk') or item.get('text') or ''
            source = item.get('source') or item.get('path') or ''
            score = item.get('score') if item.get('score') is not None else item.get('distance')
            results.append({'text': text, 'source_file': source, 'score': score})
        return results
    except Exception:
        return []
