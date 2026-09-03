"""
PostgreSQL database operations for WHOOP token and snapshot storage.
"""

import asyncpg
import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL")


async def get_conn():
    """Get a fresh database connection."""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not set! Add PostgreSQL reference in Railway Variables.")
    return await asyncpg.connect(DATABASE_URL)


async def init_db():
    """Initialize the database and create tables if they don't exist."""
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not set!")
    safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else "unknown"
    print(f"[DB] Connecting to: ...@{safe_url}")

    conn = await get_conn()
    try:
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

        # Keep the legacy table as the current materialized view while storing
        # every changed observation in an append-only revision table.
        await conn.execute("ALTER TABLE whoop_daily_snapshots ADD COLUMN IF NOT EXISTS data_status TEXT")
        await conn.execute("ALTER TABLE whoop_daily_snapshots ADD COLUMN IF NOT EXISTS snapshot_hash TEXT")
        await conn.execute("ALTER TABLE whoop_daily_snapshots ADD COLUMN IF NOT EXISTS revision INTEGER")
        await conn.execute("ALTER TABLE whoop_daily_snapshots ADD COLUMN IF NOT EXISTS report_data TEXT")
        await conn.execute("ALTER TABLE whoop_daily_snapshots ADD COLUMN IF NOT EXISTS provenance TEXT")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS whoop_daily_snapshot_revisions (
                id BIGSERIAL PRIMARY KEY,
                date TEXT NOT NULL,
                revision INTEGER NOT NULL,
                snapshot_hash TEXT NOT NULL,
                data_status TEXT NOT NULL,
                report_data TEXT NOT NULL,
                provenance TEXT NOT NULL,
                observed_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(date, revision)
            )
        """)
        await conn.execute("""ALTER TABLE whoop_daily_snapshot_revisions
            DROP CONSTRAINT IF EXISTS whoop_daily_snapshot_revisions_date_snapshot_hash_key""")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshot_revisions_date
            ON whoop_daily_snapshot_revisions(date DESC, revision DESC)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS whoop_daily_sync_jobs (
                date TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TIMESTAMPTZ NOT NULL,
                last_error TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        print("[DB] Initialized PostgreSQL base tables")
    finally:
        await conn.close()

    # Initialize Poke context tables
    await init_poke_tables()


async def get_token() -> Optional[Dict[str, Any]]:
    """Get the stored WHOOP token."""
    conn = await get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM whoop_tokens WHERE id = 1")
        return dict(row) if row else None
    finally:
        await conn.close()


async def save_token(access_token: str, refresh_token: str, expires_at: str, scope: str = None):
    """Save or update the WHOOP token."""
    conn = await get_conn()
    try:
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
    finally:
        await conn.close()


async def token_exists() -> bool:
    """Check if a token exists."""
    conn = await get_conn()
    try:
        result = await conn.fetchval("SELECT id FROM whoop_tokens WHERE id = 1")
        return result is not None
    finally:
        await conn.close()


async def save_snapshot(data: Dict[str, Any]):
    """Save or update a daily snapshot."""
    import json

    conn = await get_conn()
    raw_data = json.dumps(data.get("raw_data")) if data.get("raw_data") else None

    try:
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
    finally:
        await conn.close()


async def get_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Get the most recent snapshot."""
    conn = await get_conn()
    try:
        row = await conn.fetchrow(
            """SELECT * FROM whoop_daily_snapshots
               WHERE data_status = 'finalized' OR data_status IS NULL
               ORDER BY date DESC LIMIT 1"""
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def get_snapshots(limit: int = 7) -> List[Dict[str, Any]]:
    """Get the most recent snapshots."""
    conn = await get_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT $1",
            limit
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def get_last_sync_time() -> Optional[str]:
    """Get the timestamp of the last sync."""
    conn = await get_conn()
    try:
        result = await conn.fetchval(
            "SELECT MAX(updated_at) FROM whoop_daily_snapshots"
        )
        return str(result) if result else None
    finally:
        await conn.close()


async def save_daily_report(report: Dict[str, Any], provenance: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the current view and append a revision only when content changes."""
    fingerprint_report = dict(report)
    fingerprint_report.pop("retry", None)
    fingerprint_report.pop("snapshot", None)
    fingerprint_report.pop("provenance", None)
    fingerprint_provenance = dict(provenance)
    fingerprint_provenance.pop("retrieved_at", None)
    canonical = json.dumps(
        {"report": fingerprint_report, "provenance": fingerprint_provenance},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    provenance_json = json.dumps(provenance, sort_keys=True, default=str)
    report_json = json.dumps(report, sort_keys=True, default=str)
    day = report["date"]
    status = report["data_status"]
    recovery = report.get("recovery") or {}
    sleep = report.get("sleep") or {}
    cycle = report.get("cycle") or {}

    conn = await get_conn()
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", day)
            previous = await conn.fetchrow(
                """SELECT revision, snapshot_hash FROM whoop_daily_snapshot_revisions
                   WHERE date = $1 ORDER BY revision DESC LIMIT 1 FOR UPDATE""",
                day,
            )
            if previous and previous["snapshot_hash"] == digest:
                revision = previous["revision"]
                revised = False
            else:
                revision = (previous["revision"] if previous else 0) + 1
                await conn.execute(
                    """INSERT INTO whoop_daily_snapshot_revisions
                       (date, revision, snapshot_hash, data_status, report_data, provenance)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    day, revision, digest, status, report_json, provenance_json,
                )
                revised = previous is not None

            await conn.execute(
                """INSERT INTO whoop_daily_snapshots
                   (date, recovery_score, recovery_state, strain, sleep_duration,
                    sleep_debt, sleep_efficiency, sleep_disturbances, hrv, resting_hr,
                    raw_data, data_status, snapshot_hash, revision, report_data, provenance)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                   ON CONFLICT (date) DO UPDATE SET
                     recovery_score=EXCLUDED.recovery_score,
                     recovery_state=EXCLUDED.recovery_state,
                     strain=EXCLUDED.strain,
                     sleep_duration=EXCLUDED.sleep_duration,
                     sleep_debt=EXCLUDED.sleep_debt,
                     sleep_efficiency=EXCLUDED.sleep_efficiency,
                     sleep_disturbances=EXCLUDED.sleep_disturbances,
                     hrv=EXCLUDED.hrv,
                     resting_hr=EXCLUDED.resting_hr,
                     raw_data=EXCLUDED.raw_data,
                     data_status=EXCLUDED.data_status,
                     snapshot_hash=EXCLUDED.snapshot_hash,
                     revision=EXCLUDED.revision,
                     report_data=EXCLUDED.report_data,
                     provenance=EXCLUDED.provenance,
                     updated_at=NOW()""",
                day, recovery.get("recovery_score"), recovery.get("state"), cycle.get("strain"),
                sleep.get("total_sleep"), sleep.get("sleep_debt"), sleep.get("sleep_efficiency"),
                sleep.get("disturbances"), recovery.get("hrv"), recovery.get("resting_hr"),
                report_json, status, digest, revision, report_json, provenance_json,
            )
            return {"revision": revision, "snapshot_hash": digest, "is_revision": revised}
    finally:
        await conn.close()


async def get_daily_report(date: str) -> Optional[Dict[str, Any]]:
    conn = await get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT report_data, revision, snapshot_hash, updated_at FROM whoop_daily_snapshots WHERE date = $1",
            date,
        )
        if not row or not row["report_data"]:
            return None
        report = json.loads(row["report_data"])
        report["snapshot"] = {
            "revision": row["revision"],
            "snapshot_hash": row["snapshot_hash"],
            "stored_at": str(row["updated_at"]),
        }
        return report
    finally:
        await conn.close()


async def enqueue_daily_sync(date: str, retry_at: datetime) -> None:
    conn = await get_conn()
    try:
        await conn.execute(
            """INSERT INTO whoop_daily_sync_jobs(date, status, next_attempt_at)
               VALUES ($1, 'pending', $2)
               ON CONFLICT (date) DO UPDATE SET
                 status=CASE WHEN whoop_daily_sync_jobs.attempt_count + 1 >= 12 THEN 'failed' ELSE 'pending' END,
                 attempt_count=whoop_daily_sync_jobs.attempt_count + 1,
                 next_attempt_at=EXCLUDED.next_attempt_at, updated_at=NOW()""",
            date, retry_at,
        )
    finally:
        await conn.close()


async def get_due_daily_sync_jobs(limit: int = 3) -> List[Dict[str, Any]]:
    conn = await get_conn()
    try:
        rows = await conn.fetch(
            """SELECT * FROM whoop_daily_sync_jobs
               WHERE status='pending' AND next_attempt_at <= NOW()
               ORDER BY next_attempt_at LIMIT $1""",
            limit,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def update_daily_sync_job(date: str, *, completed: bool, retry_at: Optional[datetime] = None, error: Optional[str] = None) -> None:
    conn = await get_conn()
    try:
        if completed:
            await conn.execute(
                "UPDATE whoop_daily_sync_jobs SET status='completed', attempt_count=attempt_count+1, last_error=NULL, updated_at=NOW() WHERE date=$1",
                date,
            )
        else:
            await conn.execute(
                """UPDATE whoop_daily_sync_jobs SET
                   status=CASE WHEN attempt_count + 1 >= 12 THEN 'failed' ELSE 'pending' END,
                   attempt_count=attempt_count+1,
                   next_attempt_at=$2, last_error=$3, updated_at=NOW() WHERE date=$1""",
                date, retry_at, error,
            )
    finally:
        await conn.close()


# ============== New Tables for Poke Context & Engagement Tracking ==============

async def init_poke_tables():
    """Initialize the new tables for Poke context and engagement tracking."""
    conn = await get_conn()
    try:
        # Poke context - unified context for isolated triggers
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS poke_context (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_user_activity TIMESTAMP,
                last_user_activity_date TEXT,
                last_response_quality TEXT,
                last_checkin_sent TIMESTAMP,
                last_checkin_type TEXT,
                last_checkin_id INTEGER,
                checkins_since_response INTEGER DEFAULT 0,
                current_state TEXT,
                previous_state TEXT,
                state_changed_at TIMESTAMP,
                opt_out_until TIMESTAMP,
                opt_out_reason TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Interaction log - tracks all check-ins and responses
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS interaction_log (
                id SERIAL PRIMARY KEY,
                checkin_type TEXT,
                trigger_source TEXT,
                user_state TEXT,
                hour_of_day INTEGER,
                day_of_week TEXT,
                recovery_score INTEGER,
                responded BOOLEAN DEFAULT FALSE,
                response_quality TEXT,
                response_time_minutes INTEGER,
                previous_checkin_id INTEGER,
                timestamp TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_interaction_responded
            ON interaction_log(checkin_type, responded)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_interaction_quality
            ON interaction_log(response_quality)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_interaction_timestamp
            ON interaction_log(timestamp DESC)
        """)

        # State transitions - tracks flow between states
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS state_transitions (
                id SERIAL PRIMARY KEY,
                from_state TEXT,
                to_state TEXT,
                trigger TEXT,
                hour_of_day INTEGER,
                day_of_week TEXT,
                recovery_at_transition INTEGER,
                timestamp TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_transitions_states
            ON state_transitions(from_state, to_state)
        """)

        # Recovery history - for credibility tracking
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS recovery_history (
                id SERIAL PRIMARY KEY,
                date TEXT NOT NULL UNIQUE,
                recovery_score INTEGER,
                previous_day_score INTEGER,
                delta INTEGER,
                flagged_anomaly BOOLEAN DEFAULT FALSE,
                timestamp TIMESTAMP DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_recovery_date
            ON recovery_history(date DESC)
        """)

        # User settings - configurable thresholds
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                buffer_urgent REAL DEFAULT 1.5,
                buffer_anchored REAL DEFAULT 3.0,
                recovery_low INTEGER DEFAULT 60,
                recovery_high INTEGER DEFAULT 80,
                sleep_efficiency_good REAL DEFAULT 85.0,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        print("[DB] Initialized Poke context tables")
    finally:
        await conn.close()


# ============== Poke Context CRUD ==============

async def get_poke_context() -> Optional[Dict[str, Any]]:
    """Get the current Poke context."""
    conn = await get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM poke_context WHERE id = 1")
        return dict(row) if row else None
    finally:
        await conn.close()


async def update_poke_context(updates: Dict[str, Any]):
    """Update the Poke context with the given values."""
    conn = await get_conn()
    try:
        exists = await conn.fetchval("SELECT id FROM poke_context WHERE id = 1")

        if exists:
            # Build dynamic update query
            set_clauses = []
            values = []
            i = 1
            for key, value in updates.items():
                if key != 'id':
                    set_clauses.append(f"{key} = ${i}")
                    values.append(value)
                    i += 1

            set_clauses.append(f"updated_at = ${i}")
            values.append(datetime.now())

            query = f"UPDATE poke_context SET {', '.join(set_clauses)} WHERE id = 1"
            await conn.execute(query, *values)
        else:
            # Insert new row
            updates['id'] = 1
            updates['updated_at'] = datetime.now()
            columns = ', '.join(updates.keys())
            placeholders = ', '.join(f'${i+1}' for i in range(len(updates)))
            query = f"INSERT INTO poke_context ({columns}) VALUES ({placeholders})"
            await conn.execute(query, *updates.values())
    finally:
        await conn.close()


# ============== Interaction Log CRUD ==============

async def log_checkin(
    checkin_type: str,
    trigger_source: str,
    user_state: Optional[str],
    recovery_score: Optional[int],
    previous_checkin_id: Optional[int] = None
) -> int:
    """Log a check-in and return its ID."""
    conn = await get_conn()
    try:
        now = datetime.now()
        checkin_id = await conn.fetchval("""
            INSERT INTO interaction_log (
                checkin_type, trigger_source, user_state,
                hour_of_day, day_of_week, recovery_score,
                previous_checkin_id, timestamp
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
        """,
            checkin_type, trigger_source, user_state,
            now.hour, now.strftime('%A'), recovery_score,
            previous_checkin_id, now
        )
        return checkin_id
    finally:
        await conn.close()


async def mark_checkin_responded(
    checkin_id: int,
    response_quality: str,
    response_time_minutes: Optional[int] = None
):
    """Mark a check-in as responded with quality assessment."""
    conn = await get_conn()
    try:
        await conn.execute("""
            UPDATE interaction_log SET
                responded = TRUE,
                response_quality = $1,
                response_time_minutes = $2
            WHERE id = $3
        """, response_quality, response_time_minutes, checkin_id)
    finally:
        await conn.close()


async def close_unanswered_checkins():
    """Mark all unanswered check-ins as not responded (close them out)."""
    conn = await get_conn()
    try:
        await conn.execute("""
            UPDATE interaction_log SET
                responded = FALSE,
                response_quality = 'no_response'
            WHERE responded IS FALSE AND response_quality IS NULL
        """)
    finally:
        await conn.close()


async def get_recent_interactions(days: int = 30) -> List[Dict[str, Any]]:
    """Get recent interactions for analysis."""
    conn = await get_conn()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        rows = await conn.fetch("""
            SELECT * FROM interaction_log
            WHERE timestamp >= $1
            ORDER BY timestamp DESC
        """, cutoff)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def get_engagement_stats(days: int = 30) -> Dict[str, Any]:
    """Calculate engagement statistics from interaction log."""
    conn = await get_conn()
    try:
        cutoff = datetime.now() - timedelta(days=days)

        # Response rates by checkin type
        type_stats = await conn.fetch("""
            SELECT
                checkin_type,
                COUNT(*) as total,
                SUM(CASE WHEN responded THEN 1 ELSE 0 END) as responded_count
            FROM interaction_log
            WHERE timestamp >= $1 AND checkin_type IS NOT NULL
            GROUP BY checkin_type
        """, cutoff)

        # Response quality breakdown
        quality_stats = await conn.fetch("""
            SELECT
                response_quality,
                COUNT(*) as count
            FROM interaction_log
            WHERE timestamp >= $1 AND response_quality IS NOT NULL
            GROUP BY response_quality
        """, cutoff)

        # Best/worst hours
        hour_stats = await conn.fetch("""
            SELECT
                hour_of_day,
                COUNT(*) as total,
                SUM(CASE WHEN responded THEN 1 ELSE 0 END) as responded_count
            FROM interaction_log
            WHERE timestamp >= $1
            GROUP BY hour_of_day
            HAVING COUNT(*) >= 2
            ORDER BY hour_of_day
        """, cutoff)

        # User initiations (no previous checkin)
        initiations = await conn.fetchval("""
            SELECT COUNT(*) FROM interaction_log
            WHERE timestamp >= $1
            AND response_quality = 'initiation'
        """, cutoff)

        # Total check-ins
        total = await conn.fetchval("""
            SELECT COUNT(*) FROM interaction_log WHERE timestamp >= $1
        """, cutoff)

        return {
            "type_stats": [dict(r) for r in type_stats],
            "quality_stats": [dict(r) for r in quality_stats],
            "hour_stats": [dict(r) for r in hour_stats],
            "initiations": initiations or 0,
            "total": total or 0
        }
    finally:
        await conn.close()


# ============== State Transitions CRUD ==============

async def log_state_transition(
    from_state: str,
    to_state: str,
    trigger: str,
    recovery_at_transition: Optional[int] = None
):
    """Log a state transition."""
    conn = await get_conn()
    try:
        now = datetime.now()
        await conn.execute("""
            INSERT INTO state_transitions (
                from_state, to_state, trigger,
                hour_of_day, day_of_week, recovery_at_transition, timestamp
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
            from_state, to_state, trigger,
            now.hour, now.strftime('%A'), recovery_at_transition, now
        )
    finally:
        await conn.close()


async def get_state_transition_stats(days: int = 30) -> Dict[str, Any]:
    """Get state transition statistics."""
    conn = await get_conn()
    try:
        cutoff = datetime.now() - timedelta(days=days)

        # Common transitions
        transitions = await conn.fetch("""
            SELECT
                from_state,
                to_state,
                COUNT(*) as frequency,
                AVG(hour_of_day) as avg_hour
            FROM state_transitions
            WHERE timestamp >= $1
            GROUP BY from_state, to_state
            ORDER BY frequency DESC
        """, cutoff)

        # State durations (time between entering and leaving a state)
        # This is approximated by looking at consecutive transitions
        state_counts = await conn.fetch("""
            SELECT
                to_state as state,
                COUNT(*) as entries
            FROM state_transitions
            WHERE timestamp >= $1
            GROUP BY to_state
        """, cutoff)

        return {
            "transitions": [dict(r) for r in transitions],
            "state_entries": [dict(r) for r in state_counts]
        }
    finally:
        await conn.close()


# ============== Recovery History CRUD ==============

async def log_recovery(date: str, recovery_score: int, previous_day_score: Optional[int] = None):
    """Log recovery score for a date."""
    conn = await get_conn()
    try:
        delta = None
        flagged = False

        if previous_day_score is not None:
            delta = recovery_score - previous_day_score
            # Flag anomalies (>30% jump)
            if abs(delta) > 30:
                flagged = True

        # Use upsert
        await conn.execute("""
            INSERT INTO recovery_history (date, recovery_score, previous_day_score, delta, flagged_anomaly)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (date) DO UPDATE SET
                recovery_score = $2,
                previous_day_score = $3,
                delta = $4,
                flagged_anomaly = $5,
                timestamp = NOW()
        """, date, recovery_score, previous_day_score, delta, flagged)

        return {"delta": delta, "flagged": flagged}
    finally:
        await conn.close()


async def get_recovery_history(days: int = 14) -> List[Dict[str, Any]]:
    """Get recent recovery history."""
    conn = await get_conn()
    try:
        rows = await conn.fetch("""
            SELECT * FROM recovery_history
            ORDER BY date DESC
            LIMIT $1
        """, days)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def get_anomaly_count(days: int = 14) -> int:
    """Count recovery anomalies in recent history."""
    conn = await get_conn()
    try:
        cutoff = datetime.now() - timedelta(days=days)
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM recovery_history
            WHERE flagged_anomaly = TRUE AND timestamp >= $1
        """, cutoff)
        return count or 0
    finally:
        await conn.close()


# ============== User Settings CRUD ==============

async def get_user_settings() -> Dict[str, Any]:
    """Get user settings or return defaults."""
    conn = await get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM user_settings WHERE id = 1")
        if row:
            return dict(row)
        else:
            # Return defaults
            return {
                "buffer_urgent": 1.5,
                "buffer_anchored": 3.0,
                "recovery_low": 60,
                "recovery_high": 80,
                "sleep_efficiency_good": 85.0
            }
    finally:
        await conn.close()


async def update_user_settings(updates: Dict[str, Any]):
    """Update user settings."""
    conn = await get_conn()
    try:
        exists = await conn.fetchval("SELECT id FROM user_settings WHERE id = 1")

        if exists:
            set_clauses = []
            values = []
            i = 1
            for key, value in updates.items():
                if key not in ('id', 'updated_at'):
                    set_clauses.append(f"{key} = ${i}")
                    values.append(value)
                    i += 1

            if set_clauses:
                set_clauses.append(f"updated_at = ${i}")
                values.append(datetime.now())
                query = f"UPDATE user_settings SET {', '.join(set_clauses)} WHERE id = 1"
                await conn.execute(query, *values)
        else:
            # Insert with defaults + overrides
            defaults = {
                "id": 1,
                "buffer_urgent": 1.5,
                "buffer_anchored": 3.0,
                "recovery_low": 60,
                "recovery_high": 80,
                "sleep_efficiency_good": 85.0,
                "updated_at": datetime.now()
            }
            defaults.update(updates)

            columns = ', '.join(defaults.keys())
            placeholders = ', '.join(f'${i+1}' for i in range(len(defaults)))
            query = f"INSERT INTO user_settings ({columns}) VALUES ({placeholders})"
            await conn.execute(query, *defaults.values())
    finally:
        await conn.close()
