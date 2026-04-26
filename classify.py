import yaml
from pathlib import Path
from typing import Dict, Any

REG_PATH = Path(__file__).parent / 'types' / 'registry.yaml'

def load_registry() -> Dict[str, Any]:
    with REG_PATH.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_type(extracted: Dict[str, Any]) -> str:
    """Simple registry-driven type selector.
    Expect extracted to have keys like 'merchant', 'amount', 'summary'
    """
    reg = load_registry()
    # heuristics
    if not extracted:
        return 'photo'
    if extracted.get('merchant') and extracted.get('amount'):
        return 'receipt'
    if extracted.get('summary') and len(extracted.get('summary','')) > 10:
        return 'screenshot'
    return 'photo'
