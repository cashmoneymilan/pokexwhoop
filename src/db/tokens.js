import { query } from './client.js';

export async function getToken() {
  const result = await query('SELECT * FROM whoop_tokens WHERE id = 1');
  return result.rows[0] || null;
}

export async function saveToken({ accessToken, refreshToken, expiresAt, scope }) {
  const result = await query(`
    INSERT INTO whoop_tokens (id, access_token, refresh_token, expires_at, scope, updated_at)
    VALUES (1, $1, $2, $3, $4, CURRENT_TIMESTAMP)
    ON CONFLICT (id) DO UPDATE SET
      access_token = EXCLUDED.access_token,
      refresh_token = EXCLUDED.refresh_token,
      expires_at = EXCLUDED.expires_at,
      scope = EXCLUDED.scope,
      updated_at = CURRENT_TIMESTAMP
    RETURNING *
  `, [accessToken, refreshToken, expiresAt, scope]);

  console.log('[Token] Saved/updated token, expires at:', expiresAt);
  return result.rows[0];
}

export async function tokenExists() {
  const result = await query('SELECT id FROM whoop_tokens WHERE id = 1');
  return result.rows.length > 0;
}
