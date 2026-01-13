"""
PostgreSQL database operations for WHOOP token and snapshot storage.
"""

import asyncpg
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL")

# Connection pool (initialized on first use)
_pool: Optional[asyncpg.Pool] = None


_pool_lock = None

async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool, _pool_lock
    import asyncio

    if _pool_lock is None:
        _pool_lock = asyncio.Lock()

    async with _pool_lock:
        if _pool is None:
            if not DATABASE_URL:
                raise Exception("DATABASE_URL not set! Add PostgreSQL reference in Railway Variables.")
            # Log connection (hide password)
            safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "unknown"
            print(f"[DB] Connecting to: ...@{safe_url}")
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS whoop_tokens (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                scope TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS whoop_daily_snapshots (
                id SERIAL PRIMARY KEY,
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
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_date
            ON whoop_daily_snapshots(date DESC)
        """)

    print(f"[DB] Initialized PostgreSQL")


async def get_token() -> Optional[Dict[str, Any]]:
    """Get the stored WHOOP token."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM whoop_tokens WHERE id = 1")
        return dict(row) if row else None


async def save_token(access_token: str, refresh_token: str, expires_at: str, scope: str = None):
    """Save or update the WHOOP token."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Check if token exists
        exists = await conn.fetchval("SELECT id FROM whoop_tokens WHERE id = 1")

        if exists:
            await conn.execute("""
                UPDATE whoop_tokens SET
                    access_token = $1,
                    refresh_token = $2,
                    expires_at = $3,
                    scope = $4,
                    updated_at = NOW()
                WHERE id = 1
            """, access_token, refresh_token, expires_at, scope)
        else:
            await conn.execute("""
                INSERT INTO whoop_tokens (id, access_token, refresh_token, expires_at, scope)
                VALUES (1, $1, $2, $3, $4)
            """, access_token, refresh_token, expires_at, scope)

    print(f"[DB] Token saved, expires at: {expires_at}")


async def token_exists() -> bool:
    """Check if a token exists."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT id FROM whoop_tokens WHERE id = 1")
        return result is not None


async def save_snapshot(data: Dict[str, Any]):
    """Save or update a daily snapshot."""
    import json

    pool = await get_pool()
    raw_data = json.dumps(data.get("raw_data")) if data.get("raw_data") else None

    async with pool.acquire() as conn:
        # Check if snapshot exists for this date
        exists = await conn.fetchval(
            "SELECT id FROM whoop_daily_snapshots WHERE date = $1",
            data.get("date")
        )

        if exists:
            await conn.execute("""
                UPDATE whoop_daily_snapshots SET
                    recovery_score = $1, recovery_state = $2, strain = $3,
                    sleep_duration = $4, sleep_debt = $5, sleep_efficiency = $6,
                    sleep_disturbances = $7, hrv = $8, resting_hr = $9,
                    raw_data = $10, updated_at = NOW()
                WHERE date = $11
            """,
                data.get("recovery_score"), data.get("recovery_state"), data.get("strain"),
                data.get("sleep_duration"), data.get("sleep_debt"), data.get("sleep_efficiency"),
                data.get("sleep_disturbances"), data.get("hrv"), data.get("resting_hr"),
                raw_data, data.get("date")
            )
        else:
            await conn.execute("""
                INSERT INTO whoop_daily_snapshots (
                    date, recovery_score, recovery_state, strain,
                    sleep_duration, sleep_debt, sleep_efficiency,
                    sleep_disturbances, hrv, resting_hr, raw_data
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
                data.get("date"), data.get("recovery_score"), data.get("recovery_state"),
                data.get("strain"), data.get("sleep_duration"), data.get("sleep_debt"),
                data.get("sleep_efficiency"), data.get("sleep_disturbances"),
                data.get("hrv"), data.get("resting_hr"), raw_data
            )


async def get_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Get the most recent snapshot."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT 1"
        )
        return dict(row) if row else None


async def get_snapshots(limit: int = 7) -> List[Dict[str, Any]]:
    """Get the most recent snapshots."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT $1",
            limit
        )
        return [dict(row) for row in rows]


async def get_last_sync_time() -> Optional[str]:
    """Get the timestamp of the last sync."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT MAX(updated_at) FROM whoop_daily_snapshots"
        )
        return str(result) if result else None
