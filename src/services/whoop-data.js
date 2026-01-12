/**
 * High-level WHOOP data service
 * Combines API client with normalization and caching
 */

import { whoopClient, WhoopError } from './whoop-client.js';
import * as normalizer from './normalizer.js';
import * as snapshots from '../db/snapshots.js';

// Cache TTL in milliseconds (default 15 minutes)
const CACHE_TTL_MS = parseInt(process.env.CACHE_TTL_MINUTES || '15', 10) * 60 * 1000;

// In-memory cache for very recent data
const cache = new Map();

function getCached(key) {
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    cache.delete(key);
    return null;
  }
  return entry.data;
}

function setCache(key, data) {
  cache.set(key, { data, timestamp: Date.now() });
}

/**
 * Get today's summary (recovery, sleep, strain)
 */
export async function getTodaySummary() {
  const cacheKey = 'today_summary';
  const cached = getCached(cacheKey);
  if (cached) return cached;

  try {
    // Get recent data from WHOOP
    const today = new Date().toISOString().split('T')[0];
    const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString().split('T')[0];

    const [cyclesData, recoveryData, sleepData] = await Promise.all([
      whoopClient.getCycles({ limit: 1 }),
      whoopClient.getRecovery({ limit: 1 }),
      whoopClient.getSleep({ limit: 1 })
    ]);

    const cycle = cyclesData.records?.[0];
    const recovery = recoveryData.records?.[0];
    const sleep = sleepData.records?.[0];

    const summary = normalizer.createDailySummary({ cycle, recovery, sleep });
    setCache(cacheKey, summary);

    return summary;

  } catch (error) {
    // If API fails, try to return cached DB data
    console.error('[WhoopData] Failed to get today summary:', error.message);

    const latestSnapshot = await snapshots.getLatestSnapshot();
    if (latestSnapshot) {
      return {
        date: latestSnapshot.date,
        recovery: {
          score: latestSnapshot.recovery_score,
          state: latestSnapshot.recovery_state,
          hrv: parseFloat(latestSnapshot.hrv),
          restingHr: latestSnapshot.resting_hr
        },
        sleep: {
          totalDuration: latestSnapshot.sleep_duration,
          debt: latestSnapshot.sleep_debt,
          efficiency: parseFloat(latestSnapshot.sleep_efficiency),
          disturbances: latestSnapshot.sleep_disturbances,
          quality: normalizer.formatDuration(latestSnapshot.sleep_duration)
        },
        strain: {
          score: parseFloat(latestSnapshot.strain)
        },
        stale: true,
        staleSince: latestSnapshot.updated_at
      };
    }

    throw error;
  }
}

/**
 * Get latest recovery data
 */
export async function getLatestRecovery() {
  const cacheKey = 'latest_recovery';
  const cached = getCached(cacheKey);
  if (cached) return cached;

  try {
    const data = await whoopClient.getRecovery({ limit: 1 });
    const recovery = data.records?.[0];

    if (!recovery) {
      return { error: 'no_data', message: 'No recovery data available' };
    }

    const normalized = normalizer.normalizeRecovery(recovery);
    const result = {
      date: normalized.date,
      recoveryScore: normalized.recoveryScore,
      hrv: normalized.hrv,
      restingHr: normalized.restingHr,
      state: normalized.state,
      confidenceLevel: normalized.userCalibrating ? 'calibrating' : 'normal'
    };

    setCache(cacheKey, result);
    return result;

  } catch (error) {
    console.error('[WhoopData] Failed to get latest recovery:', error.message);
    throw error;
  }
}

/**
 * Get latest sleep data
 */
export async function getLastSleep() {
  const cacheKey = 'last_sleep';
  const cached = getCached(cacheKey);
  if (cached) return cached;

  try {
    const data = await whoopClient.getSleep({ limit: 1 });
    const sleep = data.records?.[0];

    if (!sleep) {
      return { error: 'no_data', message: 'No sleep data available' };
    }

    const normalized = normalizer.normalizeSleep(sleep);
    const result = {
      date: normalized.date,
      totalSleep: normalized.totalSleepTime,
      totalSleepFormatted: normalizer.formatDuration(normalized.totalSleepTime),
      sleepDebt: normalized.sleepDebt,
      sleepDebtFormatted: normalizer.formatDuration(normalized.sleepDebt),
      sleepEfficiency: normalized.sleepEfficiency,
      disturbances: normalized.disturbances,
      stages: {
        rem: normalizer.formatDuration(normalized.remSleep),
        deep: normalizer.formatDuration(normalized.deepSleep),
        light: normalizer.formatDuration(normalized.lightSleep),
        awake: normalizer.formatDuration(normalized.awakeTime)
      }
    };

    setCache(cacheKey, result);
    return result;

  } catch (error) {
    console.error('[WhoopData] Failed to get last sleep:', error.message);
    throw error;
  }
}

/**
 * Get weekly trends for a specific metric
 */
export async function getWeekTrends(metric) {
  const validMetrics = ['recovery', 'strain', 'sleep'];
  if (!validMetrics.includes(metric)) {
    return { error: 'invalid_metric', message: `Metric must be one of: ${validMetrics.join(', ')}` };
  }

  const cacheKey = `week_trends_${metric}`;
  const cached = getCached(cacheKey);
  if (cached) return cached;

  try {
    // Get 7 days of data
    const endDate = new Date().toISOString();
    const startDate = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

    let data;
    let values = [];
    let dataPoints = [];

    switch (metric) {
      case 'recovery':
        data = await whoopClient.getRecovery({ start: startDate, end: endDate, limit: 7 });
        dataPoints = (data.records || []).map(r => {
          const n = normalizer.normalizeRecovery(r);
          return { date: n.date, value: n.recoveryScore };
        });
        values = dataPoints.map(d => d.value);
        break;

      case 'strain':
        data = await whoopClient.getCycles({ start: startDate, end: endDate, limit: 7 });
        dataPoints = (data.records || []).map(c => {
          const n = normalizer.normalizeCycle(c);
          return { date: n.start?.split('T')[0], value: n.strain };
        });
        values = dataPoints.map(d => d.value);
        break;

      case 'sleep':
        data = await whoopClient.getSleep({ start: startDate, end: endDate, limit: 7 });
        dataPoints = (data.records || []).map(s => {
          const n = normalizer.normalizeSleep(s);
          return { date: n.date, value: n.totalSleepTime ? n.totalSleepTime / 3600 : null }; // Hours
        });
        values = dataPoints.map(d => d.value);
        break;
    }

    const validValues = values.filter(v => v !== null && v !== undefined);
    const avg = validValues.length > 0
      ? Math.round((validValues.reduce((a, b) => a + b, 0) / validValues.length) * 10) / 10
      : null;

    const trend = normalizer.calculateTrend(values);
    const outliers = normalizer.findOutliers(dataPoints, 'value');

    const result = {
      metric,
      period: '7_days',
      average: avg,
      unit: metric === 'sleep' ? 'hours' : (metric === 'recovery' ? 'percent' : 'score'),
      trendDirection: trend.direction,
      trendChange: trend.change,
      dataPoints: dataPoints.slice(0, 7),
      notableOutliers: outliers.slice(0, 3)
    };

    setCache(cacheKey, result);
    return result;

  } catch (error) {
    console.error(`[WhoopData] Failed to get week trends for ${metric}:`, error.message);
    throw error;
  }
}

/**
 * Sync latest data to database (for cron job)
 */
export async function syncToDatabase() {
  console.log('[WhoopData] Starting sync to database');

  try {
    const [cyclesData, recoveryData, sleepData] = await Promise.all([
      whoopClient.getCycles({ limit: 3 }),
      whoopClient.getRecovery({ limit: 3 }),
      whoopClient.getSleep({ limit: 3 })
    ]);

    const records = recoveryData.records || [];
    let synced = 0;

    for (const recovery of records) {
      const normalizedRecovery = normalizer.normalizeRecovery(recovery);
      if (!normalizedRecovery?.date) continue;

      // Find matching sleep
      const sleep = (sleepData.records || []).find(s => {
        const sleepDate = s.start?.split('T')[0];
        return sleepDate === normalizedRecovery.date;
      });
      const normalizedSleep = sleep ? normalizer.normalizeSleep(sleep) : null;

      // Find matching cycle
      const cycle = (cyclesData.records || []).find(c => {
        const cycleDate = c.start?.split('T')[0];
        return cycleDate === normalizedRecovery.date;
      });
      const normalizedCycle = cycle ? normalizer.normalizeCycle(cycle) : null;

      await snapshots.saveSnapshot({
        date: normalizedRecovery.date,
        recoveryScore: normalizedRecovery.recoveryScore,
        recoveryState: normalizedRecovery.state,
        strain: normalizedCycle?.strain,
        sleepDuration: normalizedSleep?.totalSleepTime,
        sleepDebt: normalizedSleep?.sleepDebt,
        sleepEfficiency: normalizedSleep?.sleepEfficiency,
        sleepDisturbances: normalizedSleep?.disturbances,
        hrv: normalizedRecovery.hrv,
        restingHr: normalizedRecovery.restingHr,
        rawData: { recovery, sleep, cycle }
      });

      synced++;
    }

    console.log(`[WhoopData] Synced ${synced} records to database`);
    return { success: true, synced };

  } catch (error) {
    console.error('[WhoopData] Sync failed:', error.message);
    throw error;
  }
}
