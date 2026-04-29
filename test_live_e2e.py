#!/usr/bin/env python3
"""S53 Live E2E Test — 直接 call bot internal handler"""
import os, sys, json, time
from dotenv import load_dotenv
load_dotenv()

from router import route
from meta_router import should_distill, log_distill_decision

TEST_CASES = [
    # Round 1: 基本功能
    {"id": 1, "input": "-45 午餐", "expected_tool": "log_expense", "round": "基本功能"},
    {"id": 2, "input": "sophia 幾時上堂", "expected_tool": "find_student", "round": "基本功能"},
    {"id": 3, "input": "頭先嗰筆改做 50", "expected_tool": "correct_last_entry", "round": "基本功能"},
    # Round 2: Confidence Gating
    {"id": 4, "input": "今天食咗咩", "expected_tool": "chat_or_clarify", "round": "Confidence Gating"},
    {"id": 5, "input": "你覺得今日天氣點", "expected_tool": "chat", "round": "Confidence Gating"},
    # Round 3: correct_last_entry
    {"id": 7, "input": "-88 晚餐", "expected_tool": "log_expense", "round": "correct_last_entry"},
    {"id": 8, "input": "上一筆改做 120", "expected_tool": "correct_last_entry", "round": "correct_last_entry"},
    {"id": 9, "input": "啱啱嗰個改返大家樂", "expected_tool": "correct_last_entry", "round": "correct_last_entry"},
]

results = []
for case in TEST_CASES:
    print(f"\n--- Case {case['id']}: {case['input']} ---")
    try:
        res = route(case['input'])
        # route may return different shapes
        tool = res.get('tool') or res.get('action') or res.get('assistant')
        confidence = res.get('confidence', 'N/A')
        # 判斷 PASS/FAIL
        expected = case['expected_tool']
        if expected == "chat_or_clarify":
            passed = (tool in [None, 'chat', 'clarify']) or (isinstance(confidence, (int, float)) and confidence < 0.8)
        else:
            passed = (tool == expected)
        status = "PASS ✅" if passed else "FAIL ❌"
        print(f"  Expected: {expected}")
        print(f"  Actual: tool={tool}, confidence={confidence}")
        print(f"  {status}")
        results.append({"id": case["id"], "status": status, "tool": tool, "confidence": confidence})

        # Meta-Router check for correct_last_entry
        if tool == "correct_last_entry" or (isinstance(res, dict) and res.get('tool') == 'correct_last_entry'):
            distill = should_distill([], res)
            print(f"  Meta-Router: {distill}")
            try:
                log_distill_decision(distill, 1)
            except Exception as e:
                print(f"  log_distill_decision error: {e}")
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"id": case["id"], "status": "ERROR ❌", "error": str(e)})

print("\n\n=== SUMMARY ===")
passed = sum(1 for r in results if "PASS" in r.get("status", ""))
print(f"Total: {len(results)}, Passed: {passed}, Failed: {len(results) - passed}")
for r in results:
    print(f"  Case {r['id']}: {r['status']}")

print("\n=== DISTILL LOG (last 5 entries) ===")
log_path = os.path.expanduser("~/jarvis-v0/logs/distill.log")
if os.path.exists(log_path):
    with open(log_path, encoding='utf-8') as f:
        lines = f.readlines()
    for line in lines[-5:]:
        print(f"  {line.strip()}")
else:
    print("  distill.log not found")
