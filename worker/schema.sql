-- Cloud store for the on-site page (D1, SQLite).
-- Apply once:  npx wrangler d1 execute tank-calibration --remote --file worker/schema.sql
-- Every statement is idempotent: running the file again changes nothing.

-- A team space.  The secret keyword is never stored: only a PBKDF2 hash.
CREATE TABLE IF NOT EXISTS workspaces (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  salt        TEXT NOT NULL,
  hash        TEXT NOT NULL,
  iterations  INTEGER NOT NULL,
  created_at  INTEGER NOT NULL,
  created_by  TEXT NOT NULL
);

-- A login.  The token is never stored: only its SHA-256.
CREATE TABLE IF NOT EXISTS tokens (
  hash          TEXT PRIMARY KEY,
  workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user          TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  expires_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS tokens_expiry ON tokens(expires_at);

-- One campaign session: the page's session JSON, as the page saved it.
-- version goes up by one on every save; a save must name the version it
-- started from, so two people cannot overwrite each other.
CREATE TABLE IF NOT EXISTS campaigns (
  workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  id            TEXT NOT NULL,
  tank          TEXT NOT NULL,
  levels        INTEGER NOT NULL,
  version       INTEGER NOT NULL,
  data          TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  created_by    TEXT NOT NULL,
  updated_at    INTEGER NOT NULL,
  updated_by    TEXT NOT NULL,
  deleted_at    INTEGER,
  PRIMARY KEY (workspace_id, id)
);
CREATE INDEX IF NOT EXISTS campaigns_updated ON campaigns(workspace_id, updated_at);

-- Failed logins and signups, per IP address and per workspace name.
CREATE TABLE IF NOT EXISTS fails (
  key    TEXT PRIMARY KEY,
  count  INTEGER NOT NULL,
  since  INTEGER NOT NULL
);
