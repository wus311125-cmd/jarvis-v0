import asyncio
import os

import classify


def test_regex_negative_number():
    # '-85' should match expense_text via regex fast path
    res = asyncio.run(classify.classify("-85"))
    assert res.type == 'expense_text'
    assert res.confidence == 1.0


def test_llm_classify_and_extract_lunch():
    # '午餐 45 蚊' should fallthrough to llm_classify (heuristic) -> ask_user (0.7)
    res = asyncio.run(classify.classify("午餐 45 蚊"))
    assert res.type in ('ask_user', 'expense_text')
    # now run extractor
    parsed = asyncio.run(classify.llm_extract_expense("午餐 45 蚊"))
    assert parsed is not None
    # amount should be parseable as number (heuristic fallback returns amount too)
    assert 'amount' in parsed and parsed['amount'] is not None


def test_unknown_text():
    res = asyncio.run(classify.classify("hello"))
    assert res.type == 'unknown'
