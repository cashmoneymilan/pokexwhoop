import { getDb, saveDb, queryOne } from './client.js';

export async function getToken() {
  return await queryOne('SELECT * FROM whoop_tokens WHERE id = 1');
}

export async function saveToken({ accessToken, refreshToken, expiresAt, scope }) {
  const db = await getDb();

  // Convert Date to ISO string if needed
  const expiresAtStr = expiresAt instanceof Date ? expiresAt.toISOString() : expiresAt;

  // Check if token exists
  const existing = await queryOne('SELECT id FROM whoop_tokens WHERE id = 1');

  if (existing) {
    db.run(`
      UPDATE whoop_tokens SET
        access_token = ?,
        refresh_token = ?,
        expires_at = ?,
        scope = ?,
        updated_at = datetime('now')
      WHERE id = 1
    `, [accessToken, refreshToken, expiresAtStr, scope]);
  } else {
    db.run(`
      INSERT INTO whoop_tokens (id, access_token, refresh_token, expires_at, scope)
      VALUES (1, ?, ?, ?, ?)
    `, [accessToken, refreshToken, expiresAtStr, scope]);
  }

  saveDb();
  console.log('[Token] Saved/updated token, expires at:', expiresAtStr);

  return await getToken();
}

export async function tokenExists() {
  const row = await queryOne('SELECT id FROM whoop_tokens WHERE id = 1');
  return !!row;
}
