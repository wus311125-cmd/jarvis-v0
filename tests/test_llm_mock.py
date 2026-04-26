import asyncio
import json
from types import SimpleNamespace

import classify


class MockResp:
    def __init__(self, content_str):
        self._content = content_str

    def raise_for_status(self):
        return None

    def json(self):
        # mimic OpenRouter chat completion shape
        return {"choices": [{"message": {"content": self._content}}]}


def make_post_return(content_str):
    def _post(url, headers=None, json=None, timeout=None):
        return MockResp(content_str)
    return _post


def test_llm_classify_json_simple(monkeypatch):
    content = json.dumps({"type": "expense_text", "confidence": 0.92})
    monkeypatch.setattr('requests.post', make_post_return(content))
    res = asyncio.run(classify.classify("lunch at cafe"))
    assert res.type == 'expense_text'
    assert res.confidence == 0.92


def test_llm_classify_wrapped_single_quotes(monkeypatch):
    # wrapped prose with python-style dict (single quotes)
    wrapped = "Here's the result:\n\n{'type': 'expense_text', 'confidence': 0.85}\nThanks"
    monkeypatch.setattr('requests.post', make_post_return(wrapped))
    res = asyncio.run(classify.classify("brunch nearby"))
    assert res.type == 'expense_text'
    assert abs(res.confidence - 0.85) < 1e-6


def test_llm_classify_low_confidence_ask(monkeypatch):
    content = json.dumps({"type": "unknown", "confidence": 0.6})
    monkeypatch.setattr('requests.post', make_post_return(content))
    res = asyncio.run(classify.classify("something ambiguous"))
    assert res.type == 'ask_user'
    assert abs(res.confidence - 0.6) < 1e-6


def test_llm_extract_expense(monkeypatch):
    content = json.dumps({"amount": 45, "currency": "HKD", "description": "午餐"})
    monkeypatch.setattr('requests.post', make_post_return(content))
    parsed = asyncio.run(classify.llm_extract_expense("午餐 45 蚊"))
    assert isinstance(parsed, dict)
    assert parsed.get('amount') == 45
    assert parsed.get('currency') == 'HKD'
