"""Lightweight local stub for `requests` to allow offline unit tests.
This mimics the minimal API used by the codebase: requests.post(...)
Return object has .json() and .raise_for_status().
"""
from types import SimpleNamespace


class _Resp:
    def __init__(self, data=None, status_code=200):
        self._data = data or {}
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP {self.status_code}")


def post(*a, **k):
    # default: return empty payload
    return _Resp()


def get(*a, **k):
    return _Resp()
