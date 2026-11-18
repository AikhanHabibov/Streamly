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
