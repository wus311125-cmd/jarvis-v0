-- ALTER TABLE to add direction column to expenses
ALTER TABLE expenses ADD COLUMN direction TEXT DEFAULT 'expense';
