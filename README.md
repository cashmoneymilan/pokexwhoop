# PokeXWhoop

**An MCP server that gives AI agents real-time awareness of your physiological state.**

> **[View Project Summary (PDF)](./docs/PokeXWhoop-Summary.pdf)** — One-page overview of the project

PokeXWhoop bridges WHOOP health data to Poke AI, enabling context-aware check-ins based on recovery, sleep, and schedule pressure—not arbitrary timers.

## Why It Matters

Traditional productivity tools ping you on schedules. This system knows:
- You slept 4 hours and have a meeting in 90 minutes → **urgent** state, no interruptions
- You're well-rested with nothing until 3pm → **primed** state, suggest deep work
- It's been 6 hours with no commitments and low recovery → **high_drift_risk**, gentle re-anchor

The agent adapts its behavior to your actual capacity, not assumptions.

## Top 3 Technical Decisions

1. **State Classification Engine** — 5 discrete states (`urgent`, `anchored`, `drift_risk`, `high_drift_risk`, `primed`) computed from buffer hours to next commitment + recovery score + sleep efficiency. Simple rules, interpretable output.

2. **Dual Transport (SSE + HTTP)** — MCP over SSE for Poke's chat interface, plus REST endpoints (`/api/poke-context`) for hourly automation. Different clients need different entry points.

3. **Engagement Tracking** — Every check-in and response is logged with quality labels. The system learns which message types work at which times, enabling future personalization.

## Quick Demo

```bash
# Check current state
curl https://pokexwhoop-production.up.railway.app/api/poke-context

# Response
{
  "state_context": { "current": "anchored" },
  "whoop_data": { "recovery_score": 72, "hrv": 45 },
  "recommendation": { "can_send": true, "suggested_type": "energy_check" }
}
```

## Architecture

```
WHOOP API ──OAuth──▶ PokeXWhoop Server ──MCP/SSE──▶ Poke AI
                          │
                    ┌─────┴─────┐
                    ▼           ▼
              State Engine   PostgreSQL
              (5 states)    (tokens, logs)
```

## States at a Glance

| State | Condition | Agent Behavior |
|-------|-----------|----------------|
| `urgent` | ≤1.5h to commitment | No interruptions, only critical alerts |
| `anchored` | 1.5-3h to commitment | Light check-ins, respect flow |
| `drift_risk` | >3h or no commitment | Proactive structure suggestions |
| `high_drift_risk` | drift + recovery <60% | Gentle re-anchoring, self-care nudges |
| `primed` | anchored + recovery ≥80% + sleep ≥85% | Suggest challenging work |

## Links

- **[Quickstart Guide](./QUICKSTART.md)** — Local setup and demo
- **[Decision Memo](./DECISION-MEMO.md)** — Full state logic and agent behaviors
- **[Examples](./EXAMPLES.md)** — Sample prompts and expected outputs
- **[Technical Appendix](./TECHNICAL.md)** — OAuth flow, rate limits, schemas
- **[Changelog](./CHANGELOG.md)** — Usage notes and lessons learned

## Reliable daily data

`GET /api/daily-summary?date=YYYY-MM-DD` always refetches the latest WHOOP records,
applies manual overrides, validates matched SCORED sleep/recovery records, and saves
an append-only revision when the normalized record or upstream revision changes.
Pending summaries return HTTP 202 with `Retry-After` and are also placed in a durable
retry queue. Calorie totals include `partial_day` or `completed_day`; only completed
days are marked valid for the weight-loss model.

Manual invalidations and dotted-path corrections live in `whoop_overrides.json` so
they are explicit, reviewable, and deployed with the service. Invalidated records
never expose measurements as model-ready data.

## Tech Stack

- Python 3.11 + FastAPI + FastMCP
- Railway (hosting)
- PostgreSQL (Railway built-in)
- WHOOP API (OAuth 2.0)

## License

MIT — See [LICENSE](./LICENSE)

---

Built by [@cashmoneymilan](https://github.com/cashmoneymilan)
