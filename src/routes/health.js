import { Router } from 'express';
import { checkConnection } from '../db/client.js';
import { tokenExists, getToken } from '../db/tokens.js';
import { getLastSyncTime } from '../db/snapshots.js';

const router = Router();

/**
 * GET /health
 * Health check endpoint for monitoring
 */
router.get('/', async (req, res) => {
  const checks = {
    database: false,
    tokenPresent: false,
    tokenExpiresAt: null,
    lastWhoopSync: null
  };

  let status = 'ok';

  try {
    // Check database connection
    checks.database = await checkConnection();
    if (!checks.database) {
      status = 'error';
    }

    // Check token presence
    checks.tokenPresent = await tokenExists();
    if (!checks.tokenPresent) {
      status = status === 'ok' ? 'degraded' : status;
    }

    // Get token expiry
    if (checks.tokenPresent) {
      const token = await getToken();
      checks.tokenExpiresAt = token?.expires_at || null;

      // Check if token is expired or expiring soon
      if (token?.expires_at) {
        const expiresAt = new Date(token.expires_at);
        const now = new Date();
        if (expiresAt < now) {
          status = 'degraded';
          checks.tokenExpired = true;
        }
      }
    }

    // Get last sync time
    checks.lastWhoopSync = await getLastSyncTime();

  } catch (error) {
    console.error('[Health] Check failed:', error.message);
    status = 'error';
    checks.error = error.message;
  }

  const httpStatus = status === 'error' ? 503 : 200;

  res.status(httpStatus).json({
    status,
    timestamp: new Date().toISOString(),
    ...checks
  });
});

export default router;
