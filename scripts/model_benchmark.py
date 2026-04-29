#!/usr/bin/env python3
import os
import json
import time
import httpx

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = [
    # Original list
    "google/gemini-2.0-flash-001",
    "google/gemini-2.5-flash-preview",
    "deepseek/deepseek-chat-v3-0324",
    "deepseek/deepseek-v3-0324",
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1-nano",
    "anthropic/claude-3.5-haiku",
    "openai/gpt-4.1",
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-pro-preview",
    "meta-llama/llama-4-scout",
    "meta-llama/llama-4-maverick",
    "qwen/qwen3-235b-a22b",
    "mistralai/mistral-medium-3",

    # === 隱世平價 ===
    "microsoft/phi-4",
    "microsoft/mai-ds-r1",
    "cohere/command-r-plus-08-2024",
    "cohere/command-a",

    # === DeepSeek 系列 ===
    "deepseek/deepseek-r1",
    "deepseek/deepseek-r1-0528",
    "deepseek/deepseek-chat-v3-0324:free",

    # === Google 系列 ===
    "google/gemini-2.5-flash-preview:thinking",
    "google/gemma-3-27b",

    # === Meta Llama 系列 ===
    "meta-llama/llama-3.3-70b",
    "meta-llama/llama-4-maverick:free",

    # === 其他隱世 ===
    "nvidia/llama-3.1-nemotron-70b",
    "perplexity/sonar-pro",
    "amazon/nova-pro-v1",
    "mistralai/mistral-small-3.1-24b",
    "mistralai/codestral-mamba",
    "qwen/qwen3-30b-a3b",
    "qwen/qwen3-32b",

    # === 推理特化 ===
    "openai/o4-mini",
    "anthropic/claude-sonnet-4",
    "qwen/qwq-32b",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_student",
            "description": "查詢學生資料同上堂時間",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "學生名"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "correct_last_entry",
            "description": "修改上一筆記錄。field=要改嘅欄位(amount/merchant/category)，new_value=新值",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "description": "要改嘅欄位"},
                    "new_value": {"type": "string", "description": "新值"}
                },
                "required": ["field", "new_value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_next_lesson",
            "description": "安排學生下次上堂時間。需要學生名+日期+時間",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_name": {"type": "string"},
                    "date": {"type": "string"},
                    "time": {"type": "string"}
                },
                "required": ["student_name", "date", "time"]
            }
        }
    }
]

TEST_CASES = [
    {
        "id": "easy_find",
        "input": "sophia 幾時上堂",
        "expect_tool": "find_student",
        "expect_args": {"name": "sophia"},
        "difficulty": "easy",
    },
    {
        "id": "easy_schedule",
        "input": "下個禮拜三 4pm sophia",
        "expect_tool": "schedule_next_lesson",
        "expect_args": {"student_name": "sophia", "date": "下個禮拜三", "time": "16:00"},
        "difficulty": "easy",
    },
    {
        "id": "medium_correct",
        "input": "頭先嗰筆改做 78",
        "expect_tool": "correct_last_entry",
        "expect_args": {"field": "amount", "new_value": "78"},
        "difficulty": "medium",
    },
    {
        "id": "hard_ambiguous",
        "input": "sophia 學到邊",
        "expect_tool": "find_student",
        "expect_args": {"name": "sophia"},
        "difficulty": "hard",
    },
    {
        "id": "hard_correction",
        "input": "唔係，我想查佢幾時上堂",
        "expect_tool": "find_student",
        "expect_args": {},
        "difficulty": "hard",
    },
]

SYSTEM_PROMPT = (
    """你係 Jarvis，Hopan 嘅私人助手。用廣東話回覆。\n"
    "你有以下工具可以用。根據用戶意圖選擇正確嘅工具。\n"
    "重要：『幾時上堂』『學到邊』= 查詢(find_student)，唔係排堂。\n"
    "只有明確提供『日期+時間+學生名』先用 schedule_next_lesson。\n"
    "『頭先嗰筆改做 X』= correct_last_entry，數字=amount，文字=merchant。"""
)


def safe_json_dumps(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


def test_model(model_name):
    results = {"model": model_name, "cases": [], "error": None}
    if not OPENROUTER_API_KEY:
        results["error"] = "NO_API_KEY"
        print("  ❌ No OPENROUTER_API_KEY in environment")
        return results

    for case in TEST_CASES:
        try:
            start = time.time()
            resp = httpx.post(
                BASE_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": case["input"]},
                    ],
                    "tools": TOOLS,
                    "tool_choice": "auto",
                    "temperature": 0.1,
                    "max_tokens": 200,
                },
                timeout=30.0,
            )
            latency = time.time() - start

            if resp.status_code == 451:
                results["error"] = "BLOCKED_HK (451)"
                print(f"  ❌ {model_name}: BLOCKED IN HK (451)")
                return results
            if resp.status_code == 429:
                results["error"] = "RATE_LIMITED (429)"
                print(f"  ⚠️ {model_name}: RATE LIMITED")
                return results
            if resp.status_code != 200:
                results["error"] = f"HTTP_{resp.status_code}: {resp.text[:200]}"
                print(f"  ❌ {model_name}: HTTP {resp.status_code}")
                return results

            data = resp.json()
            # flexible parsing for function/tool calls
            choice = data.get("choices", [])[0]
            message = choice.get("message", {}) if choice else {}

            tool_calls = []
            # OpenRouter may return tool_calls or function_call
            if isinstance(message, dict):
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    fc = message.get("function_call") or message.get("tool_call")
                    if fc and isinstance(fc, dict):
                        # normalize
                        tool_calls = [
                            {
                                "function": {"name": fc.get("name"), "arguments": fc.get("arguments")}
                            }
                        ]

            has_native_tc = len(tool_calls) > 0
            tool_name = None
            args = {}
            if has_native_tc:
                first = tool_calls[0]
                fn = first.get("function") or {}
                tool_name = fn.get("name")
                raw_args = fn.get("arguments")
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {"raw": raw_args}
                elif isinstance(raw_args, dict):
                    args = raw_args

            assistant_text = ""
            if isinstance(message, dict):
                assistant_text = message.get("content") or ""
            # fallback: sometimes the top-level choice has text
            if not assistant_text:
                assistant_text = choice.get("text") or choice.get("message", {}).get("content", "")

            text_embedded_tc = False
            if assistant_text and ("tool_calls" in assistant_text or any(tc in assistant_text for tc in [c["expect_tool"] for c in TEST_CASES])):
                text_embedded_tc = True

            tool_correct = (tool_name == case["expect_tool"]) if tool_name else False

            case_result = {
                "case_id": case["id"],
                "difficulty": case["difficulty"],
                "native_tool_call": has_native_tc,
                "text_embedded_tc": text_embedded_tc,
                "tool_correct": tool_correct,
                "tool_name": tool_name,
                "args": args,
                "latency_s": round(latency, 2),
                "assistant_text": (assistant_text[:400] if assistant_text else ""),
            }
            results["cases"].append(case_result)
            status = "✅" if tool_correct and has_native_tc else ("⚠️" if text_embedded_tc else "❌")
            print(f"  {status} {case['id']}: native={has_native_tc} correct={tool_correct} tool={tool_name} latency={latency:.1f}s")
            time.sleep(0.5)
        except httpx.TimeoutException:
            results["cases"].append({"case_id": case["id"], "error": "TIMEOUT"})
            print(f"  ❌ {case['id']}: TIMEOUT")
        except Exception as e:
            results["cases"].append({"case_id": case["id"], "error": str(e)})
            print(f"  ❌ {case['id']}: {e}")

    return results


def run_benchmark():
    all_results = []
    for model in MODELS:
        print('\n' + '=' * 60)
        print(f"Testing: {model}")
        print('=' * 60)
        res = test_model(model)
        all_results.append(res)
        if res.get("error") and "BLOCKED" in res["error"]:
            continue
        time.sleep(1)

    # summary
    print('\n' + '=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f"{'Model':<45} {'HK':<6} {'Native TC':<10} {'Correct':<10} {'Avg Latency':<12}")
    print('-' * 85)
    for r in all_results:
        if r.get("error") and "BLOCKED" in r["error"]:
            print(f"{r['model']:<45} {'❌':<6} {'N/A':<10} {'N/A':<10} {'N/A':<12}")
            continue
        if r.get("error"):
            print(f"{r['model']:<45} {'⚠️':<6} {r['error']:<30}")
            continue
        cases = r.get("cases", [])
        native_count = sum(1 for c in cases if c.get("native_tool_call"))
        correct_count = sum(1 for c in cases if c.get("tool_correct"))
        avg_latency = sum(c.get("latency_s", 0) for c in cases) / max(len(cases), 1)
        print(f"{r['model']:<45} {'✅':<6} {native_count}/{len(cases):<8} {correct_count}/{len(cases):<8} {avg_latency:.1f}s")

    outp = os.path.join(os.getcwd(), "scripts", "model_benchmark_results.json")
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\nRaw results saved to {outp}")


if __name__ == "__main__":
    run_benchmark()
