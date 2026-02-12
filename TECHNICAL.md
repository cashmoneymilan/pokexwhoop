# Technical Appendix

Deep dive into OAuth flow, API details, rate limits, and endpoint schemas.

---

## OAuth 2.0 Flow

### Overview

PokeXWhoop uses OAuth 2.0 Authorization Code flow with WHOOP's API.

```
User                    PokeXWhoop              WHOOP
  │                         │                     │
  │──GET /oauth/whoop/start─▶│                     │
  │                         │──redirect to auth───▶│
  │                         │                     │
  │◀─────────────────────────────login + consent──│
  │                         │                     │
  │──callback with code─────▶│                     │
  │                         │──POST /token────────▶│
  │                         │◀───access + refresh──│
  │◀──"Authorization        │                     │
  │    complete!"           │                     │
```

### Endpoints

| Endpoint | URL |
|----------|-----|
| Authorization | `https://api.prod.whoop.com/oauth/oauth2/auth` |
| Token Exchange | `https://api.prod.whoop.com/oauth/oauth2/token` |
| API Base | `https://api.prod.whoop.com/developer` |

### Required Scopes

```
offline read:recovery read:sleep read:workout read:cycles read:profile
```

**Critical:** The `offline` scope is required for refresh tokens. Without it, tokens expire and cannot be renewed.

### Token Lifecycle

| Token | Lifespan | Refresh |
|-------|----------|---------|
| Access Token | ~1 hour | Automatic via refresh token |
| Refresh Token | ~30 days | Must re-authorize if expired |

### Token Refresh Strategy

PokeXWhoop uses triple-redundant refresh:

1. **Background task** — Checks every 30 minutes, refreshes if <5 min remaining
2. **On API call** — Auto-refresh before any WHOOP API request if expiring
3. **Health endpoint** — `/health` triggers refresh if <1 hour remaining
4. **Keep-alive endpoint** — `/keep-alive` for cron-based proactive refresh

### Token Storage

Tokens are stored in Turso (SQLite cloud) with schema:

```sql
CREATE TABLE tokens (
    id INTEGER PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    scope TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
)
```

---

## WHOOP API Reference

### Base URL

```
https://api.prod.whoop.com/developer
```

### Authentication

All requests require Bearer token:

```
Authorization: Bearer {access_token}
```

### Endpoints Used

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v2/recovery` | GET | Recovery scores (HRV, resting HR) |
| `/v2/activity/sleep` | GET | Sleep data (duration, efficiency, stages) |
| `/v2/cycle` | GET | Strain/cycle data |
| `/v2/activity/workout` | GET | Workout activities |

### Rate Limits

WHOOP does not publish official rate limits. Observed behavior:

- **Soft limit:** ~100 requests/minute
- **429 responses:** Occasional during rapid polling
- **Recommended:** Cache responses, poll no more than once per minute

### Response Pagination

All list endpoints return:

```json
{
  "records": [...],
  "next_token": "..."
}
```

Use `next_token` for pagination. PokeXWhoop typically only needs `limit=1` for latest data.

---

## Endpoint Schemas

### GET /

Server info and status.

**Response:**
```json
{
  "server": "whoop-health-data-server",
  "version": "2.1.0",
  "status": "healthy",
  "whoop_connected": true,
  "tools_available": 14,
  "endpoints": {
    "health": "/health",
    "tools": "/tools",
    "mcp_sse": "/sse",
    "poke_context": "/api/poke-context",
    "oauth_start": "/oauth/whoop/start"
  }
}
```

### GET /health

Health check with token status.

**Response:**
```json
{
  "status": "healthy",
  "whoop_connected": true,
  "token_status": {
    "exists": true,
    "expires_at": "2026-02-12T18:00:00Z",
    "hours_until_expiry": 5.2
  }
}
```

### GET /api/poke-context

Full context for check-in decisions.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `next_commitment_time` | ISO timestamp | Next calendar event time |
| `calendar_context` | string | Description of upcoming events |

**Response:**
```json
{
  "state_context": {
    "current": "anchored",
    "previous": "drift_risk",
    "changed_recently": false,
    "reasoning": "2.5h until commitment; recovery 72%"
  },
  "whoop_data": {
    "recovery_score": 72,
    "hrv_rmssd": 41,
    "resting_hr": 56,
    "sleep_hours": 7.2,
    "sleep_efficiency": 85,
    "strain": 8.4
  },
  "wake_status": {
    "user_active_today": true,
    "first_activity": "2026-02-12T07:30:00Z",
    "hours_since_activity": 2.5
  },
  "checkin_status": {
    "last_checkin": "2026-02-12T09:00:00Z",
    "hours_since_checkin": 1.0,
    "unanswered_count": 0
  },
  "recommendation": {
    "can_send": true,
    "context": "User active, engaged, in anchored state",
    "suggested_type": "energy_check"
  },
  "calendar": {
    "buffer_hours": 2.5,
    "context": "Meeting with team at 12:30pm"
  }
}
```

### POST /api/record-checkin

Log a check-in sent.

**Query Parameters:**
| Param | Type | Values |
|-------|------|--------|
| `checkin_type` | string | morning_briefing, meal_prompt, energy_check, task_check, evening_review |
| `trigger_source` | string | hourly, recovery, scheduled, reactive |

**Response:**
```json
{
  "success": true,
  "checkin_id": 42
}
```

### POST /api/record-activity

Log user response.

**Query Parameters:**
| Param | Type | Values |
|-------|------|--------|
| `response_quality` | string | substantive, passive, tangential, emoji_only, opt_out, initiation |

**Response:**
```json
{
  "success": true,
  "logged": {
    "quality": "substantive",
    "timestamp": "2026-02-12T10:15:00Z"
  }
}
```

### GET /tools

List all registered MCP tools.

**Response:**
```json
{
  "count": 14,
  "tools": [
    {
      "name": "get_whoop_health_data",
      "description": "PRIMARY TOOL for WHOOP data..."
    },
    {
      "name": "get_today_summary",
      "description": "Get today's WHOOP health summary..."
    }
    // ... 12 more tools
  ]
}
```

---

## MCP Transport

### SSE Endpoint (for Poke)

```
GET /sse
Accept: text/event-stream
```

This is the primary endpoint for Poke AI's MCP integration.

### HTTP Endpoint (for modern clients)

```
POST /mcp
Content-Type: application/json
```

Supports JSON-RPC 2.0 over HTTP.

### Why Dual Transport?

Poke uses legacy SSE transport. Modern MCP clients use HTTP. Supporting both ensures compatibility.

---

## Database Schema

### tokens
```sql
CREATE TABLE tokens (
    id INTEGER PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    scope TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
)
```

### user_activity
```sql
CREATE TABLE user_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',
    activity_type TEXT NOT NULL,  -- 'wake', 'response', 'initiation'
    checkins_since_response INTEGER DEFAULT 0,
    last_response_quality TEXT,
    last_checkin_type TEXT,
    first_activity_today TIMESTAMP,
    last_activity TIMESTAMP,
    updated_at TIMESTAMP DEFAULT NOW()
)
```

### checkins
```sql
CREATE TABLE checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',
    checkin_type TEXT NOT NULL,
    trigger_source TEXT,
    responded BOOLEAN DEFAULT FALSE,
    response_quality TEXT,
    state_at_send TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
)
```

### state_transitions
```sql
CREATE TABLE state_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT DEFAULT 'default',
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
)
```

### settings
```sql
CREATE TABLE settings (
    id INTEGER PRIMARY KEY,
    buffer_urgent REAL DEFAULT 1.5,
    buffer_anchored REAL DEFAULT 3.0,
    recovery_low INTEGER DEFAULT 60,
    recovery_high INTEGER DEFAULT 80,
    sleep_efficiency_good REAL DEFAULT 85.0,
    updated_at TIMESTAMP DEFAULT NOW()
)
```

---

## Error Handling

### WHOOP API Errors

| Status | Handling |
|--------|----------|
| 401 | Auto-refresh token and retry once |
| 429 | Log and return cached data if available |
| 5xx | Return error, suggest retry later |

### Token Errors

| Error | Action |
|-------|--------|
| No token | Return `"Authorize at /oauth/whoop/start"` |
| Refresh failed | Return error, user must re-authorize |
| Token expired + no refresh | Return error, user must re-authorize |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WHOOP_CLIENT_ID` | Yes | OAuth Client ID from WHOOP Developer Portal |
| `WHOOP_CLIENT_SECRET` | Yes | OAuth Client Secret |
| `WHOOP_REDIRECT_URI` | Yes | Must match portal setting exactly |
| `APP_BASE_URL` | Yes | Public URL of deployed server |
| `TURSO_DATABASE_URL` | Yes | Turso database connection string |
| `TURSO_AUTH_TOKEN` | Yes | Turso authentication token |
| `PORT` | No | Server port (default: 8080) |

---

## Debugging

### Check token status
```bash
curl https://YOUR-DOMAIN/token-status
```

### Verify tools are registered
```bash
curl https://YOUR-DOMAIN/tools
```

### Test state classification
```bash
curl "https://YOUR-DOMAIN/api/poke-context?next_commitment_time=2026-02-12T14:00:00Z"
```

### View Railway logs
```bash
railway logs
```

### Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `whoop_connected: false` | Token expired or missing | Re-authorize at `/oauth/whoop/start` |
| Tools not appearing in Poke | Client-side caching | Disconnect/reconnect MCP in Poke |
| SSE connection fails | Wrong endpoint | Use `/sse`, not `/mcp` |
| State always `anchored` | No commitment time provided | Pass `next_commitment_time` param |
