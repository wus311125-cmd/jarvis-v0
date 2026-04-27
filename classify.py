import yaml
from pathlib import Path
from typing import Dict, Any

REG_PATH = Path(__file__).parent / 'types' / 'registry.yaml'

def load_registry() -> Dict[str, Any]:
    with REG_PATH.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_type(extracted: Dict[str, Any]) -> str:
    """Simple registry-driven type selector.
    Expect extracted to have keys like 'merchant', 'amount', 'summary'
    """
    reg = load_registry()
    types = reg.get('types', [])
    # heuristics based on extracted content
    if not extracted:
        return 'photo'
    if extracted.get('merchant') and extracted.get('amount'):
        return 'receipt'
    if extracted.get('summary') and len(extracted.get('summary','')) > 10:
        return 'screenshot'
    return 'photo'


import asyncio


class ClassifyResult:
    def __init__(self, type_id: str, confidence: float = 1.0, extracted: dict | None = None):
        self.type = type_id
        self.confidence = confidence
        self.extracted = extracted or {}


def _regex_match_text(text: str) -> str | None:
    reg = load_registry()
    types = reg.get('types', [])
    import re
    # Quick numeric fallback: bare numbers like '-85' should be expense_text
    if re.match(r'^-?\d+(?:\.\d+)?(?:\s*(?:HKD|USD|CNY))?$', text.strip()):
        return 'expense_text'
    # Cantonese / informal expense patterns
    # examples: '午餐 45 蚊', '買咗 XX 28蚊', '交通 $32'
    try:
        if re.search(r"\d+\s*蚊", text) or re.search(r"\$\s*\d+", text) or re.search(r"\b(?:HKD|USD|CNY)\b", text, flags=re.IGNORECASE):
            return 'expense_text'
        # consumption verbs / common Cantonese expense words + a number anywhere
        if re.search(r"\b(?:午餐|晚餐|早餐|買咗|買左|買|搭車|的士|巴士|車費|飲|食|埋單|付錢)\b", text) and re.search(r"\d", text):
            return 'expense_text'
    except re.error:
        pass
    for t in sorted(types, key=lambda x: -x.get('priority', 0)):
        patterns = t.get('patterns') or {}
        pattern = patterns.get('text_regex')
        if not pattern:
            continue
        try:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return t.get('id')
        except re.error:
            continue
    return None


def match_text_to_type(text: str) -> str | None:
    return _regex_match_text(text)


async def llm_classify(text: str) -> ClassifyResult:
    # Attempt to call OpenRouter for LLM classification. Falls back to heuristic if network fails.
    import os, base64, requests, json
    await asyncio.sleep(0)
    reg = load_registry()
    llm_cfg = reg.get('_llm_config', {})
    model = llm_cfg.get('model', 'openai/gpt-4o-mini')
    timeout = 10
    api_key = os.environ.get('OPENROUTER_API_KEY')
    prompt = (
        "You are a classifier. Given the user text, return a JSON object with keys: 'type' (one of registry ids) and 'confidence' (0.0-1.0).\n"
        "Registry examples:\n"
    )
    for t in reg.get('types', []):
        exs = t.get('examples') or []
        if exs:
            prompt += f"{t.get('id')}: examples: {exs}\n"
    prompt += f"\nUser text: {text}\n\nRespond with JSON only."

    if not api_key:
        # fallback heuristic
        if '午餐' in text or '食' in text or '餐' in text:
            return ClassifyResult('expense_text', 0.7)
        return ClassifyResult('unknown', 0.0)

    url = 'https://api.openrouter.ai/v1/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': 'You are a JSON-only classifier as specified.'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': llm_cfg.get('temperature', 0)
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        # robust JSON extraction: accept wrapped text, single-quotes, or extra prose
        try:
            parsed = json.loads(content)
        except Exception:
            # try to extract the first {...}..} substring
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and end > start:
                snippet = content[start:end+1]
                try:
                    parsed = json.loads(snippet)
                except Exception:
                    # last resort: ast.literal_eval for python-style dicts with single quotes
                    import ast
                    parsed = ast.literal_eval(snippet)
            else:
                raise ValueError('no json found')
        typ = parsed.get('type') if isinstance(parsed, dict) else 'unknown'
        conf = float(parsed.get('confidence', 0.0)) if isinstance(parsed, dict) else 0.0
        return ClassifyResult(typ or 'unknown', conf)
    except Exception:
        # network or parse error -> fallback heuristic
        if '午餐' in text or '食' in text or '餐' in text:
            return ClassifyResult('expense_text', 0.7)
        return ClassifyResult('unknown', 0.0)


async def classify(text: str, attachments=None) -> ClassifyResult:
    # Layer 1: regex fast path
    t = _regex_match_text(text)
    if t:
        return ClassifyResult(t, 1.0)
    # Layer 2: LLM fallback
    res = await llm_classify(text)
    # apply confidence gating from registry config
    reg = load_registry()
    llm_cfg = reg.get('_llm_config', {})
    thresholds = llm_cfg.get('confidence_thresholds', {})
    auto_th = float(thresholds.get('auto', 0.8))
    ask_th = float(thresholds.get('ask_user', 0.5))
    if res.confidence >= auto_th:
        return res
    if res.confidence >= ask_th:
        return ClassifyResult('ask_user', res.confidence, res.extracted)
    return ClassifyResult('unknown', res.confidence)


async def llm_extract_expense(text: str) -> dict:
    """Call LLM to extract amount/currency/description from free text. Fallback to regex."""
    import os, requests, json
    reg = load_registry()
    llm_cfg = reg.get('_llm_config', {})
    model = llm_cfg.get('model', 'openai/gpt-4o-mini')
    api_key = os.environ.get('OPENROUTER_API_KEY')
    prompt = (
        "Extract expense info from the following text. Return JSON with keys: amount (number), currency (HKD/USD/CNY), description (string).\nText: " + text + "\nRespond with JSON only."
    )
    if not api_key:
        # fallback: simple regex
        import re
        m = re.search(r'(-?\d+(?:\.\d+)?)', text)
        amount = float(m.group(1)) if m else None
        return {'amount': amount, 'currency': 'HKD', 'description': text}
    url = 'https://api.openrouter.ai/v1/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': 'You are an extractor. Return JSON only.'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': llm_cfg.get('temperature', 0)
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        parsed = json.loads(content)
        return parsed
    except Exception:
        import re
        m = re.search(r'(-?\d+(?:\.\d+)?)', text)
        amount = float(m.group(1)) if m else None
        return {'amount': amount, 'currency': 'HKD', 'description': text}
