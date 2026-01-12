import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { getDb } from './client.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MIGRATIONS_DIR = path.join(__dirname, '../../migrations');

function ensureMigrationsTable() {
  const db = getDb();
  db.exec(`
    CREATE TABLE IF NOT EXISTS migrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      applied_at TEXT DEFAULT (datetime('now'))
    )
  `);
}

function getAppliedMigrations() {
  const db = getDb();
  const rows = db.prepare('SELECT name FROM migrations ORDER BY id').all();
  return rows.map(row => row.name);
}

function applyMigration(name, sql) {
  const db = getDb();
  console.log(`[Migration] Applying: ${name}`);

  // Execute migration in a transaction
  const transaction = db.transaction(() => {
    db.exec(sql);
    db.prepare('INSERT INTO migrations (name) VALUES (?)').run(name);
  });

  transaction();
  console.log(`[Migration] Applied: ${name}`);
}

export function runMigrations() {
  try {
    ensureMigrationsTable();

    const applied = getAppliedMigrations();
    const files = fs.readdirSync(MIGRATIONS_DIR)
      .filter(f => f.endsWith('.sql'))
      .sort();

    for (const file of files) {
      if (!applied.includes(file)) {
        const sql = fs.readFileSync(path.join(MIGRATIONS_DIR, file), 'utf-8');
        applyMigration(file, sql);
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
  runMigrations();
  console.log('[Migration] Done');
  process.exit(0);
}
