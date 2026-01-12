import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

let db = null;

export function getDb() {
  if (!db) {
    // Ensure data directory exists
    const dbPath = process.env.DB_PATH || './data/whoop.db';
    const dbDir = path.dirname(dbPath);

    if (!fs.existsSync(dbDir)) {
      fs.mkdirSync(dbDir, { recursive: true });
    }

    db = new Database(dbPath);
    db.pragma('journal_mode = WAL');

    console.log(`[DB] Connected to SQLite at ${dbPath}`);
  }
  return db;
}

export function query(sql, params = []) {
  const database = getDb();
  const start = Date.now();

  try {
    // Determine if it's a SELECT query
    const isSelect = sql.trim().toUpperCase().startsWith('SELECT');

    let result;
    if (isSelect) {
      result = database.prepare(sql).all(...params);
    } else {
      result = database.prepare(sql).run(...params);
    }

    const duration = Date.now() - start;
    if (process.env.LOG_LEVEL === 'debug') {
      console.log('[DB] Query executed', { duration: `${duration}ms` });
    }

    // Return in a format compatible with the rest of the codebase
    if (isSelect) {
      return { rows: result, rowCount: result.length };
    } else {
      return { rows: [], rowCount: result.changes };
    }
  } catch (error) {
    console.error('[DB] Query error:', error.message);
    throw error;
  }
}

export function queryOne(sql, params = []) {
  const database = getDb();
  return database.prepare(sql).get(...params);
}

export async function checkConnection() {
  try {
    const database = getDb();
    database.prepare('SELECT 1').get();
    return true;
  } catch (error) {
    console.error('[DB] Connection check failed:', error.message);
    return false;
  }
}
