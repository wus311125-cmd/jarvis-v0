#!/usr/bin/env python3
"""Tests for distill.log read-back loop in router.py (functions only).

This script manipulates ~/jarvis-v0/logs/distill.log (backed up) and few_shots.json
to validate read_recent_distill, distill_to_few_shots, merge_few_shots, build_few_shot_prompt.
"""
import json, os, shutil
from pathlib import Path
from collections import deque

HERE = Path(__file__).parent
LOGS = HERE / 'logs'
DISTILL = LOGS / 'distill.log'
FEW = HERE / 'few_shots.json'

import sys
sys.path.insert(0, str(HERE))
import types
if 'httpx' not in sys.modules:
    sys.modules['httpx'] = types.SimpleNamespace(post=lambda *a, **k: None)

from router import read_recent_distill, distill_to_few_shots, load_static_few_shots, merge_few_shots, build_few_shot_prompt

def backup():
    if DISTILL.exists():
        shutil.copy2(DISTILL, DISTILL.with_suffix('.log.bak'))

def restore():
    bak = DISTILL.with_suffix('.log.bak')
    if bak.exists():
        shutil.move(str(bak), str(DISTILL))

def write_distill(lines):
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(DISTILL, 'w', encoding='utf-8') as f:
        for l in lines:
            f.write(json.dumps(l, ensure_ascii=False) + '\n')

def ac1_empty():
    print('AC-1: distill.log empty -> fallback')
    write_distill([])
    entries = read_recent_distill(10)
    assert entries == [], f'Expected empty list, got {entries}'
    print('✅ AC-1 PASS')

def ac2_nonempty():
    print('AC-2: distill.log has entries -> dynamic shots present')
    lines = []
    for i in range(12):
        lines.append({'input': f'示例 {i}', 'tool': 'log_expense' if i%2==0 else 'find_student', 'confidence': 0.8})
    write_distill(lines)
    entries = read_recent_distill(10)
    dyn = distill_to_few_shots(entries)
    assert len(dyn) > 0, 'Expected dynamic few-shots > 0'
    print('✅ AC-2 PASS, dynamic count =', len(dyn))

def ac3_dedupe():
    print('AC-3: dedupe repeated inputs')
    lines = [{'input': '重複', 'tool': 'log_expense', 'confidence': 0.9} for _ in range(3)]
    write_distill(lines)
    entries = read_recent_distill(10)
    dyn = distill_to_few_shots(entries)
    assert len(dyn) == 1, f'Expected 1 deduped entry, got {len(dyn)}'
    print('✅ AC-3 PASS')

def ac4_budget():
    print('AC-4: budget cap static 10 + dynamic cap -> total <= 20')
    # write static few_shots.json with 10 items
    static = [{'input': f'stat{i}', 'tool': 'log_expense', 'confidence': 0.95} for i in range(10)]
    with open(FEW, 'w', encoding='utf-8') as f:
        json.dump(static, f, ensure_ascii=False)
    # write 15 dynamic entries
    lines = [{'input': f'dyn{i}', 'tool': 'find_student', 'confidence': 0.7} for i in range(15)]
    write_distill(lines)
    entries = read_recent_distill(20)
    dyn = distill_to_few_shots(entries)
    merged = merge_few_shots(static, dyn, budget=20)
    assert len(merged) <= 20, f'Expected merged <=20, got {len(merged)}'
    # cleanup few_shots.json
    try:
        FEW.unlink()
    except Exception:
        pass
    print('✅ AC-4 PASS, merged count =', len(merged))

if __name__ == '__main__':
    backup()
    try:
        ac1_empty()
        ac2_nonempty()
        ac3_dedupe()
        ac4_budget()
    finally:
        restore()
    print('ALL distill read-back AC tests completed')
