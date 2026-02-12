# Decision Memo: State Classification & Agent Behaviors

This document defines the state classification logic and expected agent behaviors for each state.

---

## Overview

The system classifies users into one of **5 discrete states** based on:
1. **Buffer hours** — Time until next calendar commitment
2. **Recovery score** — WHOOP's 0-100% recovery metric
3. **Sleep efficiency** — Percentage of time in bed actually sleeping

The agent (Poke AI) adjusts its behavior based on the current state.

---

## State Definitions

### 1. `urgent`

**Condition:** `buffer_hours <= 1.5`

The user has a commitment within 90 minutes. They're likely preparing, commuting, or already in execution mode.

| Metric | Threshold |
|--------|-----------|
| Buffer hours | ≤ 1.5h |

**Agent Behavior:**
- No proactive check-ins
- Only surface critical alerts (e.g., schedule conflicts)
- If user initiates, respond concisely
- Never suggest new tasks or reflection

**Example Scenario:**
> It's 8:30am. User has a 9:00am meeting. Recovery is 45%.
>
> **State:** `urgent`
> **Agent action:** Silent. No morning check-in. If user asks something, give a direct answer without follow-up questions.

---

### 2. `anchored`

**Condition:** `1.5 < buffer_hours <= 3.0`

The user has a commitment 1.5-3 hours away. Natural structure exists—they know when their next anchor point is.

| Metric | Threshold |
|--------|-----------|
| Buffer hours | 1.5h - 3.0h |

**Agent Behavior:**
- Light check-ins allowed
- Respect flow state—don't interrupt deep work
- Energy checks appropriate ("How are you feeling?")
- Can suggest quick wins if user seems idle
- Don't pile on new commitments

**Example Scenario:**
> It's 10:00am. User has a 12:30pm lunch meeting. Recovery is 68%.
>
> **State:** `anchored`
> **Agent action:** One mid-morning check-in. "Morning! You've got 2.5h until lunch—anything you want to tackle before then?"

---

### 3. `drift_risk`

**Condition:** `buffer_hours > 3.0` OR `buffer_hours is null`

The user has no commitments for 3+ hours, or no commitments at all today. Structure may dissolve—the day could slip into unintentional patterns.

| Metric | Threshold |
|--------|-----------|
| Buffer hours | > 3.0h or none |

**Agent Behavior:**
- Proactive structure suggestions
- Offer to set an anchor ("Want to schedule a focus block?")
- Check in on intentions for the day
- More frequent light touches
- Watch for signs of drift (long silence, passive responses)

**Example Scenario:**
> It's 2:00pm on Saturday. No calendar events. Recovery is 72%.
>
> **State:** `drift_risk`
> **Agent action:** "Hey! Open afternoon—anything you'd like to accomplish? Or is this intentional rest?"

---

### 4. `high_drift_risk`

**Condition:** `drift_risk` AND `recovery_score < 60%`

Both structure AND physiology are compromised. The user has no near-term commitments and is running on depleted energy.

| Metric | Threshold |
|--------|-----------|
| Buffer hours | > 3.0h or none |
| Recovery | < 60% |

**Agent Behavior:**
- Gentle re-anchoring, not pressure
- Prioritize self-care suggestions
- Acknowledge low energy explicitly
- Don't suggest demanding tasks
- Offer permission to rest ("Today might be a recovery day")

**Example Scenario:**
> It's 11:00am Sunday. No events. Recovery is 42%, user slept 5 hours.
>
> **State:** `high_drift_risk`
> **Agent action:** "Noticing your recovery is at 42% today. Might be a good day to keep things light. Want help protecting some downtime?"

---

### 5. `primed`

**Condition:** `anchored` AND `recovery_score >= 80%` AND `sleep_efficiency >= 85%`

Optimal state: the user has structure (anchored) AND is physiologically prepared. Peak performance window.

| Metric | Threshold |
|--------|-----------|
| Buffer hours | 1.5h - 3.0h |
| Recovery | ≥ 80% |
| Sleep efficiency | ≥ 85% |

**Agent Behavior:**
- Suggest challenging/meaningful work
- This is the time for deep focus, creative tasks, hard conversations
- Celebrate the state ("You're in great shape today")
- Help protect this window from interruptions
- Can be more ambitious with suggestions

**Example Scenario:**
> It's 9:00am. Meeting at 11:30am. Recovery is 85%, slept 7.5h with 92% efficiency.
>
> **State:** `primed`
> **Agent action:** "Recovery at 85%—you're primed. You've got 2.5h before your call. Good window for that project you've been putting off?"

---

## State Transition Logic

```
                    ┌──────────────────┐
                    │   buffer_hours   │
                    │      input       │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         ≤ 1.5h        1.5h - 3.0h       > 3.0h
              │              │              │
              ▼              │              ▼
          ┌───────┐          │         ┌────────────┐
          │urgent │          │         │ drift_risk │
          └───────┘          │         └─────┬──────┘
                             │               │
                             ▼               │ recovery < 60%?
                      ┌────────────┐         │
                      │  anchored  │         ▼
                      └─────┬──────┘    ┌─────────────────┐
                            │           │ high_drift_risk │
              recovery ≥ 80%│           └─────────────────┘
         AND sleep_eff ≥ 85%│
                            ▼
                       ┌─────────┐
                       │ primed  │
                       └─────────┘
```

---

## Default Thresholds

These values are stored in the database and can be adjusted via the `update_thresholds` MCP tool.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `buffer_urgent` | 1.5 hours | Threshold for urgent state |
| `buffer_anchored` | 3.0 hours | Threshold for anchored vs drift_risk |
| `recovery_low` | 60% | Below this = physiologically compromised |
| `recovery_high` | 80% | Above this = high capacity |
| `sleep_efficiency_good` | 85% | Above this = quality sleep |

---

## Edge Cases

### No Commitment Data
When `buffer_hours` is null (no calendar integration or no events):
- If `recovery >= 80%`: → `primed`
- If `recovery < 60%`: → `drift_risk`
- Otherwise: → `anchored` (default to middle state)

### Missing WHOOP Data
When health data is unavailable (API error, stale tokens):
- Classification falls back to buffer_hours only
- `primed` and `high_drift_risk` cannot be assigned without recovery data

### State Oscillation
To prevent rapid state changes:
- State transitions are logged with timestamps
- The `state_changed_recently` flag indicates a transition in the last hour
- Agent can soften behavior during transition periods

---

## Engagement Quality Labels

When logging user responses, the system tracks quality:

| Label | Description |
|-------|-------------|
| `substantive` | Meaningful response with content |
| `passive` | Acknowledgment without engagement ("ok", "thanks") |
| `tangential` | Response but off-topic |
| `emoji_only` | Just emoji, no text |
| `opt_out` | Explicit request to stop |
| `initiation` | User initiated the conversation |

This data enables future learning: which states/times/message-types get substantive responses.

---

## Agent Instruction Summary

| State | Energy | Structure | Agent Stance |
|-------|--------|-----------|--------------|
| `urgent` | Any | High | **Silent** — don't interrupt |
| `anchored` | Any | Medium | **Supportive** — light touches |
| `drift_risk` | Normal+ | Low | **Proactive** — offer structure |
| `high_drift_risk` | Low | Low | **Gentle** — prioritize care |
| `primed` | High | Medium | **Ambitious** — suggest challenges |

---

## API Reference

Get current state:
```bash
curl https://YOUR-DOMAIN/api/poke-context
```

View thresholds:
```bash
# Via MCP tool
get_state_thresholds()
```

Update thresholds:
```bash
# Via MCP tool
update_thresholds(buffer_urgent=2.0, recovery_high=75)
```
