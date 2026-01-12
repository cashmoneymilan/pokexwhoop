/**
 * MCP Server implementation with SSE transport
 * Exposes WHOOP health data as MCP tools for Poke AI
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema
} from '@modelcontextprotocol/sdk/types.js';

import * as whoopData from '../services/whoop-data.js';

// Tool definitions
const TOOLS = [
  {
    name: 'get_today_summary',
    description: 'Get a comprehensive summary of today\'s WHOOP data including recovery score, strain, sleep duration and quality, HRV, resting heart rate, and recommended strain range.',
    inputSchema: {
      type: 'object',
      properties: {},
      required: []
    }
  },
  {
    name: 'get_latest_recovery',
    description: 'Get the most recent recovery data including recovery score (0-100), HRV (heart rate variability in milliseconds), resting heart rate, and recovery state (green/yellow/red).',
    inputSchema: {
      type: 'object',
      properties: {},
      required: []
    }
  },
  {
    name: 'get_last_sleep',
    description: 'Get the most recent sleep data including total sleep time, sleep debt, sleep efficiency percentage, number of disturbances, and time spent in each sleep stage (REM, deep, light, awake).',
    inputSchema: {
      type: 'object',
      properties: {},
      required: []
    }
  },
  {
    name: 'get_week_trends',
    description: 'Get 7-day trends for a specific health metric. Returns the weekly average, trend direction (improving/stable/declining), percentage change, daily data points, and any notable outliers.',
    inputSchema: {
      type: 'object',
      properties: {
        metric: {
          type: 'string',
          enum: ['recovery', 'strain', 'sleep'],
          description: 'The metric to analyze: "recovery" (recovery score), "strain" (daily strain), or "sleep" (total sleep hours)'
        }
      },
      required: ['metric']
    }
  }
];

// Create MCP server instance
export function createMcpServer() {
  const server = new Server(
    {
      name: 'whoop-mcp-server',
      version: '1.0.0'
    },
    {
      capabilities: {
        tools: {}
      }
    }
  );

  // Handle list tools request
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools: TOOLS };
  });

  // Handle tool execution
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params;

    console.log(`[MCP] Tool invoked: ${name}`, args || {});

    try {
      let result;

      switch (name) {
        case 'get_today_summary':
          result = await whoopData.getTodaySummary();
          break;

        case 'get_latest_recovery':
          result = await whoopData.getLatestRecovery();
          break;

        case 'get_last_sleep':
          result = await whoopData.getLastSleep();
          break;

        case 'get_week_trends':
          if (!args?.metric) {
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({ error: 'missing_parameter', message: 'The "metric" parameter is required. Use one of: recovery, strain, sleep' })
              }],
              isError: true
            };
          }
          result = await whoopData.getWeekTrends(args.metric);
          break;

        default:
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({ error: 'unknown_tool', message: `Unknown tool: ${name}` })
            }],
            isError: true
          };
      }

      return {
        content: [{
          type: 'text',
          text: JSON.stringify(result, null, 2)
        }]
      };

    } catch (error) {
      console.error(`[MCP] Tool error (${name}):`, error.message);

      return {
        content: [{
          type: 'text',
          text: JSON.stringify({
            error: error.code || 'tool_error',
            message: error.message
          })
        }],
        isError: true
      };
    }
  });

  return server;
}

// SSE connection handler for Express
export function createSseHandler(server) {
  // Store transports by session
  const transports = new Map();

  return {
    // SSE endpoint handler
    handleSse: async (req, res) => {
      console.log('[MCP] New SSE connection');

      // Set SSE headers
      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('Connection', 'keep-alive');
      res.setHeader('X-Accel-Buffering', 'no');

      // Create transport
      const transport = new SSEServerTransport('/mcp/messages', res);
      const sessionId = crypto.randomUUID();
      transports.set(sessionId, transport);

      // Send session ID to client
      res.write(`data: ${JSON.stringify({ type: 'session', sessionId })}\n\n`);

      // Connect server to transport
      await server.connect(transport);

      // Handle client disconnect
      req.on('close', () => {
        console.log('[MCP] SSE connection closed');
        transports.delete(sessionId);
      });
    },

    // Message endpoint handler
    handleMessage: async (req, res) => {
      const sessionId = req.headers['x-session-id'];
      const transport = transports.get(sessionId);

      if (!transport) {
        return res.status(400).json({ error: 'invalid_session', message: 'Invalid or expired session' });
      }

      try {
        await transport.handlePostMessage(req, res);
      } catch (error) {
        console.error('[MCP] Message handling error:', error);
        res.status(500).json({ error: 'message_error', message: error.message });
      }
    }
  };
}

// Import crypto for session IDs
import crypto from 'crypto';
