-- Migration: 001_create_tables
-- Description: Create initial tables for WHOOP token storage and daily snapshots

-- Migrations tracking table
CREATE TABLE IF NOT EXISTS migrations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- WHOOP OAuth tokens (single user, single row)
CREATE TABLE IF NOT EXISTS whoop_tokens (
    id INTEGER PRIMARY KEY DEFAULT 1,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    scope TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
);

-- Daily snapshots for caching and historical data
CREATE TABLE IF NOT EXISTS whoop_daily_snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    recovery_score INTEGER,
    recovery_state VARCHAR(50),
    strain DECIMAL(4,2),
    sleep_duration INTEGER, -- in seconds
    sleep_debt INTEGER, -- in seconds
    sleep_efficiency DECIMAL(5,2),
    sleep_disturbances INTEGER,
    hrv DECIMAL(6,2),
    resting_hr INTEGER,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for date lookups
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON whoop_daily_snapshots(date DESC);
