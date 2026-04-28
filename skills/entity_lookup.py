import re
import os
import requests

# Simple entity lookup for students (Notion) and vendors (hardcoded)
from typing import Dict, List

NOTION_API_KEY = os.getenv('NOTION_API_KEY')
STUDENTS_DB_ID = '2dd03430-f7aa-809d-b33c-f2d472e72ca9'
NOTION_HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Notion-Version': '2022-06-28',
    'Content-Type': 'application/json'
}

VENDORS = [
    '大快活', '茶餐廳', '麥當勞', 'Uber', 'Foodpanda'
]


def _query_students_by_name(name: str) -> List[Dict]:
    if not NOTION_API_KEY:
        return []
    url = f'https://api.notion.com/v1/databases/{STUDENTS_DB_ID}/query'
    body = {'filter': {'property': 'NAME', 'title': {'contains': name}}}
    try:
        r = requests.post(url, headers=NOTION_HEADERS, json=body, timeout=10)
        r.raise_for_status()
        data = r.json()
        results = []
        for p in data.get('results', []):
            props = p.get('properties', {})
            title = ''
            if props.get('NAME', {}).get('title'):
                title = ''.join([t.get('plain_text','') for t in props['NAME']['title']])
            results.append({'id': p.get('id'), 'name': title, 'properties': props})
        return results
    except Exception:
        return []


def lookup_entities(message: str) -> Dict:
    entities = []
    context_parts = []

    # student exact match attempt (case-insensitive)
    words = re.findall(r"[\w\u4e00-\u9fff]+", message)
    for w in words:
        # check vendors first (case-sensitiveish)
        for v in VENDORS:
            if v.lower() == w.lower() or v in message:
                entities.append({'type': 'vendor', 'name': v})
                context_parts.append(f'用戶提到商家 {v}')
        # check students via Notion
        studs = _query_students_by_name(w)
        for s in studs:
            if s.get('name','').lower() == w.lower():
                # we can extract more from properties if needed
                entities.append({'type': 'student', 'name': s.get('name'), 'id': s.get('id')})
                context_parts.append(f'用戶提到學生 {s.get("name")}')

    entity_context = '；'.join(context_parts)
    return {'entities': entities, 'entity_context': entity_context}
