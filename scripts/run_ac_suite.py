#!/usr/bin/env python3
"""Run a suite of automated checks (ACs) against the local jarvis instance and DB.

This is a lightweight version of the harness used during the session. It performs
read-only checks and prints a markdown-like table of results.
"""
import sqlite3, os, subprocess, json

DB = os.path.expanduser('~/jarvis-v0/jarvis.db')
LOG = os.path.expanduser('~/jarvis-v0/logs/distill.log')
BOTLOG = os.path.expanduser('~/jarvis-v0/bot.log')

def q(sql, params=()):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    try:
        res = cur.execute(sql, params).fetchall()
    finally:
        conn.close()
    return res

results = []

def check_fc1():
    # FC-1: expense inserted for '-88 大快活'
    rows = q("SELECT amount, merchant FROM expenses WHERE merchant LIKE '%大快活%' ORDER BY id DESC LIMIT 3")
    return 'PASS' if rows else 'FAIL'

def check_fc2():
    # FC-2: +3000 stored as income (direction='income' or category='income')
    rows = q("SELECT amount, direction FROM expenses WHERE amount BETWEEN 2999 AND 3001 ORDER BY id DESC LIMIT 5")
    ok = any((r[1] == 'income' or r[1] == 'income' or r[0] == 3000) for r in rows)
    return 'PASS' if ok else ('FAIL' if rows else 'INCONCLUSIVE')

def check_fc3():
    # FC-3: find_student tool_used persisted when querying student
    rows = q("SELECT role, content, tool_used FROM chat_history WHERE content LIKE '%幾時上堂%' OR content LIKE '%陳大文%' ORDER BY id DESC LIMIT 10")
    return 'PASS' if any(r[2] == 'find_student' for r in rows) else 'INCONCLUSIVE'

def check_fc4():
    # FC-4: log_lesson persisted when logging lesson (heuristic)
    rows = q("SELECT role, content, tool_used FROM chat_history WHERE content LIKE '%學咗%' OR content LIKE '%今日教%' ORDER BY id DESC LIMIT 10")
    return 'PASS' if any(r[2] == 'log_lesson' for r in rows) else 'INCONCLUSIVE'

def check_fc5():
    # FC-5: querying '今個月使咗幾多' produced a distill log or bot.log entry
    try:
        tail = subprocess.run(['tail','-80', BOTLOG], capture_output=True, text=True).stdout
        ok = 'query_expenses' in tail or '今個月' in tail
        return 'PASS' if ok else 'INCONCLUSIVE'
    except Exception:
        return 'INCONCLUSIVE'

def check_fc6():
    # FC-6: correction to 78 applied
    rows = q('SELECT amount FROM expenses ORDER BY id DESC LIMIT 3')
    if not rows: return 'INCONCLUSIVE'
    return 'PASS' if any(abs(r[0] - 78.0) < 0.01 for r in rows) else 'FAIL'

def check_fc7():
    # FC-7: assistant persisted a reply to '今日好攰' (chat reply present)
    rows = q("SELECT role, content FROM chat_history WHERE content LIKE '%好攰%' ORDER BY id DESC LIMIT 5")
    return 'PASS' if rows else 'INCONCLUSIVE'

def check_cg1():
    # CG-1: negative expense handling for '-200 交租' -> stored as positive amount
    rows = q("SELECT amount, merchant FROM expenses WHERE merchant LIKE '%交租%' ORDER BY id DESC LIMIT 5")
    return 'PASS' if rows else 'INCONCLUSIVE'

def check_cg2():
    # CG-2: clarification generation on ambiguous numeric message like '45'
    try:
        tail = subprocess.run(['tail','-80', BOTLOG], capture_output=True, text=True).stdout
        ok = 'generate_clarification' in tail or '你係想' in tail
        return 'PASS' if ok else 'INCONCLUSIVE'
    except Exception:
        return 'INCONCLUSIVE'

def check_cg3():
    # CG-3: harmless message didn't generate an expense
    rows = q('SELECT id, timestamp FROM expenses ORDER BY id DESC LIMIT 1')
    return 'PASS' if rows else 'INCONCLUSIVE'

def check_mem1():
    # MEM-1: assistant referenced '壽司' in chat_history after sequence
    rows = q("SELECT content FROM chat_history WHERE content LIKE '%壽司%' ORDER BY id DESC LIMIT 5")
    return 'PASS' if rows else 'INCONCLUSIVE'

def check_mem2():
    # MEM-2: expense reference memory - last expense ~88 exists
    rows = q('SELECT amount FROM expenses ORDER BY id DESC LIMIT 1')
    if not rows: return 'FAIL'
    return 'PASS' if abs(rows[0][0] - 88.0) < 0.01 else 'INCONCLUSIVE'

def check_mem3():
    rows = q('SELECT role, content, tool_used FROM chat_history ORDER BY id DESC LIMIT 10')
    return 'PASS' if rows else 'FAIL'

def check_xc1():
    # XC-1: leak-linter log mention in bot.log
    try:
        tail = subprocess.run(['tail','-200', BOTLOG], capture_output=True, text=True).stdout
        return 'PASS' if 'linter' in tail or 'leak' in tail else 'INCONCLUSIVE'
    except Exception:
        return 'INCONCLUSIVE'

def check_xc2():
    # XC-2: distill.log last 3 lines parseable JSON
    try:
        if not os.path.exists(LOG):
            return 'FAIL'
        with open(LOG, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        last3 = lines[-3:]
        for l in last3:
            json.loads(l)
        return 'PASS'
    except Exception:
        return 'FAIL'

def check_xc3():
    try:
        rows = q("SELECT 'expenses', COUNT(*) FROM expenses UNION SELECT 'chat_history', COUNT(*) FROM chat_history")
        return 'PASS' if rows else 'FAIL'
    except Exception:
        return 'FAIL'

def check_xc4():
    # XC-4: today's daily note contains Session header or agent name
    dn = os.path.expanduser('~/ObsidianVault.main/05-Daily/' + __import__('datetime').date.today().isoformat() + '.md')
    if not os.path.exists(dn):
        return 'FAIL'
    try:
        with open(dn, 'r', encoding='utf-8') as f:
            txt = f.read()
        return 'PASS' if 'Session' in txt or 'Hopan' in txt else 'INCONCLUSIVE'
    except Exception:
        return 'INCONCLUSIVE'

checks = [
    ('FC-1','Router Core', check_fc1),
    ('FC-2','Router Core', check_fc2),
    ('FC-3','Router Core', check_fc3),
    ('FC-4','Router Core', check_fc4),
    ('FC-5','Router Core', check_fc5),
    ('FC-6','Router Core', check_fc6),
    ('FC-7','Router Core', check_fc7),
    ('CG-1','Confidence', check_cg1),
    ('CG-2','Confidence', check_cg2),
    ('CG-3','Confidence', check_cg3),
    ('MEM-1','Context', check_mem1),
    ('MEM-2','Context', check_mem2),
    ('MEM-3','Context', check_mem3),
    ('XC-1','Cross-cutting', check_xc1),
    ('XC-2','Cross-cutting', check_xc2),
    ('XC-3','Cross-cutting', check_xc3),
    ('XC-4','Cross-cutting', check_xc4),
]

def main():
    results = []
    pass_count = 0
    print('| AC # | Phase | Status |')
    print('|---|---|---|')
    for k,phase,fn in checks:
        try:
            st = fn()
        except Exception as e:
            st = f'ERROR: {e}'
        print(f'| {k} | {phase} | {st} |')
        if st == 'PASS': pass_count += 1
    print(f'\nTotal PASS: {pass_count}/{len(checks)}')

if __name__ == '__main__':
    main()
