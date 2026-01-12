/**
 * Data normalization layer for WHOOP API responses
 * Transforms raw API data into clean, consistent structures
 */

/**
 * Normalize a cycle record
 */
export function normalizeCycle(cycle) {
  if (!cycle) return null;

  return {
    id: cycle.id,
    userId: cycle.user_id,
    start: cycle.start,
    end: cycle.end,
    timezoneOffset: cycle.timezone_offset,
    strain: cycle.score?.strain ?? null,
    kilojoules: cycle.score?.kilojoule ?? null,
    averageHr: cycle.score?.average_heart_rate ?? null,
    maxHr: cycle.score?.max_heart_rate ?? null
  };
}

/**
 * Normalize a recovery record
 */
export function normalizeRecovery(recovery) {
  if (!recovery) return null;

  const score = recovery.score || {};

  return {
    cycleId: recovery.cycle_id,
    sleepId: recovery.sleep_id,
    userId: recovery.user_id,
    date: extractDateFromTimestamp(recovery.created_at),
    createdAt: recovery.created_at,
    recoveryScore: score.recovery_score ?? null,
    restingHr: score.resting_heart_rate ?? null,
    hrv: score.hrv_rmssd_milli ?? null,
    spo2: score.spo2_percentage ?? null,
    skinTemp: score.skin_temp_celsius ?? null,
    state: getRecoveryState(score.recovery_score),
    // User actions that may have affected recovery
    userCalibrating: score.user_calibrating ?? false
  };
}

/**
 * Normalize a sleep record
 */
export function normalizeSleep(sleep) {
  if (!sleep) return null;

  const score = sleep.score || {};

  return {
    id: sleep.id,
    userId: sleep.user_id,
    start: sleep.start,
    end: sleep.end,
    date: extractDateFromTimestamp(sleep.start),
    timezoneOffset: sleep.timezone_offset,
    nap: sleep.nap ?? false,
    // Durations in seconds
    totalDuration: score.stage_summary?.total_in_bed_time_milli
      ? Math.round(score.stage_summary.total_in_bed_time_milli / 1000)
      : null,
    totalSleepTime: score.stage_summary?.total_sleep_time_milli
      ? Math.round(score.stage_summary.total_sleep_time_milli / 1000)
      : null,
    remSleep: score.stage_summary?.total_rem_sleep_time_milli
      ? Math.round(score.stage_summary.total_rem_sleep_time_milli / 1000)
      : null,
    lightSleep: score.stage_summary?.total_light_sleep_time_milli
      ? Math.round(score.stage_summary.total_light_sleep_time_milli / 1000)
      : null,
    deepSleep: score.stage_summary?.total_slow_wave_sleep_time_milli
      ? Math.round(score.stage_summary.total_slow_wave_sleep_time_milli / 1000)
      : null,
    awakeTime: score.stage_summary?.total_awake_time_milli
      ? Math.round(score.stage_summary.total_awake_time_milli / 1000)
      : null,
    // Sleep quality metrics
    sleepEfficiency: score.sleep_efficiency_percentage ?? null,
    sleepConsistency: score.sleep_consistency_percentage ?? null,
    respiratoryRate: score.respiratory_rate ?? null,
    disturbances: score.stage_summary?.disturbance_count ?? null,
    // Sleep need and debt
    sleepNeeded: score.sleep_needed?.baseline_milli
      ? Math.round(score.sleep_needed.baseline_milli / 1000)
      : null,
    sleepDebt: score.sleep_needed?.need_from_sleep_debt_milli
      ? Math.round(score.sleep_needed.need_from_sleep_debt_milli / 1000)
      : null
  };
}

/**
 * Normalize a workout record
 */
export function normalizeWorkout(workout) {
  if (!workout) return null;

  const score = workout.score || {};

  return {
    id: workout.id,
    userId: workout.user_id,
    start: workout.start,
    end: workout.end,
    date: extractDateFromTimestamp(workout.start),
    timezoneOffset: workout.timezone_offset,
    sportId: workout.sport_id,
    // Metrics
    strain: score.strain ?? null,
    averageHr: score.average_heart_rate ?? null,
    maxHr: score.max_heart_rate ?? null,
    kilojoules: score.kilojoule ?? null,
    percentHrMax: score.percent_recorded ?? null,
    distanceMeters: score.distance_meter ?? null,
    altitudeGain: score.altitude_gain_meter ?? null,
    altitudeLoss: score.altitude_loss_meter ?? null,
    // Zone durations in seconds
    zoneZero: score.zone_duration?.zone_zero_milli
      ? Math.round(score.zone_duration.zone_zero_milli / 1000) : null,
    zoneOne: score.zone_duration?.zone_one_milli
      ? Math.round(score.zone_duration.zone_one_milli / 1000) : null,
    zoneTwo: score.zone_duration?.zone_two_milli
      ? Math.round(score.zone_duration.zone_two_milli / 1000) : null,
    zoneThree: score.zone_duration?.zone_three_milli
      ? Math.round(score.zone_duration.zone_three_milli / 1000) : null,
    zoneFour: score.zone_duration?.zone_four_milli
      ? Math.round(score.zone_duration.zone_four_milli / 1000) : null,
    zoneFive: score.zone_duration?.zone_five_milli
      ? Math.round(score.zone_duration.zone_five_milli / 1000) : null
  };
}

/**
 * Create a daily summary from multiple data sources
 */
export function createDailySummary({ cycle, recovery, sleep }) {
  const normalizedRecovery = normalizeRecovery(recovery);
  const normalizedSleep = normalizeSleep(sleep);
  const normalizedCycle = normalizeCycle(cycle);

  const date = normalizedRecovery?.date || normalizedSleep?.date || normalizedCycle?.start?.split('T')[0];

  return {
    date,
    recovery: normalizedRecovery ? {
      score: normalizedRecovery.recoveryScore,
      state: normalizedRecovery.state,
      hrv: normalizedRecovery.hrv,
      restingHr: normalizedRecovery.restingHr
    } : null,
    sleep: normalizedSleep ? {
      totalDuration: normalizedSleep.totalSleepTime,
      efficiency: normalizedSleep.sleepEfficiency,
      debt: normalizedSleep.sleepDebt,
      disturbances: normalizedSleep.disturbances,
      quality: getSleepQuality(normalizedSleep.sleepEfficiency)
    } : null,
    strain: normalizedCycle ? {
      score: normalizedCycle.strain,
      kilojoules: normalizedCycle.kilojoules,
      averageHr: normalizedCycle.averageHr,
      maxHr: normalizedCycle.maxHr
    } : null,
    recommendedStrainRange: normalizedRecovery
      ? getRecommendedStrainRange(normalizedRecovery.recoveryScore)
      : null
  };
}

/**
 * Calculate trend from an array of values
 */
export function calculateTrend(values) {
  if (!values || values.length < 2) {
    return { direction: 'stable', change: 0 };
  }

  const validValues = values.filter(v => v !== null && v !== undefined);
  if (validValues.length < 2) {
    return { direction: 'stable', change: 0 };
  }

  const recentAvg = average(validValues.slice(0, Math.ceil(validValues.length / 2)));
  const olderAvg = average(validValues.slice(Math.ceil(validValues.length / 2)));

  const change = ((recentAvg - olderAvg) / olderAvg) * 100;

  let direction = 'stable';
  if (change > 5) direction = 'improving';
  else if (change < -5) direction = 'declining';

  return { direction, change: Math.round(change * 10) / 10 };
}

/**
 * Find notable outliers in a dataset
 */
export function findOutliers(data, valueKey) {
  const values = data.map(d => d[valueKey]).filter(v => v !== null && v !== undefined);
  if (values.length < 3) return [];

  const mean = average(values);
  const stdDev = standardDeviation(values);
  const threshold = 1.5; // 1.5 standard deviations

  return data.filter(d => {
    const value = d[valueKey];
    if (value === null || value === undefined) return false;
    return Math.abs(value - mean) > threshold * stdDev;
  }).map(d => ({
    date: d.date,
    value: d[valueKey],
    deviation: Math.round(((d[valueKey] - mean) / stdDev) * 10) / 10
  }));
}

// --- Helper functions ---

function extractDateFromTimestamp(timestamp) {
  if (!timestamp) return null;
  return timestamp.split('T')[0];
}

function getRecoveryState(score) {
  if (score === null || score === undefined) return 'unknown';
  if (score >= 67) return 'green';
  if (score >= 34) return 'yellow';
  return 'red';
}

function getSleepQuality(efficiency) {
  if (efficiency === null || efficiency === undefined) return 'unknown';
  if (efficiency >= 85) return 'excellent';
  if (efficiency >= 70) return 'good';
  if (efficiency >= 50) return 'fair';
  return 'poor';
}

function getRecommendedStrainRange(recoveryScore) {
  if (recoveryScore === null || recoveryScore === undefined) return null;

  // Based on WHOOP's strain recommendations
  if (recoveryScore >= 67) {
    return { min: 14, max: 21, description: 'Peak day - push hard' };
  } else if (recoveryScore >= 34) {
    return { min: 10, max: 14, description: 'Moderate day - maintain' };
  } else {
    return { min: 0, max: 10, description: 'Recovery day - take it easy' };
  }
}

function average(values) {
  if (!values.length) return 0;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function standardDeviation(values) {
  if (values.length < 2) return 0;
  const avg = average(values);
  const squareDiffs = values.map(v => Math.pow(v - avg, 2));
  return Math.sqrt(average(squareDiffs));
}

// Duration formatting helpers
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return null;

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

export function formatDurationDecimal(seconds) {
  if (seconds === null || seconds === undefined) return null;
  return Math.round((seconds / 3600) * 10) / 10; // Hours with 1 decimal
}
