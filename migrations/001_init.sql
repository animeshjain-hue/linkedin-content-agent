CREATE TABLE IF NOT EXISTS schema_migrations (
    name       TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posts (
    id               TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    posted_at        TEXT,
    status           TEXT NOT NULL CHECK(status IN ('draft','approved','scheduled','posted','rejected')),
    body             TEXT NOT NULL,
    hook             TEXT NOT NULL,
    topic_lane       TEXT NOT NULL CHECK(topic_lane IN ('ai_for_pms','pm_craft','healthcare_ai')),
    sub_topic        TEXT NOT NULL,
    format           TEXT NOT NULL CHECK(format IN ('story','framework','contrarian','list','build_log','question')),
    source_input_ids TEXT NOT NULL DEFAULT '[]',
    prompt_version   TEXT NOT NULL,
    model            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS engagement_snapshots (
    id                  TEXT PRIMARY KEY,
    post_id             TEXT NOT NULL REFERENCES posts(id),
    captured_at         TEXT NOT NULL,
    impressions         INTEGER,
    reactions           INTEGER NOT NULL DEFAULT 0,
    comments            INTEGER NOT NULL DEFAULT 0,
    reposts             INTEGER NOT NULL DEFAULT 0,
    profile_views_delta INTEGER
);

CREATE TABLE IF NOT EXISTS news_items (
    id               TEXT PRIMARY KEY,
    fetched_at       TEXT NOT NULL,
    source           TEXT NOT NULL,
    url              TEXT NOT NULL UNIQUE,
    title            TEXT NOT NULL,
    summary          TEXT NOT NULL,
    relevance_score  REAL,
    used_in_post_ids TEXT NOT NULL DEFAULT '[]'
);
