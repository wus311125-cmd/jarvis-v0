-- Create chat_history table for conversation history
CREATE TABLE IF NOT EXISTS chat_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  tool_used TEXT,
  memory_type TEXT DEFAULT NULL
);
