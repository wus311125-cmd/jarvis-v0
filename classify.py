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
    # placeholder: call OpenRouter or OpenAI via HTTP; for now return unknown
    await asyncio.sleep(0)  # async placeholder
    # simple heuristic: if chinese contains '午餐' or '食', guess expense_text
    lower = text.lower()
    if '午餐' in text or '食' in text or '餐' in text:
        return ClassifyResult('expense_text', 0.7)
    return ClassifyResult('unknown', 0.0)


async def classify(text: str, attachments=None) -> ClassifyResult:
    # Layer 1: regex fast path
    t = _regex_match_text(text)
    if t:
        return ClassifyResult(t, 1.0)
    # Layer 2: LLM fallback
    return await llm_classify(text)
