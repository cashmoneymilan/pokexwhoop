import { Router } from 'express';
import crypto from 'crypto';
import { saveToken } from '../db/tokens.js';

const router = Router();

// In-memory state storage (sufficient for single-user)
const stateStore = new Map();
const STATE_EXPIRY_MS = 10 * 60 * 1000; // 10 minutes

const WHOOP_AUTH_URL = 'https://api.prod.whoop.com/oauth/oauth2/auth';
const WHOOP_TOKEN_URL = 'https://api.prod.whoop.com/oauth/oauth2/token';

// Required scopes for WHOOP data access
const SCOPES = [
  'read:recovery',
  'read:cycles',
  'read:sleep',
  'read:workout',
  'read:profile',
  'read:body_measurement',
  'offline'
].join(' ');

function cleanExpiredStates() {
  const now = Date.now();
  for (const [state, data] of stateStore.entries()) {
    if (now - data.created > STATE_EXPIRY_MS) {
      stateStore.delete(state);
    }
  }
}

/**
 * GET /oauth/whoop/start
 * Initiates OAuth flow by redirecting to WHOOP authorization page
 */
router.get('/whoop/start', (req, res) => {
  cleanExpiredStates();

  const state = crypto.randomBytes(32).toString('hex');
  stateStore.set(state, { created: Date.now() });

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: process.env.WHOOP_CLIENT_ID,
    redirect_uri: process.env.WHOOP_REDIRECT_URI,
    scope: SCOPES,
    state: state
  });

  const authUrl = `${WHOOP_AUTH_URL}?${params.toString()}`;
  console.log('[OAuth] Starting authorization flow');
  res.redirect(authUrl);
});

/**
 * GET /oauth/whoop/callback
 * Handles OAuth callback, exchanges code for tokens, stores in database
 */
router.get('/whoop/callback', async (req, res) => {
  const { code, state, error, error_description } = req.query;

  // Handle OAuth errors
  if (error) {
    console.error('[OAuth] Authorization error:', error, error_description);
    return res.status(400).send(errorPage(
      'Authorization Failed',
      error_description || error
    ));
  }

  // Validate state
  if (!state || !stateStore.has(state)) {
    console.error('[OAuth] Invalid or missing state parameter');
    return res.status(400).send(errorPage(
      'Invalid State',
      'The authorization request has expired or is invalid. Please try again.'
    ));
  }
  stateStore.delete(state);

  // Validate code
  if (!code) {
    console.error('[OAuth] Missing authorization code');
    return res.status(400).send(errorPage(
      'Missing Code',
      'No authorization code received from WHOOP.'
    ));
  }

  try {
    // Exchange code for tokens
    const tokenResponse = await fetch(WHOOP_TOKEN_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code: code,
        redirect_uri: process.env.WHOOP_REDIRECT_URI,
        client_id: process.env.WHOOP_CLIENT_ID,
        client_secret: process.env.WHOOP_CLIENT_SECRET
      })
    });

    if (!tokenResponse.ok) {
      const errorData = await tokenResponse.text();
      console.error('[OAuth] Token exchange failed:', tokenResponse.status, errorData);
      return res.status(400).send(errorPage(
        'Token Exchange Failed',
        'Failed to exchange authorization code for tokens. Please try again.'
      ));
    }

    const tokens = await tokenResponse.json();

    // Calculate expiry time
    const expiresAt = new Date(Date.now() + (tokens.expires_in * 1000));

    // Save tokens to database
    await saveToken({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
      expiresAt: expiresAt,
      scope: tokens.scope || SCOPES
    });

    console.log('[OAuth] Successfully stored tokens');
    res.send(successPage());

  } catch (error) {
    console.error('[OAuth] Callback error:', error);
    res.status(500).send(errorPage(
      'Server Error',
      'An unexpected error occurred. Please try again.'
    ));
  }
});

function successPage() {
  return `<!DOCTYPE html>
<html>
<head>
  <title>WHOOP Connected</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           display: flex; justify-content: center; align-items: center; height: 100vh;
           margin: 0; background: #1a1a2e; color: #fff; }
    .container { text-align: center; padding: 40px; }
    .icon { font-size: 64px; margin-bottom: 20px; }
    h1 { margin: 0 0 10px; color: #00f5d4; }
    p { color: #888; margin: 0; }
  </style>
</head>
<body>
  <div class="container">
    <div class="icon">✓</div>
    <h1>WHOOP Connected</h1>
    <p>Your WHOOP account is now connected. You can close this window.</p>
  </div>
</body>
</html>`;
}

function errorPage(title, message) {
  return `<!DOCTYPE html>
<html>
<head>
  <title>Connection Error</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           display: flex; justify-content: center; align-items: center; height: 100vh;
           margin: 0; background: #1a1a2e; color: #fff; }
    .container { text-align: center; padding: 40px; max-width: 400px; }
    .icon { font-size: 64px; margin-bottom: 20px; }
    h1 { margin: 0 0 10px; color: #ff6b6b; }
    p { color: #888; margin: 0; }
    a { color: #00f5d4; text-decoration: none; display: inline-block; margin-top: 20px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="icon">✗</div>
    <h1>${title}</h1>
    <p>${message}</p>
    <a href="/oauth/whoop/start">Try Again →</a>
  </div>
</body>
</html>`;
}

export default router;
