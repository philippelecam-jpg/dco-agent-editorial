ALTER TABLE requests ADD COLUMN youtube_id TEXT;
ALTER TABLE requests ADD COLUMN youtube_url TEXT;
ALTER TABLE requests ADD COLUMN publication_status TEXT DEFAULT 'none';
ALTER TABLE requests ADD COLUMN delivery_status TEXT DEFAULT 'pending';
ALTER TABLE requests ADD COLUMN delivery_error TEXT;
ALTER TABLE requests ADD COLUMN delivery_attempted_at TEXT;
ALTER TABLE requests ADD COLUMN delivery_lease_until TEXT;
ALTER TABLE requests ADD COLUMN notified_at TEXT;
