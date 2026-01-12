import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { getDb, exec, query, saveDb } from './client.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MIGRATIONS_DIR = path.join(__dirname, '../../migrations');

async function ensureMigrationsTable() {
  const db = await getDb();
  db.exec(`
    CREATE TABLE IF NOT EXISTS migrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      applied_at TEXT DEFAULT (datetime('now'))
    )
  `);
  saveDb();
}

async function getAppliedMigrations() {
  const result = await query('SELECT name FROM migrations ORDER BY id');
  return result.rows.map(row => row.name);
}

async function applyMigration(name, sql) {
  const db = await getDb();
  console.log(`[Migration] Applying: ${name}`);

  db.exec(sql);
  db.run('INSERT INTO migrations (name) VALUES (?)', [name]);
  saveDb();

  console.log(`[Migration] Applied: ${name}`);
}

export async function runMigrations() {
  try {
    await ensureMigrationsTable();

    const applied = await getAppliedMigrations();
    const files = fs.readdirSync(MIGRATIONS_DIR)
      .filter(f => f.endsWith('.sql'))
      .sort();

    for (const file of files) {
      if (!applied.includes(file)) {
        const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, file), 'utf-8');
        await applyMigration(file, sql);
      }
    }

    console.log('[Migration] All migrations complete');
  } catch (error) {
    console.error('[Migration] Error:', error.message);
    throw error;
  }
}

// Run directly if called as script
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  runMigrations()
    .then(() => {
      console.log('[Migration] Done');
      process.exit(0);
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
