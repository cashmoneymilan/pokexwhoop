/**
 * API key authentication middleware
 */

export function requireApiKey(req, res, next) {
  const apiKey = req.headers['x-api-key'];
  const expectedKey = process.env.SERVER_API_KEY;

  if (!expectedKey) {
    console.error('[Auth] SERVER_API_KEY not configured');
    return res.status(500).json({
      error: 'server_error',
      message: 'Server API key not configured'
    });
  }

  if (!apiKey) {
    return res.status(401).json({
      error: 'missing_api_key',
      message: 'x-api-key header is required'
    });
  }

  // Constant-time comparison to prevent timing attacks
  if (!timingSafeEqual(apiKey, expectedKey)) {
    return res.status(403).json({
      error: 'invalid_api_key',
      message: 'Invalid API key'
    });
  }

  next();
}

// Constant-time string comparison
function timingSafeEqual(a, b) {
  if (a.length !== b.length) {
    return false;
  }

  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}
