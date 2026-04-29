import pytest
import importlib

import recap


def test_recap_numeric_correction():
    inp = "頭先嗰筆改做 78"
    out = recap.recap_rewrite(inp, '')
    assert isinstance(out, dict)
    assert 'rewritten_text' in out
    assert out['distilled_fields'] is not None
    assert out['distilled_fields'].get('field') == 'amount'
    assert out['distilled_fields'].get('new_value') == 78


def test_recap_merchant_correction():
    inp = "頭先嗰筆改做 大家樂"
    out = recap.recap_rewrite(inp, '')
    assert out['distilled_fields'] is not None
    assert out['distilled_fields'].get('field') == 'merchant'
    assert out['distilled_fields'].get('new_value') == '大家樂'
