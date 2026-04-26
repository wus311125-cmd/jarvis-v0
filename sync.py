import os
import json
from pathlib import Path
from dotenv import load_dotenv
from notion_client import Client
import sqlite3

load_dotenv()
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
if not NOTION_API_KEY:
    raise RuntimeError("NOTION_API_KEY not set")

notion = Client(auth=NOTION_API_KEY)

# Data source IDs (from SPEC)
INTAKE_COLLECTION = "4fd1e5dc-b094-4da8-beab-7c645485429c"
EXPENSES_COLLECTION = "cb9cf29e-84da-40af-b16a-b338a7ba2189"

DB_PATH = Path(os.environ.get("JARVIS_DB", "~/jarvis-v0/jarvis.db")).expanduser()

# Allowed option sets
CATEGORY_OPTIONS = {"飲食", "交通", "日常用品", "娛樂", "醫療", "教育", "其他"}
CURRENCY_OPTIONS = {"HKD", "USD", "CNY"}
TYPE_OPTIONS = {"receipt", "screenshot", "photo"}
SOURCE_INTAKE = {"telegram", "manual"}
SOURCE_EXPENSES = {"text", "image"}


def _page_exists(database_id: str, local_id: int) -> bool:
    # Query database for existing local_id
    try:
        res = notion.databases.query(database_id=database_id, filter={"property": "local_id", "number": {"equals": local_id}})
        return len(res.get("results", [])) > 0
    except Exception:
        return False


def sync_intake():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT id, timestamp, type, raw_input, extracted_json, source FROM intake WHERE synced_notion=0")
    rows = cur.fetchall()
    for row in rows:
        id_, timestamp, type_, raw_input, extracted_json, source = row
        try:
            if _page_exists(INTAKE_COLLECTION, id_):
                print(f"skip intake {id_}: already exists in Notion")
                cur.execute("UPDATE intake SET synced_notion=1 WHERE id=?", (id_,))
                continue

            # prepare properties per SPEC mapping
            # Summary (title) from extracted.summary if available
            try:
                extracted = json.loads(extracted_json)
                summary = extracted.get("summary") or extracted.get("extracted", {}).get("summary") or ""
            except Exception:
                summary = str(extracted_json)[:200]

            props = {
                "Summary": {"title": [{"text": {"content": summary}}]},
                "Type": {"select": {"name": type_ if type_ in TYPE_OPTIONS else "photo"}},
                "Date": {"date": {"start": timestamp.split("T")[0] if timestamp else None}},
                "Extracted": {"rich_text": [{"text": {"content": str(extracted_json)}}]},
                "Source": {"select": {"name": source if source in SOURCE_INTAKE else "telegram"}},
                "local_id": {"number": id_},
            }

            notion.pages.create(parent={"database_id": INTAKE_COLLECTION}, properties=props)
            cur.execute("UPDATE intake SET synced_notion=1 WHERE id=?", (id_,))
        except Exception as e:
            print(f"failed syncing intake {id_}: {e}")
            continue
    conn.commit()
    conn.close()


def sync_expenses():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT id, timestamp, amount, currency, category, merchant, date, note, source FROM expenses WHERE synced_notion=0")
    rows = cur.fetchall()
    for row in rows:
        id_, timestamp, amount, currency, category, merchant, date, note, source = row
        try:
            if _page_exists(EXPENSES_COLLECTION, id_):
                print(f"skip expense {id_}: already exists in Notion")
                cur.execute("UPDATE expenses SET synced_notion=1 WHERE id=?", (id_,))
                continue

            # validate selects
            currency_val = currency if currency in CURRENCY_OPTIONS else "HKD"
            category_val = category if category in CATEGORY_OPTIONS else "其他"
            source_val = source if source in SOURCE_EXPENSES else "text"

            props = {
                "Vendor": {"title": [{"text": {"content": merchant or ""}}]},
                "Amount": {"number": float(amount) if amount is not None else 0.0},
                "Currency": {"select": {"name": currency_val}},
                "Category": {"select": {"name": category_val}},
                "Date": {"date": {"start": date if date else None}},
                "Source": {"select": {"name": source_val}},
                "Note": {"rich_text": [{"text": {"content": note or ""}}]},
                "local_id": {"number": id_},
            }

            notion.pages.create(parent={"database_id": EXPENSES_COLLECTION}, properties=props)
            cur.execute("UPDATE expenses SET synced_notion=1 WHERE id=?", (id_,))
        except Exception as e:
            print(f"failed syncing expense {id_}: {e}")
            continue
    conn.commit()
    conn.close()


if __name__ == "__main__":
    sync_intake()
    sync_expenses()
