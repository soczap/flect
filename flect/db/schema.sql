CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_ts TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('info','low','medium','high','critical')),
  subject TEXT, payload TEXT NOT NULL, dedupe_key TEXT UNIQUE, status TEXT NOT NULL DEFAULT 'new');
CREATE INDEX IF NOT EXISTS signals_kind_ts ON signals(kind, ts);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, severity TEXT NOT NULL, state TEXT NOT NULL,
  opened_ts TEXT NOT NULL, closed_ts TEXT, title TEXT NOT NULL, summary TEXT,
  details TEXT NOT NULL DEFAULT '{}', github_issue INTEGER, llm_summary TEXT, dedupe_key TEXT UNIQUE);

CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, scope TEXT NOT NULL, ref TEXT NOT NULL, rule_id TEXT NOT NULL,
  severity TEXT NOT NULL, title TEXT NOT NULL, file TEXT, line INTEGER, cwe TEXT,
  evidence TEXT NOT NULL, created_ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS findings_ref ON findings(scope, ref);

CREATE TABLE IF NOT EXISTS prs (
  repo TEXT NOT NULL, number INTEGER NOT NULL, head_sha TEXT NOT NULL, base TEXT NOT NULL,
  kind TEXT NOT NULL, state TEXT NOT NULL, risk TEXT, llm_verdict TEXT, statuses TEXT NOT NULL DEFAULT '{}',
  title TEXT, updated_ts TEXT NOT NULL, PRIMARY KEY (repo, number, head_sha));

CREATE TABLE IF NOT EXISTS deployments (
  id INTEGER PRIMARY KEY, env TEXT NOT NULL CHECK (env IN ('prod','uat')), sha TEXT NOT NULL,
  previous_sha TEXT, trigger TEXT NOT NULL, state TEXT NOT NULL, started_ts TEXT NOT NULL,
  finished_ts TEXT, healthy_since TEXT, notes TEXT);

CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY, ip TEXT NOT NULL, rule_id TEXT NOT NULL, reason TEXT NOT NULL,
  offence INTEGER NOT NULL, ttl TEXT NOT NULL, created_ts TEXT NOT NULL, expires_ts TEXT NOT NULL,
  active INTEGER NOT NULL, mode TEXT NOT NULL, incident_id INTEGER, unblocked_by TEXT);
CREATE INDEX IF NOT EXISTS blocks_ip ON blocks(ip, active);

CREATE TABLE IF NOT EXISTS keys (
  name TEXT PRIMARY KEY, kind TEXT NOT NULL, location TEXT NOT NULL, expires_ts TEXT,
  days_left REAL, last_probe_ts TEXT, last_probe_ok INTEGER, alert_level TEXT, details TEXT);

CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY, task TEXT NOT NULL, priority INTEGER NOT NULL, ref TEXT,
  queued_ts TEXT NOT NULL, started_ts TEXT, finished_ts TEXT, prompt_tokens INTEGER,
  completion_tokens INTEGER, status TEXT NOT NULL, error TEXT);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref_sha TEXT, pr_number INTEGER, path TEXT NOT NULL,
  max_severity TEXT, created_ts TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, decision TEXT NOT NULL, target TEXT NOT NULL,
  params TEXT NOT NULL, mode TEXT NOT NULL, ok INTEGER, result TEXT, incident_id INTEGER,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
