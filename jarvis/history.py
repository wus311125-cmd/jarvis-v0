import sqlite3


def classify_memory_type(tool_used: str | None) -> str | None:
    """Classify memory_type based only on tool_used signal.

    Rules:
    - tool_call in ('log_expense', 'schedule', 'set_reminder') -> 'episodic'
    - tool_call == 'learn_from_correction' -> 'procedural'
    - None or other -> 'semantic'
    """
    if not tool_used:
        return 'semantic'
    if isinstance(tool_used, str):
        tu = tool_used
    else:
        try:
            tu = str(tool_used)
        except Exception:
            return 'semantic'
    episodic_tools = {'log_expense', 'schedule', 'set_reminder'}
    if tu in episodic_tools:
        return 'episodic'
    if tu == 'learn_from_correction':
        return 'procedural'
    return 'semantic'


def save_message(db_conn, role, content, tool_used=None):
    cur = db_conn.cursor()
    mem_type = classify_memory_type(tool_used)
    # try to write to tool_used and memory_type columns if exist; fallback otherwise
    try:
        cur.execute("INSERT INTO chat_history (role, content, tool_used, memory_type) VALUES (?,?,?,?)", (role, content, tool_used, mem_type))
    except Exception:
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
        cur.execute("SELECT role, content, tool_used, memory_type FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        rows.reverse()
        return [{'role': r[0], 'content': r[1], 'tool_used': r[2], 'memory_type': r[3]} for r in rows]
    except Exception:
        cur.execute("SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        rows.reverse()
        return [{'role': r[0], 'content': r[1]} for r in rows]


def recall_memory(db_conn, query: str | None = None, memory_type: str | None = None, limit: int = 50):
    """Recall messages from chat_history with optional query and memory_type filter.

    - query: simple SQL LIKE match on content (case-insensitive)
    - memory_type: filter by episodic/procedural/semantic
    Returns list of dicts: {id, role, content, tool_used, memory_type}
    """
    cur = db_conn.cursor()
    sql = "SELECT id, role, content, tool_used, memory_type FROM chat_history"
    params = []
    clauses = []
    if memory_type:
        clauses.append("memory_type = ?")
        params.append(memory_type)
    if query:
        clauses.append("content LIKE ?")
        params.append(f"%{query}%")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    results = []
    for r in rows:
        results.append({'id': r[0], 'role': r[1], 'content': r[2], 'tool_used': r[3], 'memory_type': r[4]})
    return results
