import json, os
from datetime import datetime

FEW_SHOTS_PATH = os.path.join(os.path.dirname(__file__), 'few_shots.json')

def learn_from_correction(original_input: str, correct_tool: str, lesson: str, wrong_tool: str = None):
    """Persist a correction as a new few-shot example or update existing one."""
    try:
        if os.path.exists(FEW_SHOTS_PATH):
            with open(FEW_SHOTS_PATH, 'r', encoding='utf-8') as f:
                shots = json.load(f)
        else:
            shots = []
    except Exception:
        shots = []

    new_entry = {
        'input': original_input,
        'tool': correct_tool,
        'why': lesson,
        'source': 'correction',
        'learned_at': datetime.now().isoformat()
    }
    if wrong_tool:
        new_entry['wrong_tool'] = wrong_tool

    updated = False
    for i, s in enumerate(shots):
        if s.get('input','').strip() == original_input.strip():
            shots[i] = new_entry
            updated = True
            break
    if not updated:
        shots.append(new_entry)

    # write back
    with open(FEW_SHOTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(shots, f, ensure_ascii=False, indent=2)

    return { 'ok': True, 'message': f'已學識：「{original_input}」→ {correct_tool}（{lesson}）' }
