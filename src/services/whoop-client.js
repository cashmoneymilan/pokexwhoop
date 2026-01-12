import { getToken, saveToken } from '../db/tokens.js';

const WHOOP_API_BASE = 'https://api.prod.whoop.com/developer';
const WHOOP_TOKEN_URL = 'https://api.prod.whoop.com/oauth/oauth2/token';

// Refresh token 5 minutes before expiry
const TOKEN_REFRESH_BUFFER_MS = 5 * 60 * 1000;

// Rate limiting
const MIN_REQUEST_INTERVAL_MS = 100;
let lastRequestTime = 0;

class WhoopClient {
  constructor() {
    this.token = null;
  }

  async ensureValidToken() {
    // Load token from DB
    const dbToken = await getToken();

    if (!dbToken) {
      throw new WhoopError('NO_TOKEN', 'No WHOOP token found. Please authorize at /oauth/whoop/start');
    }

    const expiresAt = new Date(dbToken.expires_at);
    const now = new Date();

    // Check if token needs refresh
    if (expiresAt.getTime() - now.getTime() < TOKEN_REFRESH_BUFFER_MS) {
      console.log('[WHOOP] Token expiring soon, refreshing...');
      await this.refreshToken(dbToken.refresh_token);
      // Reload token after refresh
      this.token = await getToken();
    } else {
      this.token = dbToken;
    }

    return this.token.access_token;
  }

  async refreshToken(refreshToken) {
    const startTime = Date.now();

    try {
      const response = await fetch(WHOOP_TOKEN_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: new URLSearchParams({
          grant_type: 'refresh_token',
          refresh_token: refreshToken,
          client_id: process.env.WHOOP_CLIENT_ID,
          client_secret: process.env.WHOOP_CLIENT_SECRET
        })
      });

      const duration = Date.now() - startTime;
      console.log(`[WHOOP] Token refresh completed in ${duration}ms`);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('[WHOOP] Token refresh failed:', response.status, errorText);
        throw new WhoopError('TOKEN_REFRESH_FAILED', 'Failed to refresh token. Re-authorization may be required.');
      }

      const tokens = await response.json();
      const expiresAt = new Date(Date.now() + (tokens.expires_in * 1000));

      await saveToken({
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
        expiresAt: expiresAt,
        scope: tokens.scope
      });

      console.log('[WHOOP] Token refreshed successfully');

    } catch (error) {
      if (error instanceof WhoopError) throw error;
      console.error('[WHOOP] Token refresh error:', error);
      throw new WhoopError('TOKEN_REFRESH_ERROR', error.message);
    }
  }

  async request(endpoint, options = {}) {
    const accessToken = await this.ensureValidToken();

    // Rate limiting
    const now = Date.now();
    const timeSinceLastRequest = now - lastRequestTime;
    if (timeSinceLastRequest < MIN_REQUEST_INTERVAL_MS) {
      await sleep(MIN_REQUEST_INTERVAL_MS - timeSinceLastRequest);
    }
    lastRequestTime = Date.now();

    const url = `${WHOOP_API_BASE}${endpoint}`;
    const startTime = Date.now();

    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
          ...options.headers
        }
      });

      const duration = Date.now() - startTime;
      console.log(`[WHOOP] ${options.method || 'GET'} ${endpoint} - ${response.status} (${duration}ms)`);

      if (response.status === 429) {
        // Rate limited - wait and retry
        const retryAfter = parseInt(response.headers.get('Retry-After') || '60', 10);
        console.log(`[WHOOP] Rate limited, retrying after ${retryAfter}s`);
        await sleep(retryAfter * 1000);
        return this.request(endpoint, options);
      }

      if (response.status === 401) {
        // Token might be invalid, try refreshing
        console.log('[WHOOP] 401 received, attempting token refresh');
        const dbToken = await getToken();
        if (dbToken) {
          await this.refreshToken(dbToken.refresh_token);
          return this.request(endpoint, options);
        }
        throw new WhoopError('UNAUTHORIZED', 'Token is invalid. Please re-authorize.');
      }

      if (!response.ok) {
        const errorText = await response.text();
        throw new WhoopError('API_ERROR', `WHOOP API error: ${response.status} - ${errorText}`);
      }

      return response.json();

    } catch (error) {
      if (error instanceof WhoopError) throw error;
      console.error(`[WHOOP] Request error for ${endpoint}:`, error.message);
      throw new WhoopError('REQUEST_FAILED', error.message);
    }
  }

  // --- API Methods ---

  async getProfile() {
    return this.request('/v1/user/profile/basic');
  }

  async getCycles(params = {}) {
    const query = new URLSearchParams();
    if (params.start) query.set('start', params.start);
    if (params.end) query.set('end', params.end);
    if (params.limit) query.set('limit', params.limit.toString());

    const queryString = query.toString();
    return this.request(`/v1/cycle${queryString ? '?' + queryString : ''}`);
  }

  async getRecovery(params = {}) {
    const query = new URLSearchParams();
    if (params.start) query.set('start', params.start);
    if (params.end) query.set('end', params.end);
    if (params.limit) query.set('limit', params.limit.toString());

    const queryString = query.toString();
    return this.request(`/v1/recovery${queryString ? '?' + queryString : ''}`);
  }

  async getSleep(params = {}) {
    const query = new URLSearchParams();
    if (params.start) query.set('start', params.start);
    if (params.end) query.set('end', params.end);
    if (params.limit) query.set('limit', params.limit.toString());

    const queryString = query.toString();
    return this.request(`/v1/activity/sleep${queryString ? '?' + queryString : ''}`);
  }

  async getWorkouts(params = {}) {
    const query = new URLSearchParams();
    if (params.start) query.set('start', params.start);
    if (params.end) query.set('end', params.end);
    if (params.limit) query.set('limit', params.limit.toString());

    const queryString = query.toString();
    return this.request(`/v1/activity/workout${queryString ? '?' + queryString : ''}`);
  }
}

class WhoopError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'WhoopError';
    this.code = code;
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Singleton instance
export const whoopClient = new WhoopClient();
export { WhoopError };
