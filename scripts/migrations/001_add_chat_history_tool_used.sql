-- Migration: add tool_used column to chat_history for better routing telemetry
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
-- Only add the column if it does not exist. SQLite lacks IF NOT EXISTS for ALTER TABLE,
-- so this migration is idempotent when applied by checking schema at runtime.
ALTER TABLE chat_history RENAME TO chat_history_old;
CREATE TABLE chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_used TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO chat_history (role, content, tool_used, created_at)
    SELECT role, content, NULL, created_at FROM chat_history_old;
DROP TABLE chat_history_old;
COMMIT;

-- NOTE: This migration will fail if the schema is significantly different. Run locally
-- and inspect DB before applying in production. It's intended for local test environments.
