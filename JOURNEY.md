# PokeXWhoop: The Journey

## The Vision

You set out to build something personal but technically ambitious: **a bridge between your WHOOP health data and Poke AI** so that an AI assistant could proactively check in on you based on your actual physiological state—not arbitrary timers.

The core idea: instead of generic "how are you?" prompts, Poke would know if you were well-rested or running on fumes, if you were about to hit a commitment deadline, or if you were in a "primed" state ready to tackle hard things.

---

## The Foundation (January 12-14)

**Session 1** started with a PRD. You had the architecture clear: WHOOP API → MCP Server → Poke AI. The server would run on Railway, use OAuth to connect to WHOOP, and expose health metrics via the Model Context Protocol (MCP).

We built the initial stack:
- Python FastAPI server with FastMCP
- OAuth 2.0 flow for WHOOP authentication
- PostgreSQL (Railway) for persistence
- 4 core tools: `get_today_summary`, `get_latest_recovery`, `get_last_sleep`, `get_trends`
- **State classification system** with 5 states: `urgent`, `anchored`, `drift_risk`, `high_drift_risk`, `primed`

The foundation was deployed to Railway and connected to Poke.

---

## Challenge 1: OAuth Token Expiration (January 21)

**The Problem:** WHOOP tokens expire, and the refresh flow kept breaking. You had to manually re-authorize constantly, destroying the "seamless" experience.

**How We Solved It:**
- Added `offline` scope to OAuth requests to get long-lived refresh tokens
- Built a background task that checks token expiry every 30 minutes
- Created a `/keep-alive` endpoint for cron-based proactive refresh
- Implemented triple-redundant token refresh: background task + on-API-call + health endpoint

---

## Challenge 2: System Wasn't Learning (February 2)

After a week of real usage, you brought detailed feedback. The system was functional but dumb—it didn't adapt to your patterns.

**Problems Identified:**
- Morning messages were going out before you woke up
- No tracking of which message types actually worked
- Hardcoded weekend rules instead of learning your actual schedule
- No validation of data quality

**How We Solved It — The Major Refactor:**

We built out a sophisticated data-driven system:

1. **Wake Detection** — No messages until first user activity of the day. Learned from your response patterns, not hardcoded times.

2. **Engagement Tracking** — Database tables to record every check-in sent and every response received. Track `response_quality`: substantive, passive, tangential, emoji_only, opt_out, initiation.

3. **State Transition Logging** — Automatic logging when your state changes (e.g., anchored → drift_risk), with timestamps and reasons.

4. **Configurable Thresholds** — Moved all magic numbers into a database table. Thresholds for buffer hours, recovery scores, HRV could be adjusted via MCP tools.

5. **Analytics Tools** — `get_engagement_insights()` to see response rates by hour, day, message type. `get_day_flow_patterns()` for state transition analysis.

The tool count grew from **4 to 14**.

---

## Challenge 3: Poke Couldn't See New Tools (February 2-3)

**The Problem:** Server had 14 tools, but Poke only showed the original 4. Worse, Poke was calling `getweektrends` but our tool was named `get_trends`—clear evidence of stale caching.

**What We Tried:**
- Added `/tools` debug endpoint to verify tools were registered
- Changed MCP server name from `whoop-mcp-server` to `whoop-mcp-v2` to force Poke to treat it as a new server

**Root Cause:** Poke's client-side schema caching. We needed Poke's team to flush the cache—this was outside our control.

---

## Challenge 4: MCP Transport Protocol Mismatch (February 3)

**The Problem:** After fixing the tools issue, a new error appeared:
```json
{"error": {"code": -32600, "message": "Not Acceptable: Client must accept text/event-stream"}}
```

**Root Cause:** We were using FastMCP's `streamable_http_app()` which only supports the new HTTP transport. Poke needed the legacy **SSE (Server-Sent Events)** transport.

**How We Solved It:**
- Added dual transport support: `/mcp` for new clients, `/sse` for Poke
- Had to fix route ordering (`/mcp` was catching `/mcp/sse` requests)
- Converted `HostFixMiddleware` from Starlette middleware to pure ASGI—Starlette's `BaseHTTPMiddleware` isn't compatible with SSE streaming

---

## Challenge 5: Automation Couldn't Access WHOOP Data (February 8)

**The Problem:** Poke has two modes:
1. **Manual chat** → uses MCP → tools work fine
2. **Hourly automation** → uses "subagent types" → automation couldn't find WHOOP data

The automation trigger said "can't access WHOOP data through available tools."

**Root Cause:** Automation subagents have different tool discovery. They weren't seeing `whoop-health-data` as a registered capability.

**How We Solved It (Multi-Part Fix):**

1. **Enriched `get_poke_context()`** — Made it fetch live WHOOP data directly, run state classification, and return everything in one call. Automation doesn't need to call multiple tools.

2. **Added `get_whoop_health_data` gateway tool** — A single entry point that returns all health metrics. Explicitly described as "PRIMARY TOOL for WHOOP data."

3. **Rewrote server metadata** — Changed server name to `"whoop-health-data-server"` with instructions explicitly stating it provides WHOOP health data.

4. **Added OpenAPI annotations** — `openWorldHint=True` to indicate the tool connects to external APIs.

5. **Created HTTP API endpoints** — `/api/poke-context`, `/api/record-checkin`, `/api/record-activity` for automation to use without MCP at all.

---

## Where We Are Now

**Production System:**
- 14 MCP tools covering health data, state classification, engagement tracking, and analytics
- HTTP API endpoints for automation triggers
- OAuth with robust token refresh (background + cron + on-demand)
- PostgreSQL persistence for tokens, activity logs, state transitions, engagement metrics
- Configurable thresholds stored in database
- Dual MCP transport (SSE for Poke, HTTP for modern clients)

**The Tech Stack:**
- Python + FastAPI + FastMCP
- Railway (hosting)
- PostgreSQL (Railway)
- WHOOP API (OAuth 2.0)
- Poke AI (MCP integration)

---

## Where We're Looking to Go

1. **Deeper Pattern Learning** — The engagement tracking infrastructure is in place. Next step is actually using it to automatically adjust check-in frequency and timing based on what historically works.

2. **Calendar Integration** — The `buffer_hours` and `next_commitment_time` parameters suggest awareness of schedule pressure, not just physiological state.

3. **Message Type Optimization** — The `response_quality` tracking can feed into learning which types of prompts (morning_briefing, energy_check, task_check) get substantive responses at which times.

4. **Closing the Loop** — Right now tracking is input-only. The system could evolve to automatically surface insights: "You respond best to energy checks between 2-4pm" or "Your engagement drops when recovery is below 50%."

---

## Key Lessons

1. **OAuth is never simple** — Token refresh edge cases will bite you. Build redundancy.

2. **Client caching is invisible** — When tools don't appear, the problem might not be your server.

3. **Middleware breaks streaming** — Standard request/response middleware doesn't work with SSE. Go pure ASGI.

4. **Discoverability matters** — It's not enough for tools to exist; they need to be described in ways that LLM agents can find them.

5. **Dual interfaces are worth it** — MCP for rich interactions, HTTP API for simple automation. Different clients need different entry points.
