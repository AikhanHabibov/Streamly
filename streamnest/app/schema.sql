PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
 display_name TEXT NOT NULL, bio TEXT NOT NULL DEFAULT '',
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL,
 user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
 expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL,
 filename TEXT NOT NULL UNIQUE, poster TEXT NOT NULL DEFAULT '',
 duration REAL NOT NULL, size INTEGER NOT NULL, views INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS likes (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
 PRIMARY KEY(user_id,video_id)
);
CREATE TABLE IF NOT EXISTS subscriptions (
 subscriber_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 creator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at INTEGER NOT NULL,
 CHECK(subscriber_id != creator_id), PRIMARY KEY(subscriber_id,creator_id)
);
CREATE TABLE IF NOT EXISTS comments (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
 body TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS view_events (
 video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
 viewer TEXT NOT NULL, day INTEGER NOT NULL,
 PRIMARY KEY(video_id,viewer,day)
);
CREATE TABLE IF NOT EXISTS rate_limits (
 key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS videos_created ON videos(created_at DESC);
CREATE INDEX IF NOT EXISTS videos_creator ON videos(user_id,created_at DESC);
CREATE INDEX IF NOT EXISTS videos_category ON videos(category);
CREATE INDEX IF NOT EXISTS comments_video ON comments(video_id,created_at);
CREATE INDEX IF NOT EXISTS subscriptions_creator ON subscriptions(creator_id);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);


-- STREAMLY_LIVE_SCHEMA_V1
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


-- STREAMLY_ADMIN_SCHEMA_V1
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

-- Streaming permissions default to denied; an admin explicitly grants them.
UPDATE streamly_live_channels SET enabled=0,key_hash='' WHERE NOT EXISTS(
 SELECT 1 FROM streamly_user_safety s WHERE s.user_id=streamly_live_channels.user_id AND s.blocked=0 AND s.can_stream=1);


-- STREAMLY_SECURITY_SCHEMA_V1
CREATE TABLE IF NOT EXISTS streamly_mfa (
 username TEXT PRIMARY KEY REFERENCES streamly_admin_accounts(username) ON DELETE CASCADE,
 secret_cipher TEXT NOT NULL, generation TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 last_counter INTEGER NOT NULL DEFAULT -1, configured_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS streamly_mfa_recovery (
 username TEXT NOT NULL REFERENCES streamly_admin_accounts(username) ON DELETE CASCADE,
 code_hash TEXT NOT NULL, used_at INTEGER,
 PRIMARY KEY(username,code_hash)
);
CREATE TABLE IF NOT EXISTS streamly_mfa_challenges (
 token_hash TEXT PRIMARY KEY,
 username TEXT NOT NULL REFERENCES streamly_admin_accounts(username) ON DELETE CASCADE,
 generation TEXT NOT NULL, password_version TEXT NOT NULL,
 expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS streamly_mfa_sessions (
 token_hash TEXT PRIMARY KEY REFERENCES streamly_admin_sessions(token_hash) ON DELETE CASCADE,
 generation TEXT NOT NULL, method TEXT NOT NULL, verified_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS streamly_security_identities (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 identity TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS streamly_security_content_ids (
 target_type TEXT NOT NULL, target_id TEXT NOT NULL, nonce TEXT NOT NULL,
 PRIMARY KEY(target_type,target_id)
);
CREATE TABLE IF NOT EXISTS streamly_reports (
 id INTEGER PRIMARY KEY,
 reporter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 target_type TEXT NOT NULL CHECK(target_type IN ('video','comment','live')),
 target_id TEXT NOT NULL, target_nonce TEXT NOT NULL,
 target_owner_id INTEGER NOT NULL, owner_identity TEXT NOT NULL,
 owner_name TEXT NOT NULL, target_title TEXT NOT NULL,
 snapshot TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL, reason TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','reviewing','resolved','dismissed')),
 admin_note TEXT NOT NULL DEFAULT '', handled_by TEXT NOT NULL DEFAULT '',
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS streamly_report_duplicate
ON streamly_reports(reporter_id,target_type,target_id,target_nonce) WHERE status IN ('open','reviewing');
CREATE INDEX IF NOT EXISTS streamly_report_queue ON streamly_reports(status,created_at);
CREATE TRIGGER IF NOT EXISTS streamly_forget_comment_nonce
AFTER DELETE ON comments BEGIN
 DELETE FROM streamly_security_content_ids WHERE target_type='comment' AND target_id=CAST(OLD.id AS TEXT);
END;
CREATE TRIGGER IF NOT EXISTS streamly_forget_video_nonce
AFTER DELETE ON videos BEGIN
 DELETE FROM streamly_security_content_ids WHERE target_type='video' AND target_id=OLD.id;
END;
CREATE TRIGGER IF NOT EXISTS streamly_forget_live_nonce
AFTER DELETE ON users BEGIN
 DELETE FROM streamly_security_content_ids WHERE target_type='live' AND target_id=OLD.username;
END;
