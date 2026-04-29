import json
import httpx
import os
import time
from pathlib import Path
from typing import List, Dict, Any

DISTILL_TYPES = {
    "recap": {
        "trigger": "用戶修正咗之前嘅操作或判斷",
        "description": "修正蒸餾：從修正中學習，避免下次再錯"
    },
    "compression": {
        "trigger": "對話累積超過 20 條 messages 或者一個 topic 討論完畢",
        "description": "壓縮蒸餾：長對話變精華摘要，保留關鍵 facts"
    },
    "perspective": {
        "trigger": "用戶問緊決策類問題（應唔應該 X？點揀 A 定 B？）",
        "description": "視角蒸餾：用多個角色（教練/投資者/朋友）分析同一件事"
    }
}


def should_distill(conversation: List[Dict[str, str]], last_route_decision: Dict[str, Any] = None) -> Dict[str, Any]:
    """Decide whether to distill the recent conversation and which type.

    conversation: list of {'role':..., 'content':...}
    Returns a dict with keys: should_distill (bool), distill_type (or None), reason, confidence (0-1)
    """
    # Fast-path: recap when user corrected a previous routing
    try:
        if isinstance(last_route_decision, dict) and last_route_decision.get('tool') == 'correct_last_entry':
            return {
                'should_distill': True,
                'distill_type': 'recap',
                'reason': '用戶觸發咗 correct_last_entry，需要 RECAP 蒸餾',
                'confidence': 0.95,
            }
    except Exception:
        pass

    # Fast-path: too short -> no distill
    if not isinstance(conversation, list) or len(conversation) < 5:
        return {
            'should_distill': False,
            'distill_type': None,
            'reason': '對話太短，唔需要蒸餾',
            'confidence': 0.9,
        }

    # LLM judgement path
    try:
        return _llm_judge_distill(conversation)
    except Exception as e:
        return {
            'should_distill': False,
            'distill_type': None,
            'reason': f'LLM 判斷失敗: {e}',
            'confidence': 0.0,
        }


def _llm_judge_distill(conversation: List[Dict[str, str]]) -> Dict[str, Any]:
    recent = conversation[-10:]
    conv_text = "\n".join([f"{m.get('role','')}: {m.get('content','')}" for m in recent])

    system_prompt = (
        "你係一個蒸餾判斷器。分析以下對話，判斷需唔需要蒸餾，如果需要用邊種。\n"
        f"可用蒸餾類型：{json.dumps(DISTILL_TYPES, ensure_ascii=False, indent=2)}\n"
        "回覆 JSON（只回 JSON，冇其他文字）：{\n  \"should_distill\": true/false, \"distill_type\": \"recap\"/\"compression\"/\"perspective\"/null, \"reason\": \"一句話解釋\", \"confidence\": 0.0-1.0\n}\n"
        "判斷原則：\n- 如果對話只係普通閒聊或簡單操作，唔需要蒸餾\n- 如果有修正行為 → recap\n- 如果對話好長或一個 topic 討論完 → compression\n- 如果用戶問緊要做決定嘅問題 → perspective\n寧願唔蒸餾都唔好亂蒸餾（precision > recall）\n"
    )

    resp = _call_openrouter(system_prompt, conv_text)
    try:
        parsed = json.loads(resp)
        # basic validation
        sd = parsed.get('should_distill', False)
        dtype = parsed.get('distill_type')
        reason = parsed.get('reason', '')
        conf = float(parsed.get('confidence') or 0.0)
        return {'should_distill': bool(sd), 'distill_type': dtype, 'reason': reason, 'confidence': conf}
    except Exception:
        # fallback conservative
        return {'should_distill': False, 'distill_type': None, 'reason': 'LLM 回傳解析失敗', 'confidence': 0.0}


def _call_openrouter(system_prompt: str, user_input: str) -> str:
    api_key = _load_api_key()
    url = 'https://openrouter.ai/api/v1/chat/completions'
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek/deepseek-chat-v3-0324",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        "max_tokens": 100,
        "temperature": 0.1,
    }
    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        r.raise_for_status()
        data = r.json()
        choices = data.get('choices') or []
        if not choices:
            return '{}'
        return choices[0].get('message', {}).get('content', '{}')
    except Exception as e:
        return json.dumps({'should_distill': False, 'distill_type': None, 'reason': f'call error: {e}', 'confidence': 0.0})


def _load_api_key() -> str:
    # search paths: ~/.secrets/openrouter.env, .env in project root, env var
    home = Path.home()
    secrets_path = home / '.secrets' / 'openrouter.env'
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding='utf-8').splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                return line.split('=', 1)[1].strip()
    # project .env
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                return line.split('=', 1)[1].strip()
    key = os.environ.get('OPENROUTER_API_KEY')
    if key:
        return key
    raise RuntimeError('OPENROUTER_API_KEY not found')


def log_distill_decision(decision: Dict[str, Any], conversation_length: int):
    log_dir = Path(os.path.expanduser(os.getenv('JARVIS_LOG_DIR', '~/jarvis-v0/logs')))
    log_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        'ts': time.time(),
        'type': 'meta_router_decision',
        'distill_type': decision.get('distill_type'),
        'should_distill': decision.get('should_distill'),
        'reason': decision.get('reason'),
        'confidence': decision.get('confidence'),
        'conversation_length': conversation_length,
    }
    path = log_dir / 'distill.log'
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
