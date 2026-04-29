import requests
class _Mod:
    def post(url, headers=None, json=None, timeout=None):
        class R:
            def __init__(self):
                self.status_code=200; self.headers={}; self._json={}
            def raise_for_status(self):
                return
            def json(self):
                return self._json
            @property
            def text(self):
                return ""
        return R()
import types
mod=types.ModuleType("httpx")
mod.post=_Mod.post
import sys
sys.modules["httpx"]=mod
