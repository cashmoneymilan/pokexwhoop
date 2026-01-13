"""
SQLite database operations for WHOOP token and snapshot storage.
"""

import aiosqlite
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

DB_PATH = os.getenv("DB_PATH", "./data/whoop.db")


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS whoop_tokens (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                scope TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

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

            CREATE INDEX IF NOT EXISTS idx_snapshots_date
            ON whoop_daily_snapshots(date DESC);
        """)
        await db.commit()

    print(f"[DB] Initialized SQLite at {DB_PATH}")


async def get_token() -> Optional[Dict[str, Any]]:
    """Get the stored WHOOP token."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM whoop_tokens WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def save_token(access_token: str, refresh_token: str, expires_at: str, scope: str = None):
    """Save or update the WHOOP token."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if token exists
        async with db.execute("SELECT id FROM whoop_tokens WHERE id = 1") as cursor:
            exists = await cursor.fetchone()

        if exists:
            await db.execute("""
                UPDATE whoop_tokens SET
                    access_token = ?,
                    refresh_token = ?,
                    expires_at = ?,
                    scope = ?,
                    updated_at = datetime('now')
                WHERE id = 1
            """, (access_token, refresh_token, expires_at, scope))
        else:
            await db.execute("""
                INSERT INTO whoop_tokens (id, access_token, refresh_token, expires_at, scope)
                VALUES (1, ?, ?, ?, ?)
            """, (access_token, refresh_token, expires_at, scope))

        await db.commit()

    print(f"[DB] Token saved, expires at: {expires_at}")


async def token_exists() -> bool:
    """Check if a token exists."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM whoop_tokens WHERE id = 1") as cursor:
            return await cursor.fetchone() is not None


async def save_snapshot(data: Dict[str, Any]):
    """Save or update a daily snapshot."""
    import json

    async with aiosqlite.connect(DB_PATH) as db:
        # Check if snapshot exists for this date
        async with db.execute(
            "SELECT id FROM whoop_daily_snapshots WHERE date = ?",
            (data.get("date"),)
        ) as cursor:
            exists = await cursor.fetchone()

        raw_data = json.dumps(data.get("raw_data")) if data.get("raw_data") else None

        if exists:
            await db.execute("""
                UPDATE whoop_daily_snapshots SET
                    recovery_score = ?, recovery_state = ?, strain = ?,
                    sleep_duration = ?, sleep_debt = ?, sleep_efficiency = ?,
                    sleep_disturbances = ?, hrv = ?, resting_hr = ?,
                    raw_data = ?, updated_at = datetime('now')
                WHERE date = ?
            """, (
                data.get("recovery_score"), data.get("recovery_state"), data.get("strain"),
                data.get("sleep_duration"), data.get("sleep_debt"), data.get("sleep_efficiency"),
                data.get("sleep_disturbances"), data.get("hrv"), data.get("resting_hr"),
                raw_data, data.get("date")
            ))
        else:
            await db.execute("""
                INSERT INTO whoop_daily_snapshots (
                    date, recovery_score, recovery_state, strain,
                    sleep_duration, sleep_debt, sleep_efficiency,
                    sleep_disturbances, hrv, resting_hr, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get("date"), data.get("recovery_score"), data.get("recovery_state"),
                data.get("strain"), data.get("sleep_duration"), data.get("sleep_debt"),
                data.get("sleep_efficiency"), data.get("sleep_disturbances"),
                data.get("hrv"), data.get("resting_hr"), raw_data
            ))

        await db.commit()


async def get_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Get the most recent snapshot."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_snapshots(limit: int = 7) -> List[Dict[str, Any]]:
    """Get the most recent snapshots."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT ?",
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_last_sync_time() -> Optional[str]:
    """Get the timestamp of the last sync."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT MAX(updated_at) as last_sync FROM whoop_daily_snapshots"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
