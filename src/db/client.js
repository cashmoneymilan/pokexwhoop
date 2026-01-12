import pg from 'pg';

const { Pool } = pg;

let pool = null;

export function getPool() {
  if (!pool) {
    pool = new Pool({
      connectionString: process.env.DATABASE_URL,
      ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: false } : false
    });
  }
  return pool;
}

export async function query(text, params) {
  const pool = getPool();
  const start = Date.now();
  const result = await pool.query(text, params);
  const duration = Date.now() - start;

  if (process.env.LOG_LEVEL === 'debug') {
    console.log('[DB] Query executed', { duration: `${duration}ms`, rows: result.rowCount });
  }

  return result;
}

export async function checkConnection() {
  try {
    await query('SELECT 1');
    return true;
  } catch (error) {
    console.error('[DB] Connection check failed:', error.message);
    return false;
  }
}
