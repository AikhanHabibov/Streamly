CREATE TABLE IF NOT EXISTS streamly_admin_accounts (
 username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS streamly_admin_sessions (
 token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES streamly_admin_accounts(username) ON DELETE CASCADE,
 expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS streamly_user_safety (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 blocked INTEGER NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),
 can_stream INTEGER NOT NULL DEFAULT 0 CHECK(can_stream IN (0,1)),
 reason TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS streamly_video_moderation (
 video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','approved','rejected')),
 reason TEXT NOT NULL DEFAULT '', reviewer TEXT NOT NULL DEFAULT '',
 updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS streamly_moderation_state ON streamly_video_moderation(state,updated_at);
CREATE TABLE IF NOT EXISTS streamly_admin_audit (
 id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
 target TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS streamly_moderate_new_video
AFTER INSERT ON videos
BEGIN
 INSERT INTO streamly_video_moderation(video_id,state,updated_at)
 VALUES(NEW.id,'pending',CAST(strftime('%s','now') AS INTEGER));
END;
CREATE TRIGGER IF NOT EXISTS streamly_remoderate_edited_video
AFTER UPDATE OF title,description,category ON videos
WHEN OLD.title IS NOT NEW.title OR OLD.description IS NOT NEW.description OR OLD.category IS NOT NEW.category
BEGIN
 INSERT INTO streamly_video_moderation(video_id,state,reason,reviewer,updated_at)
 VALUES(NEW.id,'pending','','',CAST(strftime('%s','now') AS INTEGER))
 ON CONFLICT(video_id) DO UPDATE SET state='pending',reason='',reviewer='',updated_at=excluded.updated_at;
END;
-- One-time legacy backfill only. A missing moderation row later stays fail-closed.
CREATE TABLE IF NOT EXISTS streamly_admin_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO streamly_video_moderation(video_id,state,updated_at)
SELECT id,'approved',CAST(strftime('%s','now') AS INTEGER) FROM videos
WHERE NOT EXISTS(SELECT 1 FROM streamly_admin_meta WHERE key='initial_video_backfill');
INSERT OR IGNORE INTO streamly_admin_meta VALUES('initial_video_backfill','done');
