import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { query, getPool } from './client.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MIGRATIONS_DIR = path.join(__dirname, '../../migrations');

async function ensureMigrationsTable() {
  await query(`
    CREATE TABLE IF NOT EXISTS migrations (
      id SERIAL PRIMARY KEY,
      name VARCHAR(255) NOT NULL UNIQUE,
      applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
  `);
}

async function getAppliedMigrations() {
  const result = await query('SELECT name FROM migrations ORDER BY id');
  return result.rows.map(row => row.name);
}

async function applyMigration(name, sql) {
  console.log(`[Migration] Applying: ${name}`);
  await query(sql);
  await query('INSERT INTO migrations (name) VALUES ($1)', [name]);
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
    .catch((error) => {
      console.error('[Migration] Failed:', error);
      process.exit(1);
    });
}
