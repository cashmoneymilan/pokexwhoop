/**
 * WHOOP MCP Server
 * Main entry point
 */

import express from 'express';
import { runMigrations } from './db/migrate.js';
import { createMcpServer, createSseHandler } from './mcp/server.js';
import oauthRoutes from './routes/oauth.js';
import healthRoutes from './routes/health.js';
import cronRoutes from './routes/cron.js';
import { requireApiKey } from './middleware/auth.js';

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());

// Request logging
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = Date.now() - start;
    console.log(`[HTTP] ${req.method} ${req.path} ${res.statusCode} (${duration}ms)`);
  });
  next();
});

// Public routes (no auth required)
app.get('/', (req, res) => {
  res.json({
    name: 'WHOOP MCP Server',
    version: '1.0.0',
    endpoints: {
      health: '/health',
      oauth_start: '/oauth/whoop/start',
      mcp_sse: '/mcp/sse'
    }
  });
});

app.use('/health', healthRoutes);
app.use('/oauth', oauthRoutes);

// Protected routes (require API key)
app.use('/cron', requireApiKey, cronRoutes);

// MCP Server setup
const mcpServer = createMcpServer();
const sseHandler = createSseHandler(mcpServer);

// MCP SSE endpoint (requires API key)
app.get('/mcp/sse', requireApiKey, sseHandler.handleSse);
app.post('/mcp/messages', requireApiKey, sseHandler.handleMessage);

// Error handling
app.use((err, req, res, next) => {
  console.error('[Error]', err);
  res.status(500).json({
    error: 'internal_error',
    message: process.env.NODE_ENV === 'production' ? 'Internal server error' : err.message
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    error: 'not_found',
    message: `Route ${req.method} ${req.path} not found`
  });
});

// Startup
async function start() {
  try {
    // Run database migrations
    console.log('[Startup] Running database migrations...');
    await runMigrations();

    // Start server
    app.listen(PORT, '0.0.0.0', () => {
      console.log(`[Startup] Server running on port ${PORT}`);
      console.log(`[Startup] Environment: ${process.env.NODE_ENV || 'development'}`);
      console.log('[Startup] Ready to accept connections');
    });

  } catch (error) {
    console.error('[Startup] Failed to start server:', error);
    process.exit(1);
  }
}

start();
