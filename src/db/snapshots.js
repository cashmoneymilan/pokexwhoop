import { query } from './client.js';

export async function saveSnapshot(data) {
  const result = await query(`
    INSERT INTO whoop_daily_snapshots (
      date, recovery_score, recovery_state, strain, sleep_duration,
      sleep_debt, sleep_efficiency, sleep_disturbances, hrv, resting_hr, raw_data, updated_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, CURRENT_TIMESTAMP)
    ON CONFLICT (date) DO UPDATE SET
      recovery_score = EXCLUDED.recovery_score,
      recovery_state = EXCLUDED.recovery_state,
      strain = EXCLUDED.strain,
      sleep_duration = EXCLUDED.sleep_duration,
      sleep_debt = EXCLUDED.sleep_debt,
      sleep_efficiency = EXCLUDED.sleep_efficiency,
      sleep_disturbances = EXCLUDED.sleep_disturbances,
      hrv = EXCLUDED.hrv,
      resting_hr = EXCLUDED.resting_hr,
      raw_data = EXCLUDED.raw_data,
      updated_at = CURRENT_TIMESTAMP
    RETURNING *
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

  return result.rows[0];
}

export async function getSnapshotByDate(date) {
  const result = await query(
    'SELECT * FROM whoop_daily_snapshots WHERE date = $1',
    [date]
  );
  return result.rows[0] || null;
}

export async function getLatestSnapshot() {
  const result = await query(
    'SELECT * FROM whoop_daily_snapshots ORDER BY date DESC LIMIT 1'
  );
  return result.rows[0] || null;
}

export async function getSnapshotsForRange(startDate, endDate) {
  const result = await query(`
    SELECT * FROM whoop_daily_snapshots
    WHERE date >= $1 AND date <= $2
    ORDER BY date DESC
  `, [startDate, endDate]);
  return result.rows;
}

export async function getLastNSnapshots(n) {
  const result = await query(`
    SELECT * FROM whoop_daily_snapshots
    ORDER BY date DESC
    LIMIT $1
  `, [n]);
  return result.rows;
}

export async function getLastSyncTime() {
  const result = await query(
    'SELECT MAX(updated_at) as last_sync FROM whoop_daily_snapshots'
  );
  return result.rows[0]?.last_sync || null;
}
