import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional

DB_PATH = "jarvis.db"


def _ensure_table(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck TEXT,
            question TEXT,
            answer TEXT,
            next_review TEXT,
            interval INTEGER DEFAULT 1,
            ease_factor REAL DEFAULT 2.5,
            created_at TEXT
        )
        """
    )
    conn.commit()


def _get_conn(path: Optional[str] = None):
    p = path or DB_PATH
    conn = sqlite3.connect(str(p))
    _ensure_table(conn)
    return conn


def add_flashcard(deck: Optional[str], question: str, answer: str) -> Dict:
    """Insert a flashcard. Returns dict with ok and id."""
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    # default next_review to today so it's immediately reviewable
    next_review = date.today().isoformat()
    cur.execute(
        "INSERT INTO flashcards (deck, question, answer, next_review, created_at) VALUES (?,?,?,?,?)",
        (deck or 'default', question, answer, next_review, now),
    )
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    return {"ok": True, "id": rowid}


def review_due(limit: int = 20, deck: Optional[str] = None) -> List[Dict]:
    """Return list of due flashcards (next_review <= today or NULL)."""
    conn = _get_conn()
    cur = conn.cursor()
    today = date.today().isoformat()
    if deck:
        rows = cur.execute(
            "SELECT id, deck, question, answer, next_review, interval, ease_factor FROM flashcards WHERE (next_review IS NULL OR next_review<=?) AND deck=? ORDER BY next_review IS NULL, next_review LIMIT ?",
            (today, deck, limit),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT id, deck, question, answer, next_review, interval, ease_factor FROM flashcards WHERE (next_review IS NULL OR next_review<=?) ORDER BY next_review IS NULL, next_review LIMIT ?",
            (today, limit),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "deck": r[1],
            "question": r[2],
            "answer": r[3],
            "next_review": r[4],
            "interval": r[5],
            "ease_factor": r[6],
        })
    conn.close()
    return out


def get_stats() -> Dict:
    conn = _get_conn()
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0]
    today = date.today().isoformat()
    due = cur.execute("SELECT COUNT(*) FROM flashcards WHERE next_review IS NULL OR next_review<=?", (today,)).fetchone()[0]
    decks = cur.execute("SELECT COUNT(DISTINCT deck) FROM flashcards").fetchone()[0]
    conn.close()
    return {"total": total, "due": due, "decks": decks}


def list_decks() -> List[str]:
    conn = _get_conn()
    cur = conn.cursor()
    rows = cur.execute("SELECT DISTINCT deck FROM flashcards ORDER BY deck").fetchall()
    conn.close()
    return [r[0] for r in rows if r[0] is not None]


def search_cards(query: str, limit: int = 20) -> List[Dict]:
    conn = _get_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    rows = cur.execute(
        "SELECT id, deck, question, answer, next_review FROM flashcards WHERE question LIKE ? OR answer LIKE ? ORDER BY id DESC LIMIT ?",
        (q, q, limit),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "deck": r[1],
            "question": r[2],
            "answer": r[3],
            "next_review": r[4],
        })
    conn.close()
    return out
