# WHOOP MCP Server

A hosted MCP (Model Context Protocol) server that connects to the WHOOP API and exposes health metrics as tools for Poke AI.

## Features

- OAuth 2.0 authentication with WHOOP
- Automatic token refresh
- MCP-compatible SSE transport
- 4 health data tools for Poke AI
- SQLite database (no external service needed)
- Health monitoring endpoint

## Prerequisites

1. A [WHOOP](https://www.whoop.com/) account with an active membership
2. A [GitHub](https://github.com/) account
3. A [Railway](https://railway.app/) account
4. Access to the [WHOOP Developer Portal](https://developer.whoop.com/)

---

## Setup Instructions

### Step 1: Register a WHOOP Developer Application

1. Go to the [WHOOP Developer Portal](https://developer.whoop.com/)
2. Sign in with your WHOOP account
3. Click **"Create Application"**
4. Fill in:
   - **App Name**: `Poke AI Integration`
   - **Description**: Personal health data integration
   - **Redirect URI**: Leave blank for now
5. Submit and wait for approval
6. Note your **Client ID** and **Client Secret**

### Step 2: Deploy to Railway

1. Fork or push this repo to your GitHub
2. Go to [Railway](https://railway.app/) and sign in
3. Click **"New Project"** → **"Deploy from GitHub repo"**
4. Select your repository
5. Wait for the build to complete

### Step 3: Get Your Domain

1. In Railway, click on your service
2. Go to **Settings** → **Networking** → **Public Networking**
3. Click **"Generate Domain"**
4. Copy your domain (e.g., `pokexwhoop-production.up.railway.app`)

### Step 4: Configure Environment Variables

In Railway, go to your service → **Variables** tab and add:

| Variable | Value |
|----------|-------|
| `WHOOP_CLIENT_ID` | Your Client ID from WHOOP |
| `WHOOP_CLIENT_SECRET` | Your Client Secret from WHOOP |
| `WHOOP_REDIRECT_URI` | `https://YOUR-DOMAIN/oauth/whoop/callback` |
| `APP_BASE_URL` | `https://YOUR-DOMAIN` |
| `SERVER_API_KEY` | Generate with `openssl rand -hex 32` |

### Step 5: Update WHOOP Redirect URI

1. Go back to [WHOOP Developer Portal](https://developer.whoop.com/)
2. Edit your application
3. Set **Redirect URI** to: `https://YOUR-DOMAIN/oauth/whoop/callback`
4. Save

### Step 6: Authorize Your WHOOP Account

Visit:
```
https://YOUR-DOMAIN/oauth/whoop/start
```

Log in and authorize. You should see "WHOOP Connected".

### Step 7: Verify

Check the health endpoint:
```
https://YOUR-DOMAIN/health
```

Should return:
```json
{
  "status": "ok",
  "database": true,
  "tokenPresent": true
}
```

### Step 8: Connect to Poke AI

Configure Poke AI with:
- **MCP Server URL**: `https://YOUR-DOMAIN/mcp/sse`
- **API Key Header**: `x-api-key: YOUR_SERVER_API_KEY`

---

## MCP Tools

### `get_today_summary`
Today's recovery, strain, sleep, HRV, and recommended strain range.

### `get_latest_recovery`
Most recent recovery score, HRV, resting heart rate, and state (green/yellow/red).

### `get_last_sleep`
Most recent sleep data: duration, debt, efficiency, disturbances, and sleep stages.

### `get_week_trends`
7-day trends for `recovery`, `strain`, or `sleep`. Returns average, trend direction, and outliers.

---

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | Server info |
| `/health` | GET | No | Health check |
| `/oauth/whoop/start` | GET | No | Start OAuth |
| `/oauth/whoop/callback` | GET | No | OAuth callback |
| `/mcp/sse` | GET | API Key | MCP connection |
| `/cron/sync` | POST | API Key | Sync data |

---

## Troubleshooting

**"No WHOOP token found"**
→ Visit `/oauth/whoop/start` to authorize

**"Invalid API key"**
→ Check `x-api-key` header matches `SERVER_API_KEY`

**Health shows `tokenPresent: false`**
→ Re-authorize at `/oauth/whoop/start`

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WHOOP_CLIENT_ID` | Yes | WHOOP OAuth Client ID |
| `WHOOP_CLIENT_SECRET` | Yes | WHOOP OAuth Client Secret |
| `WHOOP_REDIRECT_URI` | Yes | OAuth callback URL |
| `SERVER_API_KEY` | Yes | API key for protected endpoints |
| `APP_BASE_URL` | Yes | Public URL of your server |
| `DB_PATH` | No | SQLite path (default: `./data/whoop.db`) |
| `PORT` | No | Server port (default: 3000) |

## License

MIT
