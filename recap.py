import json
import re
import os
import logging
from typing import List, Dict, Any, Optional

import classify

# ensure logs dir
LOG_DIR = os.path.expanduser(os.getenv('JARVIS_LOG_DIR', '~/jarvis-v0/logs'))
os.makedirs(LOG_DIR, exist_ok=True)

# structured JSON logger for distillation steps
logger = logging.getLogger('distill')
if not logger.handlers:
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(os.path.join(LOG_DIR, 'distill.log'), maxBytes=5_000_000, backupCount=3, encoding='utf-8')
    formatter = logging.Formatter('%(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)


# helper to write NDJSON distill entries (keeps same log file as router)
def write_distill(entry: dict):
    try:
        path = os.path.join(LOG_DIR, 'distill.log')
        entry.setdefault('ts', __import__('datetime').datetime.utcnow().isoformat())
        entry.setdefault('source', 'recap')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            f.flush()
    except Exception:
        try:
            logger.info(json.dumps({"ts": __import__('datetime').datetime.utcnow().isoformat(), "layer": "distill_write_fail", "source": "recap"}))
        except Exception:
            pass


def recap_rewrite(text: str, entity_context: str = '', recent_turns: Optional[List[str]] = None) -> Dict[str, Any]:
    """Lightweight RECAP rewrite layer.

    Returns dict: {
      "rewritten_text": str,
      "distilled_fields": dict | None
    }

    Implementation notes:
    - Keep dependency-free (uses existing classify.rewrite_intent when available).
    - distilled_fields is a small heuristic extraction useful for corrections (e.g. change amount)
    - Designed as a minimal skeleton to evolve into LLM-based distillation later.
    """
    if recent_turns is None:
        recent_turns = []

    # Default output
    out: Dict[str, Any] = {"rewritten_text": text, "distilled_fields": None}

    # log input
    try:
        write_distill({"layer": "input", "input": text, "entity_context": entity_context})
    except Exception:
        pass

    # 1) Try to produce a rewritten intent using existing classify.rewrite_intent if available
    try:
        # classify.rewrite_intent may call remote LLM; guard failures
        rewritten = classify.rewrite_intent(text, entity_context, recent_turns)
        if isinstance(rewritten, str) and rewritten.strip():
            out["rewritten_text"] = rewritten
        # log rewrite output
        try:
            write_distill({"layer": "rewrite_output", "input": text, "output": out["rewritten_text"]})
        except Exception:
            pass
    except Exception:
        # fallback: keep original
        pass

    # 2) Heuristic distilled fields extraction (correction / short commands)
    # Patterns supported (Cantonese/Chinese heuristics):
    # - "頭先嗰筆改做 78" / "改做 78" -> {'field':'amount','new_value':78}
    # - "頭先嗰筆改做 大家樂" -> {'field':'merchant','new_value':'大家樂'}
    txt = text.strip()

    # numeric correction patterns
    m = re.search(r'(?:頭先|剛才|剛剛)?\s*(?:嗰筆)?\s*(?:改做|改為|改成|改返|改成為)\s*([+-]?[0-9]+(?:\.[0-9]+)?)', txt)
    if m:
        try:
            num = float(m.group(1))
            # prefer integer when possible
            if num.is_integer():
                num = int(num)
            out["distilled_fields"] = {"field": "amount", "new_value": num}
            try:
                write_distill({"layer": "distilled_fields", "input": text, "distilled": out["distilled_fields"]})
            except Exception:
                pass
            return out
        except Exception:
            pass

    # textual correction (merchant/category)
    m2 = re.search(r'(?:頭先|剛才|剛剛)?\s*(?:嗰筆)?\s*(?:改做|改為|改成|改返)\s*(\S.+)$', txt)
    if m2:
        candidate = m2.group(1).strip()
        # if candidate contains digits -> amount, else merchant
        if re.search(r'[0-9]', candidate):
            # pick first numeric token
            nm = re.search(r'([+-]?[0-9]+(?:\.[0-9]+)?)', candidate)
            if nm:
                try:
                    val = float(nm.group(1))
                    if val.is_integer():
                        val = int(val)
                    out["distilled_fields"] = {"field": "amount", "new_value": val}
                    return out
                except Exception:
                    pass
        # otherwise treat as merchant/merchant name
        out["distilled_fields"] = {"field": "merchant", "new_value": candidate}
        try:
            write_distill({"layer": "distilled_fields", "input": text, "distilled": out["distilled_fields"]})
        except Exception:
            pass
        return out

    # simple direct numeric message e.g. "78" or "改 78"
    m3 = re.match(r'^\s*(?:改|改為|改做)?\s*([+-]?[0-9]+(?:\.[0-9]+)?)\s*$', txt)
    if m3:
        try:
            val = float(m3.group(1))
            if val.is_integer():
                val = int(val)
            out["distilled_fields"] = {"field": "amount", "new_value": val}
            try:
                write_distill({"layer": "distilled_fields", "input": text, "distilled": out["distilled_fields"]})
            except Exception:
                pass
            return out
        except Exception:
            pass

    # No distilled fields found
    return out
