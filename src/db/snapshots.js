import { getDb } from './client.js';

export function saveSnapshot(data) {
  const db = getDb();

  const stmt = db.prepare(`
    INSERT INTO whoop_daily_snapshots (
      date, recovery_score, recovery_state, strain, sleep_duration,
      sleep_debt, sleep_efficiency, sleep_disturbances, hrv, resting_hr, raw_data, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    ON CONFLICT(date) DO UPDATE SET
      recovery_score = excluded.recovery_score,
      recovery_state = excluded.recovery_state,
      strain = excluded.strain,
      sleep_duration = excluded.sleep_duration,
      sleep_debt = excluded.sleep_debt,
      sleep_efficiency = excluded.sleep_efficiency,
      sleep_disturbances = excluded.sleep_disturbances,
      hrv = excluded.hrv,
      resting_hr = excluded.resting_hr,
      raw_data = excluded.raw_data,
      updated_at = datetime('now')
  `);

  stmt.run(
    data.date,
    data.recoveryScore,
    data.recoveryState,
    data.strain,
    data.sleepDuration,
    data.sleepDebt,
    data.sleepEfficiency,
    data.sleepDisturbances,
    data.hrv,
    data.restingHr,
    data.rawData ? JSON.stringify(data.rawData) : null
  );

  return getSnapshotByDate(data.date);
}

export function getSnapshotByDate(date) {
  const db = getDb();
  return db.prepare('SELECT * FROM whoop_daily_snapshots WHERE date = ?').get(date) || null;
}

export function getLatestSnapshot() {
  const db = getDb();
  return db.prepare('SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT 1').get() || null;
}

export function getSnapshotsForRange(startDate, endDate) {
  const db = getDb();
  return db.prepare(`
    SELECT * FROM whoop_daily_snapshots
    WHERE date >= ? AND date <= ?
    ORDER BY date DESC
  `).all(startDate, endDate);
}

export function getLastNSnapshots(n) {
  const db = getDb();
  return db.prepare(`
    SELECT * FROM whoop_daily_snapshots
    ORDER BY date DESC
    LIMIT ?
  `).all(n);
}

export function getLastSyncTime() {
  const db = getDb();
  const row = db.prepare('SELECT MAX(updated_at) as last_sync FROM whoop_daily_snapshots').get();
  return row?.last_sync || null;
}
