#!/usr/bin/env python3
"""Simple MCP-compatible agent spawner CLI + minimal stdio server fallback.

Supports:
- list_agents: prints JSON list of agents (name, model)
- spawn_agent: call OpenRouter chat completions with agent spec

Also implements a minimal stdio JSON-Lines protocol when run without CLI args
so it's usable as a simple MCP stdio tool if the mcp package is unavailable.

All user-facing text is in Traditional Chinese (Hong Kong Cantonese).
"""

import os
import sys
import json
import time
from typing import List, Dict, Optional

try:
    import httpx
except Exception:
    print("[Error] missing httpx; please pip install -r requirements.txt", file=sys.stderr)
    httpx = None

try:
    import yaml
except Exception:
    print("[Error] missing pyyaml; please pip install -r requirements.txt", file=sys.stderr)
    yaml = None

ROOT = os.path.expanduser(os.path.join(os.path.dirname(__file__), ".."))
AGENTS_DIR = os.path.join(os.path.dirname(__file__), "agents")
LOG_DIR = os.path.expanduser(os.path.join(ROOT, "logs"))
SPAWN_LOG = os.path.join(LOG_DIR, "agent-spawn.log")


def ensure_logs_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def read_frontmatter(path: str) -> Dict[str, Optional[str]]:
    # parse --- YAML frontmatter
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            raw = parts[1]
            try:
                data = yaml.safe_load(raw) if yaml else {}
            except Exception:
                data = {}
            return data or {}
    return {}


def list_agents() -> List[Dict[str, str]]:
    agents = []
    if not os.path.isdir(AGENTS_DIR):
        return agents
    for fn in sorted(os.listdir(AGENTS_DIR)):
        if not fn.endswith('.md'):
            continue
        path = os.path.join(AGENTS_DIR, fn)
        meta = read_frontmatter(path)
        agents.append({
            'name': meta.get('name') or os.path.splitext(fn)[0],
            'model': meta.get('model') or meta.get('model') or '',
            'file': fn,
        })
    return agents


def find_api_key() -> Optional[str]:
    # check env
    key = os.environ.get('OPENROUTER_API_KEY')
    if key:
        return key
    # check ~/.secrets/openrouter_key
    p1 = os.path.expanduser('~/.secrets/openrouter_key')
    if os.path.exists(p1):
        return open(p1).read().strip()
    # check ~/jarvis-v0/.env
    p2 = os.path.expanduser(os.path.join(ROOT, '.env'))
    if os.path.exists(p2):
        for line in open(p2):
            if 'OPENROUTER_API_KEY' in line:
                k = line.split('=', 1)[-1].strip()
                return k
    return None


def log_spawn(entry: dict):
    ensure_logs_dir()
    entry_json = json.dumps(entry, ensure_ascii=False)
    with open(SPAWN_LOG, 'a', encoding='utf-8') as f:
        f.write(entry_json + '\n')


def spawn_agent(name: str, prompt: str, context_files: Optional[List[str]] = None) -> str:
    path = os.path.join(AGENTS_DIR, f"{name}.md")
    ts = time.time()
    entry = {
        'ts': ts,
        'agent': name,
        'model': None,
        'prompt_length': len(prompt or ''),
        'response_length': None,
        'cost': None,
        'error': None,
    }
    try:
        meta = read_frontmatter(path)
    except FileNotFoundError:
        entry['error'] = f'agent spec {name}.md not found'
        log_spawn(entry)
        return f"唔好意思，搵唔到 agent spec: {name}.md"

    model = meta.get('model') or meta.get('fallback_model')
    entry['model'] = model

    user_prompt = prompt or ''
    if context_files:
        for cf in context_files:
            try:
                with open(cf, 'r', encoding='utf-8') as f:
                    user_prompt += '\n\n' + f.read()
            except Exception:
                pass

    api_key = find_api_key()
    if not api_key or not httpx:
        # return canned Cantonese reply explaining missing key
        resp = (
            f"（模擬回覆）{name}：我冇搵到 OPENROUTER_API_KEY 或者 httpx 未安裝，無法呼叫模型。"
            + " 我可以模擬回答：我係 %s，用緊 model %s。" % (name, model or 'unknown')
        )
        entry['response_length'] = len(resp)
        log_spawn(entry)
        return resp

    url = 'https://openrouter.ai/api/v1/chat/completions'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'HTTP-Referer': 'https://jarvis.hopan.dev',
        'X-Title': 'Jarvis Agents',
        'Content-Type': 'application/json',
    }
    system_prompt = meta.get('system_prompt') or meta.get('description') or (
        '你必須用繁體中文（香港廣東話口語）回覆。Technical term 可以用英文。'
    )
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]
    payload = {
        'model': model,
        'messages': messages,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            j = r.json()
            # attempt common response shapes
            content = None
            if isinstance(j, dict):
                if 'choices' in j and len(j['choices']) > 0:
                    ch = j['choices'][0]
                    if isinstance(ch, dict) and 'message' in ch:
                        content = ch['message'].get('content') or ch['message'].get('content_text')
                if not content:
                    content = j.get('text') or json.dumps(j, ensure_ascii=False)
            text = content or r.text
            entry['response_length'] = len(text)
            # cost estimation if available
            if isinstance(j, dict) and 'usage' in j:
                entry['cost'] = j['usage']
            log_spawn(entry)
            return text
    except Exception as e:
        entry['error'] = str(e)
        log_spawn(entry)
        return f"呼叫模型失敗：{e}"


def cli():
    import argparse
    p = argparse.ArgumentParser(description='Jarvis MCP Agents helper (CLI)')
    p.add_argument('--list', action='store_true')
    p.add_argument('--spawn', metavar='NAME')
    p.add_argument('--prompt', metavar='PROMPT', help='User prompt')
    p.add_argument('--context', metavar='FILES', help='Comma-separated context files')
    args = p.parse_args()
    if args.list:
        agents = list_agents()
        print(json.dumps(agents, ensure_ascii=False, indent=2))
        sys.exit(0)
    if args.spawn:
        ctx = args.context.split(',') if args.context else []
        out = spawn_agent(args.spawn, args.prompt or '', ctx)
        print(out)
        sys.exit(0)
    # minimal stdio server: read JSON lines with {"method":"list_agents"|"spawn_agent", "params": {...}}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            method = req.get('method')
            params = req.get('params') or {}
            if method == 'list_agents':
                res = list_agents()
            elif method == 'spawn_agent':
                res = spawn_agent(params.get('name'), params.get('prompt', ''), params.get('context_files', []))
            else:
                res = {'error': f'unknown method {method}'}
        except Exception as e:
            res = {'error': str(e)}
        sys.stdout.write(json.dumps({'result': res}, ensure_ascii=False) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    cli()
