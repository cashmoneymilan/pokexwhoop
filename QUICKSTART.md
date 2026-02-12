# Quickstart Guide

Get PokeXWhoop running locally in under 10 minutes.

## Prerequisites

- Python 3.11+
- A WHOOP account with data
- PostgreSQL (Railway provides this automatically)

## Option 1: Local Development

### 1. Clone and Install

```bash
git clone https://github.com/cashmoneymilan/pokexwhoop.git
cd pokexwhoop
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get WHOOP Credentials

1. Go to [WHOOP Developer Portal](https://developer.whoop.com/)
2. Create a new application
3. Note your **Client ID** and **Client Secret**
4. Set Redirect URI to: `http://localhost:8080/oauth/whoop/callback`

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```bash
WHOOP_CLIENT_ID=your_client_id
WHOOP_CLIENT_SECRET=your_client_secret
WHOOP_REDIRECT_URI=http://localhost:8080/oauth/whoop/callback
APP_BASE_URL=http://localhost:8080

# For local dev, you need a PostgreSQL database
# Set DATABASE_URL to your local postgres or use Railway
```

### 4. Run the Server

```bash
python server.py
```

Server starts at `http://localhost:8080`

### 5. Authorize WHOOP

Open in browser: `http://localhost:8080/oauth/whoop/start`

Log in with your WHOOP credentials. You'll be redirected back with tokens saved.

### 6. Test It

```bash
# Health check
curl http://localhost:8080/health

# Get your state
curl http://localhost:8080/api/poke-context

# List all tools
curl http://localhost:8080/tools
```

---

## Option 2: Deploy to Railway (Production)

### 1. Fork the Repo

Fork `cashmoneymilan/pokexwhoop` to your GitHub.

### 2. Create Railway Project

1. Go to [Railway](https://railway.app/)
2. **New Project** → **Deploy from GitHub**
3. Select your forked repo

### 3. Add PostgreSQL Database

1. In Railway, click **+ New** → **Database** → **PostgreSQL**
2. Railway automatically sets `DATABASE_URL` for your app

### 4. Set Environment Variables

In Railway → **Variables**:

| Variable | Value |
|----------|-------|
| `WHOOP_CLIENT_ID` | From WHOOP Developer Portal |
| `WHOOP_CLIENT_SECRET` | From WHOOP Developer Portal |
| `WHOOP_REDIRECT_URI` | `https://YOUR-RAILWAY-DOMAIN/oauth/whoop/callback` |
| `APP_BASE_URL` | `https://YOUR-RAILWAY-DOMAIN` |

Note: `DATABASE_URL` is set automatically by Railway when you add PostgreSQL.

### 5. Update WHOOP Redirect URI

In WHOOP Developer Portal, update Redirect URI to match your Railway domain.

### 6. Authorize

Visit: `https://YOUR-RAILWAY-DOMAIN/oauth/whoop/start`

---

## Demo Mode (Mock Data)

For demos without real WHOOP data, you can test the state engine directly:

```bash
# Test state classification logic
curl "http://localhost:8080/api/poke-context?next_commitment_time=2024-01-15T14:00:00Z"
```

The `next_commitment_time` parameter lets you simulate different schedule scenarios.

---

## Verify Everything Works

Run this checklist:

```bash
# 1. Server is running
curl http://localhost:8080/
# → Should return server info with version

# 2. WHOOP is connected
curl http://localhost:8080/health
# → Should show "whoop_connected": true

# 3. State engine works
curl http://localhost:8080/api/poke-context
# → Should return state_context, whoop_data, recommendation

# 4. MCP tools are registered
curl http://localhost:8080/tools
# → Should list 15 tools
```

---

## Connect to Poke AI

In Poke's MCP configuration, add:

```
URL: https://YOUR-DOMAIN/sse
Transport: SSE
```

The agent will now have access to all WHOOP health tools.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Token refresh fails | Re-authorize at `/oauth/whoop/start` |
| "whoop_connected": false | Check credentials in environment variables |
| Tools not appearing in Poke | Disconnect and reconnect the MCP server in Poke |
| SSE connection errors | Ensure you're connecting to `/sse`, not `/mcp` |

---

## Next Steps

- Read [DECISION-MEMO.md](./DECISION-MEMO.md) to understand state logic
- See [EXAMPLES.md](./EXAMPLES.md) for sample agent interactions
- Check [TECHNICAL.md](./TECHNICAL.md) for OAuth and API details
