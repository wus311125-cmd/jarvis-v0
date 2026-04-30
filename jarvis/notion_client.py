import os
import json
from typing import Any, Dict
try:
    import httpx
except Exception:
    httpx = None

# Use same Notion-Version as jarvis.student to satisfy handoff constraint
from jarvis import student as _student

NOTION_VERSION = getattr(_student, 'NOTION_VERSION', '2022-06-28')


def _get_headers(token: str | None = None) -> Dict[str, str]:
    if token is None:
        token = os.environ.get('NOTION_API_KEY')
    if not token:
        raise RuntimeError('NOTION_API_KEY not set')
    return {
        'Authorization': f'Bearer {token}',
        'Notion-Version': NOTION_VERSION,
        'Content-Type': 'application/json',
    }


def search_notion(query: str, page_size: int = 5) -> Dict[str, Any]:
    """Perform a simple search across pages by title/content using Notion search endpoint.

    Returns a dict with 'results' list. This is a thin wrapper suitable for the router tools.
    """
    url = 'https://api.notion.com/v1/search'
    body = {'query': query, 'page_size': page_size}
    headers = _get_headers()
    if httpx:
        resp = httpx.post(url, headers=headers, json=body, timeout=15.0)
        try:
            resp.raise_for_status()
        except Exception:
            raise RuntimeError(f'HTTP {resp.status_code}: {resp.text}')
        return resp.json()
    else:
        import requests
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        try:
            resp.raise_for_status()
        except Exception:
            raise RuntimeError(f'HTTP {resp.status_code}: {resp.text}')
        return resp.json()


def query_notion_database(database_id: str, filter_json: Dict | None = None, page_size: int = 20) -> Dict[str, Any]:
    """Query a Notion database. Limits results to `page_size` (default 20 as per handoff)."""
    url = f'https://api.notion.com/v1/databases/{database_id}/query'
    body = {}
    if filter_json and isinstance(filter_json, dict):
        body.update(filter_json)
    # enforce page_size cap at 20 per handoff
    body.setdefault('page_size', min(int(page_size), 20))
    headers = _get_headers()
    if httpx:
        resp = httpx.post(url, headers=headers, json=body, timeout=15.0)
        try:
            resp.raise_for_status()
        except Exception:
            raise RuntimeError(f'HTTP {resp.status_code}: {resp.text}')
        return resp.json()
    else:
        import requests
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        try:
            resp.raise_for_status()
        except Exception:
            raise RuntimeError(f'HTTP {resp.status_code}: {resp.text}')
        return resp.json()


def read_notion_page(page_id: str, truncate_chars: int = 3000) -> Dict[str, Any]:
    """Retrieve block children for a page and return a simplified text body.

    Truncates returned text body to `truncate_chars` characters to respect handoff.
    """
    url = f'https://api.notion.com/v1/blocks/{page_id}/children'
    headers = _get_headers()
    if httpx:
        resp = httpx.get(url, headers=headers, timeout=15.0)
        try:
            resp.raise_for_status()
        except Exception:
            raise RuntimeError(f'HTTP {resp.status_code}: {resp.text}')
        data = resp.json()
    else:
        import requests
        resp = requests.get(url, headers=headers, timeout=15)
        try:
            resp.raise_for_status()
        except Exception:
            raise RuntimeError(f'HTTP {resp.status_code}: {resp.text}')
        data = resp.json()
    # Flatten paragraph blocks into a simple text body
    texts = []
    for b in data.get('results', []):
        t = None
        if b.get('type') == 'paragraph':
            rich = b.get('paragraph', {}).get('rich_text', [])
            t = ''.join([rt.get('plain_text','') for rt in rich])
        elif b.get('type') == 'heading_1':
            rich = b.get('heading_1', {}).get('rich_text', [])
            t = ''.join([rt.get('plain_text','') for rt in rich])
        elif b.get('type') == 'heading_2':
            rich = b.get('heading_2', {}).get('rich_text', [])
            t = ''.join([rt.get('plain_text','') for rt in rich])
        elif b.get('type') == 'heading_3':
            rich = b.get('heading_3', {}).get('rich_text', [])
            t = ''.join([rt.get('plain_text','') for rt in rich])
        if t:
            texts.append(t)
    body = "\n\n".join(texts)
    if len(body) > int(truncate_chars):
        body = body[:int(truncate_chars)]
    return {'page_id': page_id, 'body': body, 'raw': data}
