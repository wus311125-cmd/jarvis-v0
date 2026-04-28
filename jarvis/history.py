import sqlite3

def save_message(db_conn, role, content):
    cur = db_conn.cursor()
    cur.execute("INSERT INTO chat_history (role, content) VALUES (?,?)", (role, content))
    db_conn.commit()

def get_recent(db_conn, limit=20):
    cur = db_conn.cursor()
    cur.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    # return in chronological order
    rows.reverse()
    return [{'role': r[0], 'content': r[1]} for r in rows]
