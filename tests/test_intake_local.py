import os
from pathlib import Path
from skills import intake


def test_classify_and_store(tmp_path):
    # use a small local image file if exists, else create dummy bytes
    img_path = Path("/Users/nhp/fixture_receipt.jpg")
    if img_path.exists():
        img_bytes = img_path.read_bytes()
    else:
        img_bytes = b"\xff\xd8\xff\xdb\x00\x43\x00"  # minimal jpeg header

    parsed = intake.classify_and_extract(img_bytes)
    assert "type" in parsed
    assert "extracted_json" in parsed

    db_path = tmp_path / "jarvis.db"
    rec = {
        "timestamp": "2026-04-27T01:00:00",
        "type": parsed.get("type", "photo"),
        "raw_input": "<test>",
        "extracted_json": parsed.get("extracted_json", {}),
        "source": "unittest",
    }
    rowid = intake.store_intake(rec, db_path)
    assert rowid > 0
    # obsdaily
    intake.append_to_daily_intake(rec)
    today = Path(os.environ.get("OBSIDIAN_VAULT", "~/ObsidianVault.main")).expanduser() / "05-Daily" / "2026-04-27.md"
    # file may not exist in test env, just ensure no exceptions
    assert rowid > 0
