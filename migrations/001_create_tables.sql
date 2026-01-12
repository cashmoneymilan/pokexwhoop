-- Migration: 001_create_tables
-- Description: Create initial tables for WHOOP token storage and daily snapshots (SQLite)

-- WHOOP OAuth tokens (single user, single row)
CREATE TABLE IF NOT EXISTS whoop_tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    scope TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Daily snapshots for caching and historical data
CREATE TABLE IF NOT EXISTS whoop_daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    recovery_score INTEGER,
    recovery_state TEXT,
    strain REAL,
    sleep_duration INTEGER,
    sleep_debt INTEGER,
    sleep_efficiency REAL,
    sleep_disturbances INTEGER,
    hrv REAL,
    resting_hr INTEGER,
    raw_data TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Index for date lookups
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON whoop_daily_snapshots(date DESC);
