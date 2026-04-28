import os
import json
import sqlite3
import requests
from jarvis.history import save_message, get_recent

SYSTEM_PROMPT = """
你係 Jarvis，Hopan 嘅個人 AI 助手。
- 用廣東話（香港口語）回覆，technical term 用英文
- 簡潔、直接、有用
- 你識 Hopan 係結他老師 + indie developer
- 唔好用 emoji spam，適量就好
- 如果唔識答，老實講
- 你有記憶：可以參考之前嘅對話
"""

def chat_reply(text, db_path="jarvis.db"):
    db_conn = sqlite3.connect(db_path)
    try:
        history = get_recent(db_conn, limit=20)
    except Exception:
        history = []

    messages = []
    messages.append({'role': 'system', 'content': SYSTEM_PROMPT})
    for m in history:
        messages.append({'role': m['role'], 'content': m['content']})
    messages.append({'role': 'user', 'content': text})

    api_key = os.getenv('OPENROUTER_API_KEY')
    model = os.getenv('CHAT_MODEL', 'meta-llama/llama-4-scout')
    if not api_key:
        # fallback reply
        reply = "我而家答唔到，缺少 OPENROUTER_API_KEY。"
        try:
            save_message(db_conn, 'user', text)
            save_message(db_conn, 'assistant', reply)
        except Exception:
            pass
        return reply

    endpoint = 'https://openrouter.ai/api/v1/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': 512,
        'temperature': 0.6
    }

    try:
        r = requests.post(endpoint, headers=headers, data=json.dumps(payload), timeout=15)
        r.raise_for_status()
        data = r.json()
        # openrouter response path: data['choices'][0]['message']['content'] (or similar)
        reply = None
        if 'choices' in data and len(data['choices'])>0:
            msg = data['choices'][0].get('message') or data['choices'][0]
            reply = msg.get('content') if isinstance(msg, dict) else str(msg)
        if not reply:
            reply = data.get('message') or '我唔清楚點回覆'

    except Exception:
        reply = '我而家答唔到，稍後再試。'

    # save history
    try:
        save_message(db_conn, 'user', text)
        save_message(db_conn, 'assistant', reply)
    except Exception:
        pass

    return reply
