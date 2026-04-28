import os
import requests
import json
from datetime import datetime

NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_VERSION = '2022-06-28'
STUDENTS_DB_ID = '2dd03430-f7aa-809d-b33c-f2d472e72ca9'

HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Notion-Version': NOTION_VERSION,
    'Content-Type': 'application/json'
}


def _req(method, url, **kwargs):
    if NOTION_API_KEY is None:
        raise RuntimeError('NOTION_API_KEY not set')
    resp = requests.request(method, url, headers=HEADERS, timeout=15, **kwargs)
    resp.raise_for_status()
    return resp.json()


def find_student(name):
    """Query students DB for case-insensitive name match. Return page dict or None."""
    url = f'https://api.notion.com/v1/databases/{STUDENTS_DB_ID}/query'
    body = {
        'filter': {
            'property': 'NAME',
            'title': {
                'contains': name
            }
        }
    }
    try:
        data = _req('POST', url, json=body)
        results = data.get('results', [])
        for p in results:
            # extract title text
            props = p.get('properties', {})
            title_prop = props.get('NAME', {})
            title_text = ''
            if title_prop.get('title'):
                title_text = ''.join([t.get('plain_text','') for t in title_prop.get('title',[])])
            if title_text.lower() == name.lower():
                return {'id': p.get('id'), 'name': title_text, 'properties': props}
        # if none exact, return first contains
        if results:
            p = results[0]
            props = p.get('properties', {})
            title_prop = props.get('NAME', {})
            title_text = ''.join([t.get('plain_text','') for t in title_prop.get('title',[])])
            return {'id': p.get('id'), 'name': title_text, 'properties': props}
    except Exception as e:
        return None
    return None


def get_lesson_db(student_page_id):
    """Get block children of student page and return child database id if any."""
    url = f'https://api.notion.com/v1/blocks/{student_page_id}/children'
    try:
        data = _req('GET', url)
        for b in data.get('results', []):
            if b.get('type') == 'child_database':
                return b.get('id')
        return None
    except Exception as e:
        return None


def new_student(name, phone=None, price=None, term=None, day=None,
                time=None, level=None, instrument=None):
    """Create a new student page in students DB and create an inline lesson DB as child database."""
    # create page in students DB
    url = 'https://api.notion.com/v1/pages'
    properties = {
        'NAME': {'title': [{'text': {'content': name}}]},
        '狀態': {'select': {'name': '進行中'}},
        '已約': {'checkbox': True},
    }
    if phone:
        properties['電話'] = {'phone_number': phone}
    if price is not None:
        try:
            properties['每堂價錢'] = {'number': float(price)}
        except Exception:
            pass
    if term:
        properties['堂數模式'] = {'select': {'name': term}}
    if day:
        properties['上堂日'] = {'select': {'name': day}}
    if time:
        properties['上堂時間'] = {'rich_text': [{'text': {'content': time}}]}
    if level:
        properties['級別'] = {'select': {'name': level}}
    if instrument:
        properties['樂器'] = {'select': {'name': instrument}}

    body = {'parent': {'database_id': STUDENTS_DB_ID}, 'properties': properties}
    try:
        p = _req('POST', url, json=body)
        page_id = p.get('id')
        # create child database (inline) with schema
        db_url = 'https://api.notion.com/v1/databases'
        db_body = {
            'parent': {'type': 'page_id', 'page_id': page_id},
            'title': [{'type': 'text', 'text': {'content': f"{name} 課堂紀錄"}}],
            'properties': {
                '堂數': {'title': {}},
                '日期': {'date': {}},
                '狀態': {'select': {'options': [{'name': '未開始'},{'name':'進行中'},{'name':'完成'},{'name':'缺課'}]}},
                '已上': {'checkbox': {}},
                '學費': {'select': {'options':[{'name':'未開始'},{'name':'進行中'},{'name':'已收取'}]}},
                '學費收取日期': {'date': {}}
            }
        }
        dbp = _req('POST', db_url, json=db_body)
        lesson_db_id = dbp.get('id')
        return {'page_id': page_id, 'lesson_db_id': lesson_db_id}
    except Exception as e:
        return {'error': str(e)}


def _parse_lesson_title(title):
    # expect X/Y
    try:
        parts = title.split('/')
        x = int(parts[0])
        y = int(parts[1]) if len(parts)>1 else None
        return x, y
    except Exception:
        return None, None


def log_lesson(name, content=None, lesson_num=None):
    stud = find_student(name)
    if not stud:
        return f'搵唔到 {name}，要唔要新增？'
    page_id = stud['id']
    lesson_db = get_lesson_db(page_id)
    if not lesson_db:
        return f'無為 {name} 搵到課堂紀錄資料庫。'
    # query lessons not completed
    url = f'https://api.notion.com/v1/databases/{lesson_db}/query'
    try:
        data = _req('POST', url, json={})
        rows = data.get('results', [])
        target = None
        if lesson_num is not None:
            for r in rows:
                title = ''.join([t.get('plain_text','') for t in r.get('properties',{}).get('堂數',{}).get('title',[])])
                x,y = _parse_lesson_title(title)
                if x == lesson_num:
                    target = r
                    break
        if not target:
            # pick first row where 狀態 != 完成
            for r in rows:
                sel = r.get('properties',{}).get('狀態',{}).get('select')
                if not sel or sel.get('name') != '完成':
                    target = r
                    break
        if not target:
            return f'冇未完成嘅課堂紀錄可以標記。'
        # update target page properties
        tpage = target.get('id')
        up_url = f'https://api.notion.com/v1/pages/{tpage}'
        body = {'properties': {'狀態': {'select': {'name': '完成'}}, '已上': {'checkbox': True}}}
        _req('PATCH', up_url, json=body)
        # append content as child block if provided
        if content:
            app_url = f'https://api.notion.com/v1/blocks/{tpage}/children'
            block_body = {'children': [{'object':'block','type':'paragraph','paragraph':{'rich_text':[{'type':'text','text':{'content':content}}]}}]}
            _req('PATCH', app_url, json=block_body)
        return f'已標記 {name} 的課堂為完成。'
    except Exception as e:
        return f'操作失敗: {e}'


def schedule_next(name, date_str, time_str=None):
    stud = find_student(name)
    if not stud:
        return f'搵唔到 {name}，要唔要新增？'
    page_id = stud['id']
    lesson_db = get_lesson_db(page_id)
    if not lesson_db:
        return f'無為 {name} 搵到課堂紀錄資料庫。'
    # query lessons to find last
    url = f'https://api.notion.com/v1/databases/{lesson_db}/query'
    try:
        data = _req('POST', url, json={})
        rows = data.get('results', [])
        last_x = 0
        last_y = None
        if rows:
            # find max X by parsing 堂數 title
            for r in rows:
                title = ''.join([t.get('plain_text','') for t in r.get('properties',{}).get('堂數',{}).get('title',[])])
                x,y = _parse_lesson_title(title)
                if x and (x>last_x):
                    last_x = x
                    last_y = y
        # decide next
        default_y = 4
        if stud.get('properties',{}).get('堂數模式',{}):
            sel = stud['properties']['堂數模式'].get('select')
            if sel and sel.get('name'):
                try:
                    default_y = int(sel.get('name').lstrip('/'))
                except Exception:
                    pass
        if last_x >= (last_y or default_y):
            next_x = 1
            next_y = default_y
        else:
            next_x = last_x + 1
            next_y = last_y or default_y

        # create new lesson row
        create_url = 'https://api.notion.com/v1/pages'
        props = {
            'parent': {'database_id': lesson_db},
            'properties': {
                '堂數': {'title':[{'text':{'content':f"{next_x}/{next_y}"}}]},
                '日期': {'date': {'start': date_str}},
                '狀態': {'select': {'name':'未開始'}}
            }
        }
        if time_str:
            props['properties']['備註'] = {'rich_text':[{'text':{'content': time_str}}]}
        _req('POST', create_url, json=props)
        # update outer student page 已約 = true
        up_url = f'https://api.notion.com/v1/pages/{page_id}'
        _req('PATCH', up_url, json={'properties': {'已約': {'checkbox': True}}})
        return f'已為 {name} 安排下次堂: {next_x}/{next_y} 於 {date_str} {time_str or ""}'
    except Exception as e:
        return f'操作失敗: {e}'
