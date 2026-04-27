import os
import json
from pathlib import Path
from dotenv import load_dotenv
from notion_client import Client
import sqlite3
import argparse
import logging

load_dotenv()
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
if not NOTION_API_KEY:
    raise RuntimeError("NOTION_API_KEY not set")

notion = Client(auth=NOTION_API_KEY)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data source IDs (from SPEC)
# Prefer env overrides so DB IDs aren't hardcoded in runtime if provided
INTAKE_COLLECTION = os.environ.get("JARVIS_INTAKE_DB_ID", "4fd1e5dc-b094-4da8-beab-7c645485429c")
EXPENSES_COLLECTION = os.environ.get("JARVIS_EXPENSES_DB_ID", "e1ac8a57-b58d-46c4-a6c3-2d7f8d487642")

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


def sync_intake(dry_run: bool = False):
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, timestamp, type, raw_input, extracted_json, source FROM intake WHERE synced_notion=0")
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("intake table missing or DB not initialized: %s", e)
        conn.close()
        return
    logger.info("Found %d intake rows to consider", len(rows))
    for row in rows:
        id_, timestamp, type_, raw_input, extracted_json, source = row
        try:
            if _page_exists(INTAKE_COLLECTION, id_):
                logger.info("skip intake %s: already exists in Notion", id_)
                if not dry_run:
                    cur.execute("UPDATE intake SET synced_notion=1 WHERE id=?", (id_,))
                continue

            try:
                extracted = json.loads(extracted_json or "{}")
            except Exception:
                extracted = {}

            # Title mapping per intake.type
            t = type_ if type_ in TYPE_OPTIONS else "photo"
            title = None
            if t == "receipt":
                vendor = extracted.get("vendor") or extracted.get("merchant") or "Receipt"
                amount = extracted.get("amount") if extracted.get("amount") is not None else "?"
                title = f"🧾 {vendor} ${amount}"
            elif t == "screenshot":
                title = f"📸 {extracted.get('summary') or extracted.get('title') or ''}".strip()
            elif t == "photo":
                title = f"🖼️ {extracted.get('description') or ''}".strip()
            if not title:
                title = f"Intake #{id_}"

            props = {
                "Summary": {"title": [{"text": {"content": title}}]},
                "Type": {"select": {"name": t}},
                "Date": {"date": {"start": timestamp.split("T")[0] if timestamp else None}},
                "Extracted": {"rich_text": [{"text": {"content": (json.dumps(extracted, ensure_ascii=False) if extracted else str(extracted_json))[:2000]}}]},
                "Source": {"select": {"name": source if source in SOURCE_INTAKE else "telegram"}},
                "local_id": {"number": id_},
            }

            if dry_run:
                logger.info("[dry-run] would create intake page: id=%s props=%s", id_, json.dumps(props, ensure_ascii=False))
            else:
                notion.pages.create(parent={"database_id": INTAKE_COLLECTION}, properties=props)
                cur.execute("UPDATE intake SET synced_notion=1 WHERE id=?", (id_,))
        except Exception as e:
            logger.exception("failed syncing intake %s", id_)
            continue
    if not dry_run:
        conn.commit()
    conn.close()


def sync_expenses(dry_run: bool = False):
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, timestamp, amount, currency, category, merchant, date, note, source FROM expenses WHERE synced_notion=0")
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        logger.warning("expenses table missing or DB not initialized: %s", e)
        conn.close()
        return
    logger.info("Found %d expense rows to consider", len(rows))
    for row in rows:
        id_, timestamp, amount, currency, category, merchant, date, note, source = row
        try:
            if _page_exists(EXPENSES_COLLECTION, id_):
                logger.info("skip expense %s: already exists in Notion", id_)
                if not dry_run:
                    cur.execute("UPDATE expenses SET synced_notion=1 WHERE id=?", (id_,))
                continue

            currency_val = currency if currency in CURRENCY_OPTIONS else "HKD"
            category_val = category if category in CATEGORY_OPTIONS else "其他"
            source_val = source if source in SOURCE_EXPENSES else "text"

            # Vendor: prefer merchant, fallback to note (original text)
            vendor_text = merchant or (note if note else "")
            # Date: prefer explicit date column, else derive from timestamp
            date_start = None
            if date:
                date_start = date
            else:
                try:
                    # timestamp is ISO datetime; take date part
                    if timestamp:
                        date_start = str(timestamp).split('T')[0]
                except Exception:
                    date_start = None

            props = {
                "Vendor": {"title": [{"text": {"content": vendor_text}}]},
                "Amount": {"number": float(amount) if amount is not None else 0.0},
                "Currency": {"select": {"name": currency_val}},
                "Category": {"select": {"name": category_val}},
                "Source": {"select": {"name": source_val}},
                "local_id": {"number": id_},
            }
            if date_start:
                props["Date"] = {"date": {"start": date_start}}

            if dry_run:
                logger.info("[dry-run] would create expense page: id=%s props=%s", id_, json.dumps(props, ensure_ascii=False))
            else:
                notion.pages.create(parent={"database_id": EXPENSES_COLLECTION}, properties=props)
                cur.execute("UPDATE expenses SET synced_notion=1 WHERE id=?", (id_,))
        except Exception as e:
            logger.exception("failed syncing expense %s", id_)
            continue
    if not dry_run:
        conn.commit()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Sync SQLite intake/expenses to Notion')
    parser.add_argument('--dry-run', action='store_true', help='Only print what would be synced')
    args = parser.parse_args()
    dry = args.dry_run
    logger.info('Starting sync (dry_run=%s)', dry)
    sync_intake(dry_run=dry)
    sync_expenses(dry_run=dry)
    logger.info('Sync complete (dry_run=%s)', dry)
