# WHOOP MCP Server for Poke AI

A hosted MCP server that connects to the WHOOP API and exposes health metrics + context tools for Poke AI's hourly automation.

## Features

- OAuth 2.0 authentication with WHOOP
- Automatic token refresh (background task + /keep-alive endpoint)
- MCP-compatible SSE transport for Poke
- **HTTP API endpoints** for automation (no MCP needed)
- 14 tools: health data, state classification, engagement tracking
- SQLite database with Turso cloud sync
- Configurable thresholds for state classification

## Quick Start

### 1. Register WHOOP Developer App

1. Go to [WHOOP Developer Portal](https://developer.whoop.com/)
2. Create application, note **Client ID** and **Client Secret**
3. Leave Redirect URI blank for now

### 2. Deploy to Railway

1. Fork this repo to your GitHub
2. Go to [Railway](https://railway.app/) → **New Project** → **Deploy from GitHub**
3. Select your repo, wait for build

### 3. Configure Railway

In Railway → **Variables**, add:

| Variable | Value |
|----------|-------|
| `WHOOP_CLIENT_ID` | Your Client ID |
| `WHOOP_CLIENT_SECRET` | Your Client Secret |
| `WHOOP_REDIRECT_URI` | `https://YOUR-DOMAIN/oauth/whoop/callback` |
| `APP_BASE_URL` | `https://YOUR-DOMAIN` |
| `TURSO_DATABASE_URL` | Your Turso database URL |
| `TURSO_AUTH_TOKEN` | Your Turso auth token |

### 4. Update WHOOP Redirect URI

In WHOOP Developer Portal, set Redirect URI to:
```
https://YOUR-DOMAIN/oauth/whoop/callback
```

### 5. Authorize

Visit `https://YOUR-DOMAIN/oauth/whoop/start` and log in.

### 6. Connect Poke

Configure Poke with MCP Server URL:
```
https://YOUR-DOMAIN/sse
```

---

## HTTP API (for Automation)

These endpoints work without MCP - perfect for hourly automation.

### GET `/api/poke-context`

Get all context for deciding whether/how to check in.

```bash
curl https://YOUR-DOMAIN/api/poke-context
```

Response:
```json
{
  "wake_status": {
    "user_active_today": true,
    "hours_since_activity": 2.5
  },
  "checkin_status": {
    "hours_since_checkin": 1.2,
    "unanswered_count": 0
  },
  "state_context": {
    "current": "anchored",
    "changed_recently": false
  },
  "recommendation": {
    "can_send": true,
    "context": "User active today; 2.5h since last check-in",
    "suggested_type": "energy_check"
  },
  "calendar": {
    "buffer_hours": null
  }
}
```

Optional query params:
- `next_commitment_time` - ISO timestamp of next calendar event
- `calendar_context` - Brief description of upcoming events

### POST `/api/record-checkin`

Log that a check-in was sent.

Query params:
- `checkin_type` - morning_briefing, meal_prompt, energy_check, task_check, etc.
- `trigger_source` - hourly, recovery, scheduled, reactive

### POST `/api/record-activity`

Log user response.

Query params:
- `response_quality` - substantive, passive, tangential, emoji_only, opt_out, initiation

---

## MCP Tools

### Health Data
- `get_today_summary` - Recovery, strain, sleep, HRV, recommendations
- `get_latest_recovery` - Recovery score, HRV, resting HR, state
- `get_last_sleep` - Duration, debt, efficiency, stages
- `get_trends` - Historical data for any metric (recovery, strain, sleep, hrv)

### State Classification
- `get_user_state` - Classify user state (urgent, anchored, drift_risk, primed)
- `get_state_thresholds` - View current threshold settings
- `update_thresholds` - Adjust classification thresholds

### Poke Context
- `get_poke_context` - All context for check-in decisions
- `record_user_activity` - Log user responses
- `record_checkin_sent` - Log check-ins sent
- `process_opt_out` - Handle user opt-out requests

### Analytics
- `get_engagement_insights` - Response rates, best hours, recommendations
- `get_day_flow_patterns` - State transition patterns
- `validate_today_data` - Check for data anomalies

---

## All Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Server info |
| `/health` | GET | Health check + token refresh |
| `/token-status` | GET | Detailed token expiry info |
| `/keep-alive` | GET | Proactive token refresh (for cron) |
| `/tools` | GET | List all MCP tools |
| `/sse` | GET | MCP SSE stream (for Poke) |
| `/messages` | POST | MCP message posting |
| `/api/poke-context` | GET | Context for automation |
| `/api/record-checkin` | POST | Log check-in sent |
| `/api/record-activity` | POST | Log user activity |
| `/oauth/whoop/start` | GET | Start OAuth flow |
| `/oauth/whoop/callback` | GET | OAuth callback |

---

## Token Management

The server automatically refreshes tokens:
1. **Background task** - Checks every 30 minutes
2. **On API call** - Refreshes if expired
3. **Health endpoint** - Refreshes if < 1 hour left

For extra reliability, set up a cron job to hit `/keep-alive` every 30 minutes.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WHOOP_CLIENT_ID` | Yes | WHOOP OAuth Client ID |
| `WHOOP_CLIENT_SECRET` | Yes | WHOOP OAuth Client Secret |
| `WHOOP_REDIRECT_URI` | Yes | OAuth callback URL |
| `APP_BASE_URL` | Yes | Public URL of server |
| `TURSO_DATABASE_URL` | Yes | Turso database URL |
| `TURSO_AUTH_TOKEN` | Yes | Turso auth token |
| `PORT` | No | Server port (default: 8080) |

## License

MIT
