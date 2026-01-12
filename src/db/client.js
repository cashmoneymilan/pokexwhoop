import initSqlJs from 'sql.js';
import path from 'path';
import fs from 'fs';

let db = null;
let SQL = null;
const DB_PATH = process.env.DB_PATH || './data/whoop.db';

async function ensureDbDir() {
  const dbDir = path.dirname(DB_PATH);
  if (!fs.existsSync(dbDir)) {
    fs.mkdirSync(dbDir, { recursive: true });
  }
}

export async function getDb() {
  if (db) return db;

  await ensureDbDir();

  // Initialize SQL.js
  if (!SQL) {
    SQL = await initSqlJs();
  }

  // Load existing database or create new one
  if (fs.existsSync(DB_PATH)) {
    const buffer = fs.readFileSync(DB_PATH);
    db = new SQL.Database(buffer);
    console.log(`[DB] Loaded SQLite from ${DB_PATH}`);
  } else {
    db = new SQL.Database();
    console.log(`[DB] Created new SQLite database`);
  }

  return db;
}

export function saveDb() {
  if (db) {
    const data = db.export();
    const buffer = Buffer.from(data);
    fs.writeFileSync(DB_PATH, buffer);
  }
}

export async function query(sql, params = []) {
  const database = await getDb();
  const start = Date.now();

  try {
    const isSelect = sql.trim().toUpperCase().startsWith('SELECT');

    if (isSelect) {
      const stmt = database.prepare(sql);
      stmt.bind(params);

      const rows = [];
      while (stmt.step()) {
        const row = stmt.getAsObject();
        rows.push(row);
      }
      stmt.free();

      const duration = Date.now() - start;
      if (process.env.LOG_LEVEL === 'debug') {
        console.log('[DB] Query executed', { duration: `${duration}ms`, rows: rows.length });
      }

      return { rows, rowCount: rows.length };
    } else {
      database.run(sql, params);
      saveDb(); // Persist changes

      const duration = Date.now() - start;
      if (process.env.LOG_LEVEL === 'debug') {
        console.log('[DB] Query executed', { duration: `${duration}ms` });
      }

      return { rows: [], rowCount: database.getRowsModified() };
    }
  } catch (error) {
    console.error('[DB] Query error:', error.message);
    throw error;
  }
}

export async function queryOne(sql, params = []) {
  const result = await query(sql, params);
  return result.rows[0] || null;
}

export async function exec(sql) {
  const database = await getDb();
  database.exec(sql);
  saveDb();
}

export async function checkConnection() {
  try {
    await getDb();
    return true;
  } catch (error) {
    console.error('[DB] Connection check failed:', error.message);
    return false;
  }
}
