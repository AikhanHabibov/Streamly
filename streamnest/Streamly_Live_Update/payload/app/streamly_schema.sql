CREATE TABLE IF NOT EXISTS streamly_live_channels (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 path TEXT NOT NULL UNIQUE, key_hash TEXT NOT NULL DEFAULT '',
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT 'Gaming', enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS streamly_uploads (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 metadata TEXT NOT NULL, expected_size INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'open', video_id TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS streamly_uploads_owner ON streamly_uploads(user_id,state);
