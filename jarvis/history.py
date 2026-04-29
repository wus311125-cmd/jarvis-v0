import sqlite3


def save_message(db_conn, role, content, tool_used=None):
    cur = db_conn.cursor()
    # try to write to tool_used column if exists; fallback to original insert when absent
    try:
        cur.execute("INSERT INTO chat_history (role, content, tool_used) VALUES (?,?,?)", (role, content, tool_used))
    except Exception:
        # fallback for older schema
        cur.execute("INSERT INTO chat_history (role, content) VALUES (?,?)", (role, content))
    db_conn.commit()

def get_recent(db_conn, limit=20):
    cur = db_conn.cursor()
    # prefer returning tool_used if present
    try:
        cur.execute("SELECT role, content, tool_used FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        rows.reverse()
        return [{'role': r[0], 'content': r[1], 'tool_used': r[2]} for r in rows]
    except Exception:
        cur.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        rows.reverse()
        return [{'role': r[0], 'content': r[1]} for r in rows]
