#!/usr/bin/env python3
"""
Quick benchmark runner for NVIDIA NIM models/scenarios requested by user.

This script is additive and does not modify existing benchmark logic.
It reads NVIDIA_API_KEY from environment or .env in project root, runs three scenarios
per model 3 times, and writes results to scripts/nvidia_nim_results.json and
docs/benchmarks/nvidia-nim-S56.md (creating docs/benchmarks if missing).

Be careful: this makes live network calls.
"""
import os
import json
import time
try:
    import httpx
    _HAVE_HTTPX = True
except Exception:
    import subprocess
    _HAVE_HTTPX = False
from pathlib import Path
try:
    # prefer python-dotenv if available
    from dotenv import load_dotenv
    _HAVE_DOTENV = True
except Exception:
    _HAVE_DOTENV = False

ROOT = Path(__file__).resolve().parents[1]

NIM_API_KEY = os.getenv("NVIDIA_API_KEY")
NIM_BASE = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Updated candidate model IDs (consulted build.nvidia.com). We'll try these free/available IDs.
MODELS = [
    # 11 candidates requested (use exact IDs from /v1/models if available)
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/nemotron-3-super-120b-a12b",
    "deepseek-ai/deepseek-v4-flash",
    "z-ai/glm-5.1",
    "qwen/qwen3.5-122b-a10b",
    "nvidia/gpt-oss-120b",
    "nvidia/gpt-oss-20b",
    "nvidia/llama-3.1-nemotron-nano-8b-v1",
    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "google/gemma-4-31b-it",
    "moonshot/kimi-2.5",
]

SCENARIOS = {
    "A": {"prompt": "用一句話解釋咩係 function calling", "tools": []},
    "B": {"prompt": "幫我記低：今日買咗杯咖啡 $38", "tools": ["log_expense"]},
    "C": {"prompt": "幫我記帳同埋 set 個 reminder 聽日交租", "tools": ["log_expense", "set_reminder"]},
}


# OpenAI-standard tools schema builder
def build_tools_schema(names):
    tools = []
    for n in names:
        if n == "log_expense":
            tools.append({
                "type": "function",
                "function": {
                    "name": "log_expense",
                    "description": "記錄一筆開支",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string", "description": "買咗咩"},
                            "amount": {"type": "number", "description": "幾錢"},
                        },
                        "required": ["item", "amount"],
                    },
                },
            })
        elif n == "set_reminder":
            tools.append({
                "type": "function",
                "function": {
                    "name": "set_reminder",
                    "description": "設定提醒",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "提醒內容"},
                            "datetime": {"type": "string", "description": "ISO datetime"},
                        },
                        "required": ["task", "datetime"],
                    },
                },
            })
    return tools

HEADERS = {"Content-Type": "application/json"}


def load_env_dotenv():
    p = ROOT / ".env"
    if _HAVE_DOTENV:
        # use python-dotenv if installed for robust parsing
        load_dotenv(dotenv_path=str(p))
        return
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        k, sep, v = line.partition("=")
        if sep and k:
            # strip quotes
            v = v.strip().strip('"').strip("'")
            if not os.getenv(k):
                os.environ[k] = v


def call_nim(model, prompt, tools):
    url = f"{NIM_BASE}/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 300,
    }
    if tools:
        # use OpenAI-standard tools schema
        body["tools"] = build_tools_schema(tools)
        # ensure provider receives the tool choice directive we used in manual test
        # (the NVIDIA endpoint accepts "tool_choice": "auto" as observed)
        body["tool_choice"] = "auto"

    headers = HEADERS.copy()
    if NIM_API_KEY:
        # NVIDIA expects: Authorization: Bearer nvapi-...
        headers["Authorization"] = f"Bearer {NIM_API_KEY}"
    start = time.time()
    try:
        if _HAVE_HTTPX:
            r = httpx.post(url, json=body, headers=headers, timeout=30.0)
            latency = time.time() - start
            result = {"status_code": r.status_code, "latency_s": latency}
            try:
                result["json"] = r.json()
            except Exception:
                result["text"] = r.text[:200]
            return result
        else:
            # Fallback to curl via subprocess when httpx is not installed
            import shlex
            cmd = [
                "curl", "-s", "-w", "nHTTP:%{http_code}",
                f"{url}",
                "-H", f"Authorization: {headers.get('Authorization')}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(body)
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            latency = time.time() - start
            out = proc.stdout
            # last token after nHTTP: is status code
            if "nHTTP:" in out:
                parts = out.rsplit("nHTTP:", 1)
                text = parts[0]
                status = int(parts[1].strip() or 0)
            else:
                text = out
                status = None
            result = {"status_code": status, "latency_s": latency}
            # try parse json
            try:
                result["json"] = json.loads(text)
            except Exception:
                result["text"] = text[:200]
            return result
    except Exception as e:
        return {"error": str(e), "status_code": None, "latency_s": time.time() - start}


def run():
    load_env_dotenv()
    global NIM_API_KEY
    if not NIM_API_KEY:
        NIM_API_KEY = os.getenv("NVIDIA_API_KEY")
    # Prefer provider key in opencode.json if present (explicit inject)
    try:
        opencfg = ROOT / "opencode.json"
        if opencfg.exists():
            import json as _json
            cfg = _json.load(open(opencfg))
            prov = cfg.get("provider", {}).get("nvidia", {})
            pk = prov.get("apiKey") or prov.get("api_key")
            if pk:
                NIM_API_KEY = pk
    except Exception:
        pass

    out = {"models": [], "meta": {"nim_base": NIM_BASE, "timestamp": time.time()}}

    # Phase 1: run Scenario A (plain chat) for all models once
    available = []
    for model in MODELS:
        print(f"[PHASE1] Testing A: {model}")
        res = call_nim(model, SCENARIOS["A"]["prompt"], SCENARIOS["A"]["tools"])
        out.setdefault("models", []).append({"model": model, "scenarios": {"A": [res]}})
        status = res.get("status_code")
        print(f"  -> status={status}, latency={res.get('latency_s')}")
        if status == 200:
            available.append(model)
        time.sleep(0.5)

    # Phase 2: for available models, run Scenario B and C three times each
    for model in available:
        print(f"[PHASE2] Running B/C for: {model}")
        # find the model entry we stored
        entry = next((m for m in out["models"] if m["model"] == model), None)
        if entry is None:
            entry = {"model": model, "scenarios": {}}
            out["models"].append(entry)
        for sname in ("B", "C"):
            runs = []
            for i in range(3):
                print(f"  {sname} run {i+1}/3")
                res = call_nim(model, SCENARIOS[sname]["prompt"], SCENARIOS[sname]["tools"])
                runs.append(res)
                print(f"    -> status={res.get('status_code')}, latency={res.get('latency_s')}")
                time.sleep(0.5)
            entry["scenarios"][sname] = runs

    # write JSON
    outp = ROOT / "scripts" / "nvidia_nim_results.json"
    outp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # generate markdown summary
    mdp = ROOT / "docs" / "benchmarks"
    mdp.mkdir(parents=True, exist_ok=True)
    mdfile = mdp / "nvidia-nim-S56.md"
    lines = ["# NVIDIA NIM Benchmark (S56)", "", f"Base: {NIM_BASE}", ""]
    for m in out["models"]:
        lines.append(f"## {m['model']}")
        for sname, runs in m["scenarios"].items():
            statuses = []
            latencies = []
            for r in runs:
                if r.get("status_code"):
                    statuses.append(str(r["status_code"]))
                else:
                    statuses.append("ERR")
                if r.get("latency_s"):
                    latencies.append(round(r["latency_s"] * 1000))
            lines.append(f"- Scenario {sname}: statuses={statuses}, latencies_ms={latencies}")
        lines.append("")

    mdfile.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote results to {outp} and summary {mdfile}")


if __name__ == "__main__":
    run()
