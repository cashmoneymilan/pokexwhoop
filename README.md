# WHOOP MCP Server

A hosted MCP (Model Context Protocol) server that connects to the WHOOP API and exposes health metrics as tools for Poke AI.

## Features

- OAuth 2.0 authentication with WHOOP
- Automatic token refresh
- MCP-compatible SSE transport
- 4 health data tools for Poke AI
- PostgreSQL storage for tokens and data caching
- Health monitoring endpoint
- Cron-triggered data sync

## Prerequisites

Before you begin, you'll need:

1. A [WHOOP](https://www.whoop.com/) account with an active membership
2. A [GitHub](https://github.com/) account
3. A [Railway](https://railway.app/) account (free tier works)
4. Access to the [WHOOP Developer Portal](https://developer.whoop.com/)

---

## Setup Instructions

### Step 1: Register a WHOOP Developer Application

1. Go to the [WHOOP Developer Portal](https://developer.whoop.com/)
2. Sign in with your WHOOP account
3. Click **"Create Application"** (or similar)
4. Fill in the application details:
   - **App Name**: `Poke AI Integration` (or your preferred name)
   - **Description**: Personal health data integration
   - **Redirect URI**: Leave blank for now (you'll update this after Railway setup)
5. Submit and wait for approval (may take 24-48 hours for personal apps)
6. Once approved, note your **Client ID** and **Client Secret**

### Step 2: Create a GitHub Repository

1. Create a new repository on GitHub (e.g., `whoop-mcp-server`)
2. Clone this project to your local machine:
   ```bash
   git clone <this-repo-url> whoop-mcp-server
   cd whoop-mcp-server
   ```
3. Push to your new GitHub repository:
   ```bash
   git remote set-url origin https://github.com/YOUR_USERNAME/whoop-mcp-server.git
   git push -u origin main
   ```

### Step 3: Deploy to Railway

1. Go to [Railway](https://railway.app/) and sign in
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Connect your GitHub account if prompted
5. Select your `whoop-mcp-server` repository
6. Railway will detect the Node.js project and start building

### Step 4: Add PostgreSQL Database

1. In your Railway project dashboard, click **"+ New"**
2. Select **"Database"** → **"Add PostgreSQL"**
3. Wait for the database to provision
4. Railway automatically adds `DATABASE_URL` to your service

### Step 5: Configure Environment Variables

1. In Railway, click on your service (not the database)
2. Go to **"Variables"** tab
3. Add the following variables:

| Variable | Value |
|----------|-------|
| `WHOOP_CLIENT_ID` | Your WHOOP Client ID from Step 1 |
| `WHOOP_CLIENT_SECRET` | Your WHOOP Client Secret from Step 1 |
| `WHOOP_REDIRECT_URI` | `https://YOUR-APP.railway.app/oauth/whoop/callback` |
| `SERVER_API_KEY` | Generate a secure random string (see below) |
| `APP_BASE_URL` | `https://YOUR-APP.railway.app` |
| `NODE_ENV` | `production` |

**To generate a secure API key:**
```bash
openssl rand -hex 32
```
Or use any password generator to create a 32+ character random string.

### Step 6: Get Your Railway Domain

1. In Railway, go to **"Settings"** tab for your service
2. Under **"Networking"** → **"Public Networking"**
3. Click **"Generate Domain"**
4. Copy your domain (e.g., `whoop-mcp-server-production.up.railway.app`)
5. Update your environment variables:
   - `WHOOP_REDIRECT_URI`: `https://YOUR-DOMAIN/oauth/whoop/callback`
   - `APP_BASE_URL`: `https://YOUR-DOMAIN`

### Step 7: Update WHOOP Redirect URI

1. Go back to the [WHOOP Developer Portal](https://developer.whoop.com/)
2. Edit your application
3. Update the **Redirect URI** to match: `https://YOUR-DOMAIN/oauth/whoop/callback`
4. Save changes

### Step 8: Authorize Your WHOOP Account

1. Open your browser and go to:
   ```
   https://YOUR-DOMAIN/oauth/whoop/start
   ```
2. Log in with your WHOOP account
3. Authorize the application
4. You should see a success page: "WHOOP Connected"

### Step 9: Verify Setup

Check the health endpoint:
```bash
curl https://YOUR-DOMAIN/health
```

Expected response:
```json
{
  "status": "ok",
  "timestamp": "2024-01-15T10:30:00.000Z",
  "database": true,
  "tokenPresent": true,
  "tokenExpiresAt": "2024-01-15T12:30:00.000Z",
  "lastWhoopSync": null
}
```

### Step 10: Connect to Poke AI

Configure Poke AI to use your MCP server:

- **MCP Server URL**: `https://YOUR-DOMAIN/mcp/sse`
- **API Key Header**: `x-api-key: YOUR_SERVER_API_KEY`

Refer to Poke AI's documentation for specific integration steps.

---

## MCP Tools

Once connected, Poke AI can use these tools:

### `get_today_summary`
Returns today's comprehensive health data:
- Recovery score and state
- Strain score
- Sleep duration and quality
- HRV and resting heart rate
- Recommended strain range

### `get_latest_recovery`
Returns the most recent recovery data:
- Recovery score (0-100)
- HRV (heart rate variability)
- Resting heart rate
- Recovery state (green/yellow/red)
- Confidence level

### `get_last_sleep`
Returns the most recent sleep data:
- Total sleep time
- Sleep debt
- Sleep efficiency
- Disturbances
- Time in each sleep stage

### `get_week_trends`
Returns 7-day trends for a metric:
- **Parameters**: `metric` (required): `"recovery"`, `"strain"`, or `"sleep"`
- Weekly average
- Trend direction (improving/stable/declining)
- Daily data points
- Notable outliers

---

## Optional: Cron Sync

For faster MCP responses and data resilience, set up a cron job:

### Using Railway Cron

1. In Railway, add a new service
2. Use a cron image or configure a cron job to hit:
   ```
   POST https://YOUR-DOMAIN/cron/sync
   Header: x-api-key: YOUR_SERVER_API_KEY
   ```

### Using External Cron Service

Use services like [cron-job.org](https://cron-job.org/) or [EasyCron](https://www.easycron.com/):

- **URL**: `https://YOUR-DOMAIN/cron/sync`
- **Method**: POST
- **Headers**: `x-api-key: YOUR_SERVER_API_KEY`
- **Schedule**: Every 30 minutes or hourly

---

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | Server info |
| `/health` | GET | No | Health check |
| `/oauth/whoop/start` | GET | No | Start OAuth flow |
| `/oauth/whoop/callback` | GET | No | OAuth callback |
| `/mcp/sse` | GET | API Key | MCP SSE connection |
| `/mcp/messages` | POST | API Key | MCP message handling |
| `/cron/sync` | POST | API Key | Trigger data sync |

---

## Troubleshooting

### "No WHOOP token found"
- Visit `/oauth/whoop/start` to authorize your account

### "Token refresh failed"
- Your refresh token may have expired
- Re-authorize at `/oauth/whoop/start`

### "Invalid API key"
- Ensure you're sending `x-api-key` header
- Check the `SERVER_API_KEY` environment variable

### Health endpoint shows `"status": "degraded"`
- Token may be missing or expired
- Database connection may be failing

### WHOOP API returns 429 (Rate Limited)
- The server handles rate limits automatically
- If persistent, reduce cron frequency

---

## Development

### Local Setup

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in values
3. Start a local PostgreSQL database
4. Run:
   ```bash
   npm install
   npm run dev
   ```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WHOOP_CLIENT_ID` | Yes | WHOOP OAuth Client ID |
| `WHOOP_CLIENT_SECRET` | Yes | WHOOP OAuth Client Secret |
| `WHOOP_REDIRECT_URI` | Yes | OAuth callback URL |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `SERVER_API_KEY` | Yes | API key for protected endpoints |
| `APP_BASE_URL` | Yes | Public URL of your server |
| `PORT` | No | Server port (default: 3000) |
| `NODE_ENV` | No | Environment (development/production) |
| `CACHE_TTL_MINUTES` | No | Cache duration (default: 15) |
| `LOG_LEVEL` | No | Logging level (default: info) |

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   WHOOP API     │────▶│  MCP Server      │────▶│  Poke AI    │
│   (Official)    │     │  (Railway)       │     │  (Client)   │
└─────────────────┘     └──────────────────┘     └─────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │  PostgreSQL  │
                        │  (Railway)   │
                        └──────────────┘
```

## License

MIT
