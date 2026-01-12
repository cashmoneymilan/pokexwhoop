import { getDb, saveDb, query, queryOne } from './client.js';

export async function saveSnapshot(data) {
  const db = await getDb();

  // Check if snapshot exists for this date
  const existing = await queryOne('SELECT id FROM whoop_daily_snapshots WHERE date = ?', [data.date]);

  if (existing) {
    db.run(`
      UPDATE whoop_daily_snapshots SET
        recovery_score = ?,
        recovery_state = ?,
        strain = ?,
        sleep_duration = ?,
        sleep_debt = ?,
        sleep_efficiency = ?,
        sleep_disturbances = ?,
        hrv = ?,
        resting_hr = ?,
        raw_data = ?,
        updated_at = datetime('now')
      WHERE date = ?
    `, [
      data.recoveryScore,
      data.recoveryState,
      data.strain,
      data.sleepDuration,
      data.sleepDebt,
      data.sleepEfficiency,
      data.sleepDisturbances,
      data.hrv,
      data.restingHr,
      data.rawData ? JSON.stringify(data.rawData) : null,
      data.date
    ]);
  } else {
    db.run(`
      INSERT INTO whoop_daily_snapshots (
        date, recovery_score, recovery_state, strain, sleep_duration,
        sleep_debt, sleep_efficiency, sleep_disturbances, hrv, resting_hr, raw_data
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `, [
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
    ]);
  }

  saveDb();
  return await getSnapshotByDate(data.date);
}

export async function getSnapshotByDate(date) {
  return await queryOne('SELECT * FROM whoop_daily_snapshots WHERE date = ?', [date]);
}

export async function getLatestSnapshot() {
  return await queryOne('SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT 1');
}

export async function getSnapshotsForRange(startDate, endDate) {
  const result = await query(`
    SELECT * FROM whoop_daily_snapshots
    WHERE date >= ? AND date <= ?
    ORDER BY date DESC
  `, [startDate, endDate]);
  return result.rows;
}

export async function getLastNSnapshots(n) {
  const result = await query(`
    SELECT * FROM whoop_daily_snapshots
    ORDER BY date DESC
    LIMIT ?
  `, [n]);
  return result.rows;
}

export async function getLastSyncTime() {
  const row = await queryOne('SELECT MAX(updated_at) as last_sync FROM whoop_daily_snapshots');
  return row?.last_sync || null;
}
