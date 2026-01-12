import { getDb } from './client.js';

export function getToken() {
  const db = getDb();
  const row = db.prepare('SELECT * FROM whoop_tokens WHERE id = 1').get();
  return row || null;
}

export function saveToken({ accessToken, refreshToken, expiresAt, scope }) {
  const db = getDb();

  // Convert Date to ISO string if needed
  const expiresAtStr = expiresAt instanceof Date ? expiresAt.toISOString() : expiresAt;

  const stmt = db.prepare(`
    INSERT INTO whoop_tokens (id, access_token, refresh_token, expires_at, scope, updated_at)
    VALUES (1, ?, ?, ?, ?, datetime('now'))
    ON CONFLICT(id) DO UPDATE SET
      access_token = excluded.access_token,
      refresh_token = excluded.refresh_token,
      expires_at = excluded.expires_at,
      scope = excluded.scope,
      updated_at = datetime('now')
  `);

  stmt.run(accessToken, refreshToken, expiresAtStr, scope);
  console.log('[Token] Saved/updated token, expires at:', expiresAtStr);

  return getToken();
}

export function tokenExists() {
  const db = getDb();
  const row = db.prepare('SELECT id FROM whoop_tokens WHERE id = 1').get();
  return !!row;
}
