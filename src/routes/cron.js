import { Router } from 'express';
import { syncToDatabase } from '../services/whoop-data.js';
import { tokenExists } from '../db/tokens.js';

const router = Router();

/**
 * POST /cron/sync
 * Syncs WHOOP data to the database
 * Protected by SERVER_API_KEY
 */
router.post('/sync', async (req, res) => {
  console.log('[Cron] Sync triggered');

  try {
    // Check if we have a token
    const hasToken = await tokenExists();
    if (!hasToken) {
      return res.status(400).json({
        success: false,
        error: 'no_token',
        message: 'No WHOOP token found. Please authorize first at /oauth/whoop/start'
      });
    }

    // Run sync
    const result = await syncToDatabase();

    res.json({
      success: true,
      synced: result.synced,
      timestamp: new Date().toISOString()
    });

  } catch (error) {
    console.error('[Cron] Sync failed:', error);

    res.status(500).json({
      success: false,
      error: error.code || 'sync_error',
      message: error.message
    });
  }
});

export default router;
