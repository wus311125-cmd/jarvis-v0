import os
import json
import ast
import requests
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from skills import intake

OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
MODEL = os.environ.get('OPENROUTER_MODEL', 'gpt-5-mini')


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "log_expense",
            "description": "記錄一筆支出：當用戶講到買嘢、食飯、花費。常見格式：-金額 描述，例如「-88 大快活」",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "金額（正數）"},
                    "description": {"type": "string", "description": "消費描述"},
                    "vendor": {"type": "string", "description": "商戶名稱（如有）"},
                    "category": {"type": "string", "description": "分類（food/transport/shopping/other）"}
                },
                "required": ["amount", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_income",
            "description": "記錄一筆收入：當用戶講到收款、學費、人工等。常見格式：+金額 描述，例如「+3000 學費」",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "金額（正數）"},
                    "description": {"type": "string", "description": "收入描述"},
                    "source": {"type": "string", "description": "收入來源"}
                },
                "required": ["amount", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_student",
            "description": "查詢學生資料：用戶問某位學生嘅上堂時間、進度、聯絡方法時用",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "學生名（中文或英文）"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_lesson",
            "description": "記錄一堂課內容：當用戶講「幫我記低今日教咗乜」時使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_name": {"type": "string", "description": "學生名"},
                    "content": {"type": "string", "description": "課堂內容"},
                    "date": {"type": "string", "description": "日期（YYYY-MM-DD，預設今日）"}
                },
                "required": ["student_name", "content"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "new_student",
            "description": "新增學生：name 必填，phone/instrument/level optional",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "學生名（必填）"},
                    "phone": {"type": "string", "description": "電話（可選）"},
                    "instrument": {"type": "string", "description": "樂器（可選）"},
                    "level": {"type": "string", "description": "級別（可選）"}
                },
                "required": ["name"],
                "additionalProperties": False
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "list_students",
            "description": "列出所有學生（無參數）",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "schedule_next_lesson",
            "description": "排下次堂：student_name + date + time 必填",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_name": {"type": "string", "description": "學生名（必填）"},
                    "date": {"type": "string", "description": "日期（YYYY-MM-DD，必填）"},
                    "time": {"type": "string", "description": "時間（HH:MM，必填）"}
                },
                "required": ["student_name", "date", "time"],
                "additionalProperties": False
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "query_expenses",
            "description": "查詢支出總額或明細，例如「今個月使咗幾多」",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "description": "時間範圍（today/this_week/this_month/last_month）"},
                    "category": {"type": "string", "description": "分類篩選（可選）"}
                },
                "required": ["period"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "correct_last_entry",
            "description": "修改最近一筆記錄。當用戶講「改做 X」「改為 X」「改返 X」「頭先嗰筆改做 X」等，請呼叫此 tool 並判斷要改嘅欄位與新值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "description": "要改嘅欄位。LLM 請根據用戶講法判斷：若用戶講數字 → field='amount'；講店名或文字 → field='merchant'；講類別 → field='category'；講日期 → field='date'；講備註或文字 → field='note'。"},
                    "new_value": {"type": "string", "description": "新值。根據用戶原話提取：數字請傳 number（例如 78），文字請傳 string（例如 '大家樂'）。"}
                },
                "required": ["field", "new_value"]
            }
        }
    }
    ,
    {
        "type": "function",
        "function": {
            "name": "learn_from_correction",
            "description": "當用戶糾正你嘅理解或 routing 時 call 呢個 tool。記低正確嘅 input -> tool mapping，下次自動用正確嘅 tool。只喺用戶明確表示你做錯咗（例如『唔係』『錯咗』『我係想』）時先 call。",
            "parameters": {
                "type": "object",
                "properties": {
                    "original_input": {"type": "string", "description": "用戶原本講嘅嘢（觸發錯誤 routing 嗰句）"},
                    "wrong_tool": {"type": "string", "description": "你之前錯誤 route 去嘅 tool name"},
                    "correct_tool": {"type": "string", "description": "用戶糾正後應該用嘅 tool name"},
                    "lesson": {"type": "string", "description": "一句話總結學到咩，用廣東話寫（例如：冇日期時間 = 查詢，唔係排堂）"}
                },
                "required": ["original_input", "correct_tool", "lesson"],
                "additionalProperties": False
            }
        }
    }
]


def _load_recent_history(limit: int = 10) -> List[str]:
    out: List[str] = []
    try:
        db = sqlite3.connect(str(intake.DB_PATH))
        cur = db.cursor()
        cur.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        for r in reversed(rows):
            role, content = r
            out.append(f"{role}: {content}")
        db.close()
    except Exception:
        # fallback empty
        return []
    return out


def _resolve_relative_date(text: str) -> str:
    """Convert Chinese relative weekday like '下禮拜三' or '禮拜三' to ISO date YYYY-MM-DD.
    If no match, return original text unchanged.
    """
    if not text or not isinstance(text, str):
        return text
    today = datetime.now().date()
    wd_map = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6,
              '1': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5, '7': 6}
    txt = text.replace('星期', '禮拜').replace('週', '禮拜')
    # next week pattern
    m = re.search(r'下?禮拜\s*([一二三四五六日1-7])', txt)
    if m:
        ch = m.group(1)
        target = wd_map.get(ch)
        if target is not None:
            days_ahead = (target - today.weekday()) % 7
            if '下' in text:
                days_ahead = days_ahead + 7 if days_ahead >= 0 else 7
                if days_ahead == 0:
                    days_ahead = 7
            else:
                if days_ahead == 0:
                    days_ahead = 7
            target_date = today + timedelta(days=days_ahead)
            return target_date.isoformat()
    # fallback: try plain '禮拜X'
    m2 = re.search(r'禮拜\s*([一二三四五六日1-7])', txt)
    if m2:
        ch = m2.group(1)
        target = wd_map.get(ch)
        if target is not None:
            days_ahead = (target - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            target_date = today + timedelta(days=days_ahead)
            return target_date.isoformat()
    return text


def _resolve_time(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    m = re.search(r'(\d{1,2})\s*(?:點|時|:)', text)
    if m:
        hour = int(m.group(1)) % 24
        return f"{hour:02d}:00"
    return text


def _build_system_prompt(recent: List[str], entity_context: str = '') -> str:
    # 大賢者 system prompt — encourage LLM-native routing and tool use
    system = (
        "你係大賢者，Hopan 嘅個人 AI 助手 Jarvis 嘅核心。\n"
        "Hopan 係一個結他老師，有大約 20 個學生，同時用你管理日常記帳。\n\n"
        "你嘅能力（Skills）\n"
        "你有以下 tools 可以用。根據用戶意圖自動判斷用邊個：\n"
        "💰 記帳類：log_expense, log_income, correct_last_entry, query_expenses。當用戶提及金額或收支時使用。\n"
        "🎸 學生管理類：find_student（查詢學生資料）、list_students、log_lesson（記錄今日課堂）、schedule_next_lesson（安排下次堂）、new_student（新增學生）。\n\n"
        "判斷規則：\n"
        "- 如果用戶意圖明確對應某個 tool，直接呼叫該 tool（function calling），唔需要太多額外問題。\n"
        "- 如果資訊不足（例如 schedule 但冇日期），要以清晰問題追問所需欄位，唔好盲 call tool。\n"
        "- 如果用戶講嘅唔 match 任何 tool，就直接用廣東話友善回覆（簡短）。\n"
        "- 當有 conversation memory 時，善用 memory 處理代詞（例如「佢」「嗰個」）。\n"
        "Entity context：系統會注入來自 DB 嘅 entity context（例如某學生存在與否），你應該善用該資訊來判斷工具使用。\n"
        "語言：用廣東話回覆，簡潔、有禮。"
    )
    if entity_context:
        system = system + "\n\n## Entity Context\n" + entity_context
    # append recent history if present (for LLM context awareness)
    history = "\n".join(recent)
    if history:
        system = system + "\n\nRecent conversation history:\n" + history
    # inject few-shot intent examples for LLM guidance
    try:
        fs_path = os.path.join(os.path.dirname(__file__), 'few_shots.json')
        if os.path.exists(fs_path):
            with open(fs_path, 'r', encoding='utf-8') as f:
                import json as _json
                shots = _json.load(f)
            examples = []
            for s in shots:
                examples.append(f'• 「{s.get("input","")}" → {s.get("tool","")}（{s.get("why","")}）')
            if examples:
                system = system + "\n\n【意圖判斷範例（從經驗學到）】\n" + "\n".join(examples)
    except Exception:
        # non-fatal; ignore few-shots if file unreadable
        pass
    # self-learning rules: when user corrects you, record lesson and execute corrected intent
    system = system + "\n\n【自我學習規則】\n- 當用戶以「唔係」「錯咗」「我係想」「唔啱」等字眼糾正你嘅理解，請呼叫 learn_from_correction 工具記低教訓，並同時執行正確嘅工具。\n- 你可以在一次回應中同時呼叫多個 tools（例如 learn_from_correction 然後 find_student）。\n- 回覆格式：簡短確認學到嘅教訓，然後提供正確結果。例如：\n  「明白，已記住：冇日期時間 = 查詢。sophia 下次上堂：2026-05-06 16:00」\n"

    # Guidance to encourage structured function-calling for corrections
    system = system + "\n\n【修正呼叫格式建議】\n- 當你處理用戶嘅糾正（correction），盡量以 function-calling（tool_calls）形式回應，唔好只把 JSON embed 入普通文字。\n- 例如：若用戶講「頭先嗰筆改做 78」，請呼叫 correct_last_entry 並傳入 arguments（嚴格 JSON 字串或 native function_call depending on API）如下：\n  {\n    \"tool_calls\": [\n      {\"function\": {\"name\": \"correct_last_entry\", \"arguments\": \"{\\\"field\\\": \\\"amount\\\", \\\"new_value\\\": 78}\"}}\n    ]\n  }\n- 同時（若唔係單純糾正金額，而係用戶改變意圖），可先呼叫 learn_from_correction 再執行正確工具，例如：learn_from_correction + find_student。\n- 簡短、結構化、用廣東話回覆。\n"

    # (no strong response-format enforcement here — keep few-shots + self-learning rules only)
    return system


def route(text: str, entity_context: str = '', recent: List[str] = None, history: List[Dict[str,str]] = None) -> Dict[str, Any]:
    """Send user text to OpenRouter with function definitions.
    Returns: { 'tool': name | None, 'args': dict | None, 'assistant': str | None }
    If OPENROUTER_API_KEY is not set, use lightweight local heuristics as fallback to enable offline testing.
    """
    if recent is None:
        recent = _load_recent_history(10)
    system = _build_system_prompt(recent)
    messages = [
        {"role": "system", "content": system},
    ]
    # inject conversational memory (history) if provided. Expect history as list of {'role','content'}
    if history and isinstance(history, list):
        for m in history:
            # validate minimal shape
            if isinstance(m, dict) and m.get('role') and m.get('content'):
                messages.append({'role': m.get('role'), 'content': m.get('content')})
    # finally append current user message
    messages.append({"role": "user", "content": text})

    # Local heuristic fallback when no API key (allows offline E2E smoke tests)
    if OPENROUTER_API_KEY is None:
        # Offline fallback: very small heuristic set for local smoke tests only.
        # Keep minimal to avoid divergence from LLM-native routing in production.
        # explicit -amount / +amount
        m = re.match(r'^\s*([+-])(\d+(?:\.\d+)?)\s*(.*)$', text)
        if m:
            sign, amt_s, rest = m.groups()
            amt = float(amt_s)
            if sign == '-':
                return {'tool': 'log_expense', 'args': {'amount': amt, 'description': rest.strip(), 'vendor': ''}, 'assistant': None}
            else:
                return {'tool': 'log_income', 'args': {'amount': amt, 'description': rest.strip(), 'source': ''}, 'assistant': None}
        # basic expense queries
        if '今個月' in text or '本月' in text or '今個 月' in text:
            return {'tool': 'query_expenses', 'args': {'period': 'this_month'}, 'assistant': None}
        # default offline reply
        return {'tool': None, 'args': None, 'assistant': '嗯，收到，我記低。'}

    payload = {
        "model": MODEL,
        "messages": messages,
        # OpenRouter expects the newer 'tools' key (not 'functions')
        "tools": TOOLS,
        # use new key name for tool selection
        "tool_choice": "auto",
        "temperature": 0.0,
    }

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    # Debug logs to help E2E diagnose function-calling issues
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # no-op: remove debug prints in production
    choices = data.get('choices') or []
    if not choices:
        # empty response from model — fallback to no tool
        return {'tool': None, 'args': None, 'assistant': None}
    choice = choices[0]
    msg = choice.get('message', {})

    # New/OpenRouter format: 'tool_calls' array — support multiple tool calls sequentially
    if msg.get('tool_calls'):
        try:
            tcalls = msg['tool_calls']
            parsed_calls = []
            for tc in tcalls:
                tool_name = tc['function']['name']
                tool_args_raw = tc['function'].get('arguments') or '{}'
                try:
                    tool_args = json.loads(tool_args_raw)
                except Exception:
                    # attempt lenient parse using ast.literal_eval for safety
                    try:
                        tool_args = ast.literal_eval(tool_args_raw)
                    except Exception:
                        tool_args = {}
                parsed_calls.append({'tool': tool_name, 'args': tool_args})
            return {'tool_calls': parsed_calls, 'assistant': None}
        except Exception:
            # fallthrough to other parsing strategies
            pass

    # Backwards-compatible fallbacks: 'function_call' or 'tool_call'
    fc = msg.get('function_call') or msg.get('tool_call')
    if fc:
        name = fc.get('name')
        args_raw = fc.get('arguments') or '{}'
        try:
            args = json.loads(args_raw)
        except Exception:
            try:
                args = ast.literal_eval(args_raw)
            except Exception:
                args = {}
        return {'tool': name, 'args': args, 'assistant': None}

    # else assistant content
    assistant_text = msg.get('content')

    # Fallback parser: sometimes the model writes tool_calls JSON into assistant text.
    # Use a robust balanced-brace extractor anchored at the '"tool_calls"' token to
    # tolerate surrounding text or newlines.
    if assistant_text and isinstance(assistant_text, str):
        try:
            idx = assistant_text.find('"tool_calls"')
            if idx != -1:
                # find opening brace before idx
                open_pos = assistant_text.rfind('{', 0, idx)
                if open_pos != -1:
                    # scan forward from open_pos to find matching closing brace, ignoring string contents
                    s = assistant_text
                    i = open_pos
                    brace_count = 0
                    in_str = False
                    escape = False
                    end_pos = None
                    while i < len(s):
                        ch = s[i]
                        if in_str:
                            if escape:
                                escape = False
                            elif ch == '\\':
                                escape = True
                            elif ch == '"':
                                in_str = False
                        else:
                            if ch == '"':
                                in_str = True
                            elif ch == '{':
                                brace_count += 1
                            elif ch == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    end_pos = i
                                    break
                        i += 1
                    if end_pos:
                        raw = assistant_text[open_pos:end_pos+1]
                        parsed = None
                        try:
                            parsed = json.loads(raw)
                        except Exception:
                            try:
                                parsed = ast.literal_eval(raw)
                            except Exception:
                                parsed = None
                        if parsed and isinstance(parsed, dict) and parsed.get('tool_calls'):
                            tcalls = parsed['tool_calls']
                            parsed_calls = []
                            for tc in tcalls:
                                func = tc.get('function') or tc.get('function_call') or tc.get('tool')
                                if not func or not isinstance(func, dict):
                                    continue
                                tool_name = func.get('name')
                                tool_args_raw = func.get('arguments') or func.get('args') or '{}'
                                tool_args = {}
                                if isinstance(tool_args_raw, str):
                                    try:
                                        tool_args = json.loads(tool_args_raw)
                                    except Exception:
                                        try:
                                            tool_args = ast.literal_eval(tool_args_raw)
                                        except Exception:
                                            tool_args = {}
                                elif isinstance(tool_args_raw, dict):
                                    tool_args = tool_args_raw
                                parsed_calls.append({'tool': tool_name, 'args': tool_args})
                            if parsed_calls:
                                return {'tool_calls': parsed_calls, 'assistant': None}
        except Exception:
            # non-fatal; fall back to returning assistant text
            pass

    return {'tool': None, 'args': None, 'assistant': assistant_text}


def execute_tool(tool_name: str, args: dict | None):
    """Dispatch helper to call internal student tools.

    Returns the tool result or an error dict. Designed to be imported and
    used by bot.py dispatch so that student-related handling centralises here.
    """
    if args is None:
        args = {}
    try:
        # support batched tool calls passed as list
        if tool_name == 'batch_calls' and isinstance(args, list):
            results = []
            for call in args:
                t = call.get('tool')
                a = call.get('args') or {}
                results.append({ 'call': call, 'result': execute_tool(t, a) })
            return results

        # find_student
        if tool_name == "find_student":
            from jarvis.student import find_student
            return find_student(args.get("name") or args.get("student_name") or args.get("student", ""))

        # log_expense / record_expense: store an expense record
        if tool_name in ("log_expense", "record_expense"):
            try:
                from skills import expense as _expense
                rec = {
                    'timestamp': datetime.now().isoformat(),
                    'amount': float(args.get('amount', 0)),
                    'currency': args.get('currency', 'HKD'),
                    'category': args.get('category') or None,
                    'merchant': args.get('vendor') or args.get('merchant') or args.get('description',''),
                    'date': args.get('date') or datetime.now().date().isoformat(),
                    'note': args.get('note',''),
                    'source': 'tool',
                }
                rowid = _expense.store_expense(rec)
                return {'ok': True, 'rowid': rowid, 'record': rec}
            except Exception as e:
                return {'error': str(e)}

        # log_income: acknowledge or store as income (mirror of expense store with positive amount)
        if tool_name in ("log_income", "record_income"):
            try:
                from skills import expense as _expense
                rec = {
                    'timestamp': datetime.now().isoformat(),
                    'amount': float(args.get('amount', 0)),
                    'currency': args.get('currency', 'HKD'),
                    'category': args.get('category') or 'income',
                    'merchant': args.get('source') or args.get('description',''),
                    'date': args.get('date') or datetime.now().date().isoformat(),
                    'note': args.get('note',''),
                    'source': 'tool_income',
                }
                # store as negative to keep same table semantics? store_expense expects expense rows.
                # We'll store positive amount but tag category for income.
                rowid = _expense.store_expense(rec)
                return {'ok': True, 'rowid': rowid, 'record': rec}
            except Exception as e:
                return {'error': str(e)}

        # query_expenses: simple aggregator for period
        if tool_name == 'query_expenses':
            try:
                from skills import expense as _expense
                period = args.get('period','today')
                conn = sqlite3.connect(str(_expense.DB_PATH))
                cur = conn.cursor()
                if period in ('today','this_day'):
                    d = datetime.now().date().isoformat()
                    rows = cur.execute("SELECT amount FROM expenses WHERE date=?", (d,)).fetchall()
                elif period in ('this_month', 'month'):
                    today = datetime.now().date()
                    month_start = today.replace(day=1).isoformat()
                    rows = cur.execute("SELECT amount FROM expenses WHERE date>=?", (month_start,)).fetchall()
                else:
                    # fallback: return all
                    rows = cur.execute("SELECT amount FROM expenses").fetchall()
                total = sum([r[0] for r in rows]) if rows else 0
                conn.close()
                return {'period': period, 'total': total, 'count': len(rows)}
            except Exception as e:
                return {'error': str(e)}

        # correct_last_entry: naive correction of last expense row
        if tool_name == 'correct_last_entry':
            try:
                field = args.get('field')
                new_value = args.get('new_value')
                from skills import expense as _expense
                # whitelist allowed updatable columns to avoid SQL injection / invalid columns
                allowed = {'amount', 'merchant', 'category', 'date', 'note'}
                if not field or field not in allowed:
                    return {'error': f'invalid field: {field}. allowed={sorted(list(allowed))}'}

                conn = sqlite3.connect(str(_expense.DB_PATH))
                cur = conn.cursor()
                cur.execute('SELECT id FROM expenses ORDER BY id DESC LIMIT 1')
                row = cur.fetchone()
                if not row:
                    conn.close()
                    return {'error': 'no expense rows'}
                eid = row[0]

                # parameterize value; column name inserted from whitelist only
                if field == 'amount':
                    val = float(new_value)
                else:
                    val = str(new_value)

                sql = f'UPDATE expenses SET {field}=? WHERE id=?'
                cur.execute(sql, (val, eid))
                conn.commit()
                conn.close()
                return {'ok': True, 'id': eid, 'field': field, 'new_value': val}
            except Exception as e:
                return {'error': str(e)}

        # new_student: expects name required, other fields optional
        if tool_name == "new_student":
            from jarvis.student import new_student
            name = args.get("name") or args.get("student_name") or args.get("student")
            if not name:
                raise ValueError("name is required for new_student")
            # sanitize inputs
            phone = args.get("phone")
            if phone:
                import re
                phone = re.sub(r'\D', '', str(phone))
            instrument = args.get("instrument")
            if instrument and isinstance(instrument, str):
                instrument = instrument.strip().title()

            res = new_student(
                name,
                phone=phone,
                price=args.get("price"),
                term=args.get("term"),
                day=args.get("day"),
                time=args.get("time"),
                level=args.get("level"),
                instrument=instrument,
            )
            # If Notion rejects payload (bad request), try retry without instrument/phone
            try:
                if isinstance(res, dict) and res.get('error') and ('400' in res.get('error') or 'Bad Request' in res.get('error')):
                    # retry minimal create without optional selects
                    res2 = new_student(name)
                    return res2
            except Exception:
                pass
            return res

        # list_students: query Notion students DB and return list of names/ids
        if tool_name == "list_students":
            from jarvis import student
            url = f'https://api.notion.com/v1/databases/{student.STUDENTS_DB_ID}/query'
            body = {"page_size": 50}
            data = student._req('POST', url, json=body)
            results = data.get('results', [])
            out = []
            for p in results:
                props = p.get('properties', {})
                title_prop = props.get('NAME', {})
                title_text = ''
                if title_prop.get('title'):
                    title_text = ''.join([t.get('plain_text','') for t in title_prop.get('title',[])])
                out.append({'id': p.get('id'), 'name': title_text})
            return out

        # log_lesson: forward to student.log_lesson
        if tool_name == "log_lesson":
            from jarvis.student import log_lesson
            name = args.get('student_name') or args.get('name') or args.get('student')
            content = args.get('content') or args.get('notes') or args.get('description')
            return log_lesson(name or '', content)

        # schedule_next_lesson -> student.schedule_next
        if tool_name == "schedule_next_lesson":
            from jarvis.student import schedule_next
            name = args.get('student_name') or args.get('name') or args.get('student')
            date = args.get('date')
            time = args.get('time') or args.get('time_str') or None
            # normalize relative chinese dates and times to ISO
            if date and isinstance(date, str):
                date = _resolve_relative_date(date)
            if time and isinstance(time, str):
                time = _resolve_time(time)
            if not name or not date:
                raise ValueError('student_name and date are required for scheduling')
            return schedule_next(name, date, time)

        raise ValueError(f"Unknown tool: {tool_name}")
    except Exception as e:
        return {"error": str(e)}
