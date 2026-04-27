"""One-off backfill: normalize existing intake rows + create missing expenses."""
import json, sqlite3, shutil, time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skills.normalize import normalize_extracted

DB = Path.home() / "jarvis-v0" / "jarvis.db"

# Backup
bak = f"{DB}.bak.{int(time.time())}"
shutil.copy2(DB, bak)
print(f"Backup: {bak}")

conn = sqlite3.connect(str(DB))
cur = conn.cursor()

# Normalize intake rows
cur.execute("SELECT id, type, extracted_json FROM intake WHERE id > 0 ORDER BY id")
rows = cur.fetchall()
updated = 0
created = 0
for rid, typ, ej in rows:
    try:
        obj = json.loads(ej)
    except Exception:
        continue
    normalized = normalize_extracted(obj)
    if normalized != obj:
        cur.execute("UPDATE intake SET extracted_json=? WHERE id=?",
                    (json.dumps(normalized, ensure_ascii=False), rid))
        updated += 1

    # Auto-create expense for receipts with valid amount
    ext = normalized.get("extracted", normalized)
    amt = ext.get("amount")
    if (typ == "receipt" or normalized.get("type") == "receipt") and amt and isinstance(amt, (int, float)) and amt > 0:
        date_val = ext.get("date") or ""
        cur2 = conn.cursor()
        cur2.execute("SELECT id FROM expenses WHERE amount=? AND date=? LIMIT 1", (amt, date_val))
        if cur2.fetchone() is None:
            import datetime
            ts = datetime.datetime.now().isoformat()
            cur.execute(
                "INSERT INTO expenses (timestamp, amount, currency, category, merchant, date, note, source, synced_notion) VALUES (?,?,?,?,?,?,?,?,0)",
                (ts, amt, ext.get("currency", "HKD"), ext.get("category", "其他"),
                 ext.get("merchant", ""), date_val, "", "image")
            )
            created += 1

conn.commit()
conn.close()
print(f"Done: updated {updated} intake rows, created {created} expenses")
