#!/usr/bin/env python3
"""Quick test for direction logic and sqlite column verification.
Run from repo root: python3 scripts/test_direction.py
"""
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from jarvis import expense, bot


class MockLLM:
    def classify(self, text, prompt=None):
        # naive rules to simulate LLM
        t = text.lower()
        if t.startswith('-'):
            return {'amount': float(''.join([c for c in t if c.isdigit()]) or 0), 'description': t, 'direction': 'expense'}
        if any(k in t for k in ['收到', '人工', '薪', 'paid', 'transfer in', '學費']):
            amt = [int(s) for s in t.split() if s.isdigit()]
            return {'amount': amt[0] if amt else None, 'description': t, 'direction': 'income'}
        # fallback expense
        amt = [int(s) for s in t.split() if s.isdigit()]
        return {'amount': amt[0] if amt else None, 'description': t, 'direction': 'expense'}


DB = 'test_jarvis.db'
if os.path.exists(DB):
    os.remove(DB)

conn = sqlite3.connect(DB)
cur = conn.cursor()

# create base table (simulate existing schema)
cur.execute('''CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL,
    description TEXT
);
''')
conn.commit()

# apply migration: add direction column
try:
    cur.execute("ALTER TABLE expenses ADD COLUMN direction TEXT DEFAULT 'expense';")
except Exception:
    pass
conn.commit()

llm = MockLLM()

tests = [
    ('-45 大快活', None),
    ('45 食飯', llm),
    ('收到 3000 人工', llm),
    ('學費 800 陳大文', llm),
]

for text, client in tests:
    parsed = expense.parse(text, llm_client=client)
    amount = parsed.get('amount')
    desc = parsed.get('description')
    direction = parsed.get('direction')
    expense.store_expense(conn, amount, desc, direction)
    print('Stored:', bot.format_reply(amount, desc, direction))

print('\nDB rows:')
for row in cur.execute('SELECT id, amount, description, direction FROM expenses'):
    print(row)

conn.close()
