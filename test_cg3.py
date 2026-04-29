#!/usr/bin/env python3
"""CG-3 local AC verification — threshold logic only.

This script manipulates chat_history in jarvis.db (clears and inserts test rows)
to validate detect_mode() and adjust_threshold() behavior.
"""
import sqlite3
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from router import detect_mode, adjust_threshold

DB_PATH = HERE / "jarvis.db"


def setup_chat_history(rows: list[dict]):
    """Clear chat_history then insert test rows.
    rows: list of dicts with keys: role, content, tool_used
    """
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    # keep schema, clear data
    c.execute("DELETE FROM chat_history")
    for r in rows:
        c.execute(
            "INSERT INTO chat_history (role, content, tool_used, created_at) VALUES (?, ?, ?, datetime('now'))",
            (r.get('role', 'user'), r.get('content', ''), r.get('tool_used')),
        )
    conn.commit()
    conn.close()


def test_ac1_expense_mode():
    """AC-1: expense mode + 記帳語句 → threshold 0.7"""
    setup_chat_history([
        {"role": "assistant", "content": "記咗 45 蚊", "tool_used": "log_expense"},
        {"role": "assistant", "content": "記咗 120 蚊", "tool_used": "log_expense"},
        {"role": "assistant", "content": "記咗 88 蚊", "tool_used": "log_expense"},
    ])
    mode = detect_mode([], window=5)
    threshold = adjust_threshold(0.8, mode, "log_expense")
    assert mode == "expense", f"Expected 'expense', got '{mode}'"
    assert abs(threshold - 0.7) < 0.01, f"Expected 0.7, got {threshold}"
    print("✅ AC-1 PASS: expense mode → threshold 0.7")


def test_ac2_chat_mode():
    """AC-2: chat mode + tool present → threshold 0.9"""
    setup_chat_history([
        {"role": "assistant", "content": "今日天氣幾好", "tool_used": None},
        {"role": "assistant", "content": "係呀，出去行下", "tool_used": None},
        {"role": "assistant", "content": "你食咗飯未", "tool_used": None},
    ])
    mode = detect_mode([], window=5)
    threshold = adjust_threshold(0.8, mode, "log_expense")
    assert mode == "chat", f"Expected 'chat', got '{mode}'"
    assert abs(threshold - 0.9) < 0.01, f"Expected 0.9, got {threshold}"
    print("✅ AC-2 PASS: chat mode + tool present → threshold 0.9")


def test_ac3_student_mode():
    """AC-3: student mode → threshold 0.7"""
    setup_chat_history([
        {"role": "assistant", "content": "搵到陳大文", "tool_used": "find_student"},
        {"role": "assistant", "content": "搵到李小明", "tool_used": "find_student"},
    ])
    mode = detect_mode([], window=5)
    threshold = adjust_threshold(0.8, mode, "find_student")
    assert mode == "student", f"Expected 'student', got '{mode}'"
    assert abs(threshold - 0.7) < 0.01, f"Expected 0.7, got {threshold}"
    print("✅ AC-3 PASS: student mode → threshold 0.7")


def test_ac4_mixed_mode():
    """AC-4: mixed mode → threshold 0.8（static）"""
    setup_chat_history([
        {"role": "assistant", "content": "記咗 45 蚊", "tool_used": "log_expense"},
        {"role": "assistant", "content": "今日天氣幾好", "tool_used": None},
        {"role": "assistant", "content": "記咗 120 蚊", "tool_used": "log_expense"},
        {"role": "assistant", "content": "你食咗飯未", "tool_used": None},
        {"role": "assistant", "content": "搵到陳大文", "tool_used": "find_student"},
    ])
    mode = detect_mode([], window=5)
    threshold = adjust_threshold(0.8, mode, "log_expense")
    assert mode == "mixed", f"Expected 'mixed', got '{mode}'"
    assert abs(threshold - 0.8) < 0.01, f"Expected 0.8, got {threshold}"
    print("✅ AC-4 PASS: mixed mode → threshold 0.8 (static)")


def test_ac5_correction_mode():
    """AC-5: correction 後 → threshold 0.85"""
    setup_chat_history([
        {"role": "assistant", "content": "記咗 45 蚊", "tool_used": "log_expense"},
        {"role": "assistant", "content": "記咗 120 蚊", "tool_used": "log_expense"},
        {"role": "assistant", "content": "改咗做 78", "tool_used": "correct_last_entry"},
    ])
    mode = detect_mode([], window=5)
    threshold = adjust_threshold(0.8, mode, "log_expense")
    assert mode == "correction", f"Expected 'correction', got '{mode}'"
    assert abs(threshold - 0.85) < 0.01, f"Expected 0.85, got {threshold}"
    print("✅ AC-5 PASS: correction mode → threshold 0.85")


if __name__ == "__main__":
    print("=" * 50)
    print("CG-3 Memory-informed Gating — 5 AC Test")
    print("=" * 50)
    tests = [test_ac1_expense_mode, test_ac2_chat_mode, test_ac3_student_mode, test_ac4_mixed_mode, test_ac5_correction_mode]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {test.__name__} ERROR: {e}")
            failed += 1
    print("=" * 50)
    print(f"Results: {passed}/5 PASS, {failed}/5 FAIL")
    if failed == 0:
        print("🎉 全部 PASS！可以上 TG 實測。")
    else:
        print("⚠️ 有 FAIL，修正後再跑。")
