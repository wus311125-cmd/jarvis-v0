import sys, os
sys.path.insert(0, os.path.expanduser('~/oh-my-opencode/skills/leak-linter'))
from linter import lint

variants = [
    'TL;DR：今晚搞掂 leak linter，朝早落 code',
    '結論：用 regex 守門，唔再靠 prompt',
    '主路線：先寫 fixture，再寫 detector',
    '利害取條：快做 vs 穩做，揀其中一條',
    'Immediate（今晚）：寫圖紙。Short-term（聽日）：落 code。Mid-term（下週）：rollout。',
    '我已準備好寫 fixture，亦已避免使用 TL;DR header，跟住即刻落手',
    'RUN_P0',
    '要我而家即刻寫埋 detector code 嗎？',
]
blocked = 0
for v in variants:
    r = lint(v)
    status = 'BLOCKED' if r.get('blocked') else 'PASS'
    print(f'{status} | {r.get("rule_id", "-")} | {v[:50]}')
    if r.get('blocked'): blocked += 1

print(f'\n=== {blocked}/{len(variants)} blocked ===')
assert blocked == len(variants), f'AC-1 FAIL: only {blocked}/{len(variants)} blocked'
print('AC-1 PASS ✅')
