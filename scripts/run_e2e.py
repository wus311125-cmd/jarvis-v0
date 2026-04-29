#!/usr/bin/env python3
"""Run local E2E smoke tests against on_text handler.

Sets minimal env defaults and stubs missing libs to allow offline run.
"""
import os
import sys
import asyncio
from pathlib import Path

# ensure project root is on sys.path so `import bot` works
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# minimal env defaults (override in shell if you want real bot)
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'fake')
os.environ.setdefault('ALLOWED_USER_ID', str(os.getuid() if hasattr(os, 'getuid') else 1000))
os.environ.setdefault('OBSIDIAN_VAULT', '/Users/nhp/ObsidianVault.main')

# stub optional modules if not installed
try:
    import dotenv
except Exception:
    class _dot: 
        def load_dotenv(self,*a,**k): return None
    sys.modules['dotenv'] = _dot()

try:
    import requests
except Exception:
    import types
    r = types.SimpleNamespace()
    class Resp:
        status_code = 200
        def json(self): return {}
        def raise_for_status(self): pass
    r.post = lambda *a, **k: Resp()
    sys.modules['requests'] = r

try:
    import telegram
    import telegram.ext
except Exception:
    import types
    telegram = types.ModuleType('telegram')
    class Update: pass
    telegram.Update = Update
    ext = types.ModuleType('telegram.ext')
    class ApplicationBuilder:
        def __init__(self,*a,**k): pass
        def token(self,t): return self
        def build(self): return None
    class CommandHandler:
        def __init__(self,*a,**k): pass
    class MessageHandler:
        def __init__(self,*a,**k): pass
    class filters:
        TEXT=None; COMMAND=None
    class ContextTypes:
        # minimal placeholder used by bot import
        pass
    ext.ApplicationBuilder=ApplicationBuilder
    ext.CommandHandler=CommandHandler
    ext.MessageHandler=MessageHandler
    ext.filters=filters
    ext.ContextTypes=ContextTypes
    sys.modules['telegram']=telegram
    sys.modules['telegram.ext']=ext

# import bot handler
from bot import on_text

# ensure DB initialized
try:
    import skills.intake as intake
    intake.init_db()
except Exception:
    pass

class MockUser:
    def __init__(self,id): self.id=id
class MockMessage:
    def __init__(self,text): self.text=text
    async def reply_chat_action(self,a): pass
    async def reply_text(self,txt): print('BOT REPLY:', txt)
class MockUpdate:
    def __init__(self,text):
        self.effective_user=MockUser(int(os.environ.get('ALLOWED_USER_ID')))
        self.message=MockMessage(text)

def run_case(text):
    u = MockUpdate(text)
    # use asyncio.run to ensure a running event loop on modern Python
    return asyncio.run(on_text(u, None))

cases=['-88 大快活','+3000 陳大文學費','今日好攰','今個月使咗幾多','頭先嗰筆改做 78','陳大文幾時上堂','頭先嗰筆改做 大家樂','78']
for c in cases:
    print('\n=== INPUT ===\n', c)
    try:
        run_case(c)
    except Exception as e:
        print('ERROR:', e)

print('\nE2E run complete')
