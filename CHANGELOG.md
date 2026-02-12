# Changelog & Usage Notes

Personal usage log, iteration history, and lessons learned.

---

## Current State (as of February 2026)

### Deployment Status
- **Production:** Hosted on Railway at `pokexwhoop-production.up.railway.app`
- **Database:** PostgreSQL (Railway built-in)
- **WHOOP Integration:** Active, OAuth tokens refreshing automatically
- **Poke Integration:** Connected via SSE transport at `/sse`

### Known Issues / Breakages
- **Poke tool caching:** Poke may cache old tool schemas. Disconnect/reconnect in Poke settings to refresh.
- **WHOOP API rate limits:** Occasionally returns 429 during high-frequency polling. Server handles gracefully with retry.
- **No calendar integration yet:** `buffer_hours` requires manual input or external automation passing `next_commitment_time`.

### Threshold Tuning History
| Date | Change | Reason |
|------|--------|--------|
| Jan 14 | `buffer_urgent`: 1.0h → 1.5h | 1h felt too tight; users need prep time |
| Jan 21 | `recovery_high`: 75% → 80% | 75% triggered `primed` too often; didn't feel exceptional |
| Feb 2 | Added `sleep_efficiency_good`: 85% | Recovery alone wasn't enough; poor sleep quality should block `primed` |

### Edge Cases Handled
| Edge Case | Decision |
|-----------|----------|
| No calendar data | Default to `anchored` unless recovery <60% (then `drift_risk`) or ≥80% (then `primed`) |
| WHOOP API down | Fallback to buffer_hours only; `primed`/`high_drift_risk` unavailable |
| Commitment in the past | Treat as null (ignore stale calendar events) |
| Negative buffer_hours | Clamp to null (commitment already passed) |
| State oscillation | Log transitions but don't alert on rapid changes within 1 hour |
| Timezone handling | All times in user's local timezone via WHOOP API |

### Privacy & Data Handling
| Signal | Recorded | Retention | Opt-Out |
|--------|----------|-----------|---------|
| WHOOP metrics (recovery, HRV, sleep) | Cached 24h | Overwritten daily | Revoke WHOOP OAuth |
| Check-ins sent | Logged with timestamp | Indefinite | Delete via database |
| User responses | Quality label only, no content | Indefinite | Call `process_opt_out()` MCP tool |
| State transitions | Logged with reason | 90 days | N/A (anonymized) |

**To fully opt out:** Revoke WHOOP authorization at `/oauth/whoop/start` or disconnect MCP in Poke.

### Personal Usage Log
| Period | Status | Notes |
|--------|--------|-------|
| Jan 12-14 | Building | Initial deployment, OAuth working |
| Jan 15-20 | **Broken** | Token refresh failing, had to re-auth daily |
| Jan 21-31 | Running | Token fix deployed, 10 days continuous |
| Feb 1-8 | Running | Major refactor, engagement tracking added |
| Feb 8-12 | Running | Automation fix deployed |

**Subjective assessment:** Helpful ~60% of the time. Most valuable when it caught low-recovery days and suggested rest instead of productivity. Annoying when it sent morning check-ins before I woke up (fixed with wake detection). The `primed` state suggestions felt motivating on good days.

### Test Coverage
| Component | Tests | Coverage |
|-----------|-------|----------|
| State classification | Manual | Core logic verified via `/api/poke-context` |
| OAuth flow | Manual | End-to-end tested on Railway |
| Token refresh | Manual | Verified via `/health` and `/keep-alive` |
| MCP tools | Manual | All 15 tools callable via Poke |
| Unit tests | **None** | No automated test suite yet |

**Risk:** No automated tests means regressions are caught manually. High priority for next iteration.

### Next 3 Steps
1. **Add `/state` endpoint** — Direct HTTP endpoint returning just the current state (simpler than full context)
2. **Calendar API integration** — Connect Google Calendar to auto-populate `buffer_hours`
3. **Engagement-based threshold tuning** — Use logged response quality to auto-adjust check-in frequency

---

## Timeline

### Week 1: January 12-14, 2026

**What shipped:**
- Initial MCP server with 4 tools
- OAuth 2.0 flow for WHOOP
- State classification engine (5 states)
- Railway deployment
- PostgreSQL database (Railway)

**First impressions:**
- The concept worked immediately—Poke could call tools and get WHOOP data
- State classification felt right: the 5-state model captured meaningful distinctions
- OAuth flow was more complex than expected (WHOOP's docs are sparse)

---

### Week 2: January 21-23

**Problem:** Had to re-authorize WHOOP every few hours. Tokens expired and refresh failed.

**Root cause:** Missing `offline` scope in OAuth request. WHOOP requires explicit request for long-lived refresh tokens.

**What shipped:**
- Added `offline` scope to OAuth
- Background token refresh task (every 30 min)
- `/keep-alive` endpoint for cron-based refresh
- Triple redundancy: background + on-API-call + health endpoint

**Days running:** 9 continuous days after fix

---

### Week 3: February 2

**Problem:** System wasn't learning from my patterns. Morning messages at 6am when I wake at 8am. Generic prompts regardless of what worked before.

**Feedback collected:**
- Message response rates: some types get engagement, others are ignored
- Early morning messages go unanswered until I wake up
- Weekend patterns differ from weekday
- No tracking of what actually works

**What shipped (major refactor):**
- Wake detection—no messages until first activity
- Engagement tracking database tables
- Response quality labels (substantive, passive, emoji_only, etc.)
- State transition logging
- Configurable thresholds (database-driven, not hardcoded)
- Analytics tools (`get_engagement_insights`, `get_day_flow_patterns`)
- Expanded from 4 to 14 MCP tools

---

### Week 3-4: February 2-8

**Problem:** New tools not appearing in Poke. Server had 14 tools, Poke showed 4.

**Debugging journey:**
1. Added `/tools` endpoint to verify tools were registered server-side ✓
2. Changed MCP server name to force cache invalidation
3. Discovered Poke was calling `getweektrends` but our tool was `get_trends`—clear stale cache
4. This was client-side caching in Poke, outside our control

**Lesson:** When tools don't appear, the problem might not be your server.

---

### Week 4: February 3

**Problem:** New error after fixing tools:
```
"Not Acceptable: Client must accept text/event-stream"
```

**Root cause:** FastMCP's `streamable_http_app()` only supports new HTTP transport. Poke needed legacy SSE.

**What shipped:**
- Dual transport: `/mcp` for new clients, `/sse` for Poke
- Route ordering fix (`/mcp` was catching `/mcp/sse`)
- Rewrote middleware as pure ASGI (Starlette's `BaseHTTPMiddleware` breaks SSE)

**Lesson:** Standard request/response middleware doesn't work with streaming. Go pure ASGI.

---

### Week 4: February 8

**Problem:** Hourly automation couldn't access WHOOP data. Manual chat worked, automation failed.

**Root cause:** Automation uses "subagent types" with different tool discovery. It couldn't find `whoop-health-data` as a capability.

**What shipped:**
- Enriched `get_poke_context()` to fetch live WHOOP data directly
- Added `get_whoop_health_data` gateway tool
- Rewrote server metadata with explicit instructions
- Added HTTP endpoints (`/api/poke-context`) for automation

**Lesson:** It's not enough for tools to exist—they need descriptions that LLM agents can discover.

---

## Personal Usage Stats

| Metric | Value |
|--------|-------|
| Days running | ~30 |
| Total check-ins logged | ~150 |
| Substantive response rate | ~45% |
| Best check-in time | 10-11am |
| Worst check-in time | 6-7am (pre-wake) |
| Most effective message type | energy_check |
| Least effective message type | morning_briefing |

---

## Surprising Failure Cases

### 1. Sunday Morning Paradox
High recovery + no events = `primed` state, but I don't want productivity nudges on Sunday morning. The system optimizes for capacity but doesn't understand rest as a goal.

**Potential fix:** Add day-of-week awareness or "rest mode" flag.

### 2. Post-Workout Confusion
Recovery score drops after a hard workout (expected), triggering `high_drift_risk`. But I'm not drifting—I just exercised.

**Potential fix:** Incorporate strain data into classification, or add cooldown period after high strain.

### 3. Travel Days
Buffer hours collapse during travel (flights, transit). System thinks I'm in `urgent` all day, but I can't do focused work anyway.

**Potential fix:** Detect travel patterns or add manual "travel mode."

### 4. The "Okay" Spiral
When I respond with just "ok" or "thanks," the system logs it as `passive` and may reduce check-in frequency. But sometimes "ok" means "acknowledged, I'm in flow"—not disengagement.

**Potential fix:** Consider context (e.g., was there a follow-up action?) not just response text.

---

## What Would I Build Differently?

### 1. Start with HTTP, add MCP later
MCP transport issues consumed 40% of debugging time. HTTP endpoints would have validated the concept faster.

### 2. Mock data mode from day one
Testing state transitions required waiting for actual physiological changes. A mock mode would have accelerated iteration.

### 3. Explicit "learning" vs "acting" modes
The system tracks engagement but doesn't yet use it to adapt behavior. Should have separated data collection from behavioral changes.

### 4. Calendar integration earlier
Buffer hours are the primary signal, but they require manual input. Calendar API integration would have made the system truly autonomous.

---

## Key Lessons

1. **OAuth is never simple.** Token refresh edge cases will bite you. Build redundancy.

2. **Client caching is invisible.** When tools don't appear, verify server-side first, then suspect the client.

3. **Middleware breaks streaming.** SSE needs pure ASGI middleware, not Starlette's convenience wrappers.

4. **Discoverability > existence.** LLM agents need explicit, verbose descriptions to find and use tools.

5. **Dual interfaces are worth it.** MCP for rich interactions, HTTP for simple automation. Different clients need different entry points.

6. **Real usage reveals real problems.** Feedback after a week of use was more valuable than any amount of upfront design.

---

## Future Roadmap

- [ ] Automatic threshold adjustment based on engagement patterns
- [ ] Calendar API integration (Google/Outlook)
- [ ] Travel mode detection
- [ ] Weekly digest of state patterns and insights
- [ ] A/B testing message types to optimize engagement
