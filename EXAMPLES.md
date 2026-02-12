# Example Agent Prompts & Expected Outputs

This document shows how the agent should behave in different states, with example prompts and expected outputs.

---

## State: `primed`

**Conditions:** Recovery ≥80%, Sleep efficiency ≥85%, Commitment 1.5-3h away

### API Response
```json
{
  "state_context": {
    "current": "primed",
    "previous": "anchored",
    "changed_recently": false,
    "reasoning": "2.5h until commitment; recovery 85% (high); sleep efficiency 91% (good)"
  },
  "whoop_data": {
    "recovery_score": 85,
    "hrv_rmssd": 52,
    "resting_hr": 54,
    "sleep_hours": 7.8,
    "sleep_efficiency": 91,
    "strain": 4.2
  },
  "wake_status": {
    "user_active_today": true,
    "hours_since_activity": 1.2
  },
  "recommendation": {
    "can_send": true,
    "context": "User primed - high recovery + good sleep + natural structure",
    "suggested_type": "deep_work_prompt"
  }
}
```

### Expected Agent Behavior

**Good prompt:**
> "Morning! Recovery at 85% and you slept well—you're in great shape today. You've got 2.5h before your 11:30 call. Good window for something challenging. Any project you've been putting off?"

**Bad prompt (generic):**
> "Good morning! How can I help you today?"

**Why:** `primed` is rare. The agent should explicitly acknowledge the high-capacity state and suggest ambitious work.

---

## State: `anchored`

**Conditions:** Commitment 1.5-3h away, Recovery <80% or Sleep <85%

### API Response
```json
{
  "state_context": {
    "current": "anchored",
    "reasoning": "2.0h until commitment; recovery 68%"
  },
  "whoop_data": {
    "recovery_score": 68,
    "hrv_rmssd": 38,
    "sleep_hours": 6.5,
    "sleep_efficiency": 82
  },
  "recommendation": {
    "can_send": true,
    "suggested_type": "energy_check"
  }
}
```

### Expected Agent Behavior

**Good prompt:**
> "Hey! You've got about 2 hours until your next thing. How are you feeling—want to knock something out or take it easy?"

**Bad prompt (too pushy):**
> "You have 2 hours—let's maximize this! What's the most important thing you could accomplish?"

**Why:** `anchored` has structure but not peak energy. Supportive, not demanding.

---

## State: `drift_risk`

**Conditions:** No commitment for 3+ hours, or no commitments at all

### API Response
```json
{
  "state_context": {
    "current": "drift_risk",
    "reasoning": "No commitments today; recovery 72%"
  },
  "whoop_data": {
    "recovery_score": 72,
    "hrv_rmssd": 41,
    "sleep_hours": 7.2
  },
  "recommendation": {
    "can_send": true,
    "suggested_type": "structure_offer"
  },
  "calendar": {
    "buffer_hours": null,
    "context": "No upcoming events"
  }
}
```

### Expected Agent Behavior

**Good prompt:**
> "Open afternoon ahead—no events on the calendar. Anything you'd like to accomplish, or is this intentional downtime? I can help set a focus block if you want some structure."

**Bad prompt (assumes productivity):**
> "No meetings today! Perfect time to be productive. What should we tackle?"

**Why:** `drift_risk` doesn't mean the user *should* work—it means structure may dissolve. Offer, don't assume.

---

## State: `high_drift_risk`

**Conditions:** `drift_risk` + Recovery <60%

### API Response
```json
{
  "state_context": {
    "current": "high_drift_risk",
    "reasoning": "No commitments; recovery 42% (low)"
  },
  "whoop_data": {
    "recovery_score": 42,
    "hrv_rmssd": 28,
    "resting_hr": 62,
    "sleep_hours": 5.1,
    "sleep_efficiency": 68
  },
  "recommendation": {
    "can_send": true,
    "suggested_type": "self_care_nudge"
  }
}
```

### Expected Agent Behavior

**Good prompt:**
> "Noticing your recovery is at 42% today—looks like a rough night. Might be a good day to keep things light. Want help protecting some downtime, or is there something small I can help with?"

**Bad prompt (ignores physiology):**
> "Free day! What ambitious project should we work on?"

**Why:** Low recovery + no structure = vulnerable state. Prioritize care, not output.

---

## State: `urgent`

**Conditions:** Commitment within 1.5 hours

### API Response
```json
{
  "state_context": {
    "current": "urgent",
    "reasoning": "0.8h until commitment"
  },
  "whoop_data": {
    "recovery_score": 55
  },
  "recommendation": {
    "can_send": false,
    "context": "User in urgent state - commitment imminent",
    "suggested_type": null
  }
}
```

### Expected Agent Behavior

**Good behavior:**
> (No message sent. Agent remains silent unless user initiates.)

**If user initiates:**
> User: "What time is my meeting?"
> Agent: "11:00am, in 48 minutes."

**Bad prompt (interrupts):**
> "Just checking in! How's your morning going?"

**Why:** `urgent` means the user is preparing or in transit. Don't interrupt.

---

## Test Scenarios

### Scenario 1: Monday Morning, Well-Rested

```bash
curl "https://YOUR-DOMAIN/api/poke-context?next_commitment_time=2026-02-12T11:30:00Z"
```

**If recovery=85%, sleep_efficiency=90%:** → `primed`
**If recovery=70%, sleep_efficiency=80%:** → `anchored`

---

### Scenario 2: Saturday Afternoon, No Plans

```bash
curl "https://YOUR-DOMAIN/api/poke-context"
# (no next_commitment_time)
```

**If recovery=75%:** → `drift_risk`
**If recovery=45%:** → `high_drift_risk`

---

### Scenario 3: 30 Minutes Before Important Meeting

```bash
curl "https://YOUR-DOMAIN/api/poke-context?next_commitment_time=2026-02-12T09:30:00Z"
# (current time: 9:00am)
```

**Any recovery:** → `urgent`

---

## MCP Tool Examples

### get_whoop_health_data

```
Input: {}
Output: {
  "recovery_score": 72,
  "hrv_rmssd": 41,
  "resting_hr": 56,
  "sleep_hours": 7.2,
  "sleep_efficiency": 85,
  "strain": 8.4,
  "timestamp": "2026-02-12T08:00:00Z"
}
```

### get_user_state

```
Input: { "next_commitment_time": "2026-02-12T14:00:00Z" }
Output: {
  "state": "anchored",
  "reasoning": "3.5h until commitment; recovery 68%",
  "buffer_hours": 3.5,
  "recovery_score": 68
}
```

### record_user_activity

```
Input: { "response_quality": "substantive" }
Output: {
  "success": true,
  "logged": {
    "quality": "substantive",
    "timestamp": "2026-02-12T10:15:00Z"
  }
}
```

---

## Response Quality Guide

When logging user responses via `record_user_activity`:

| User Response | Quality Label |
|---------------|---------------|
| "I'm going to focus on the quarterly report for the next 2 hours" | `substantive` |
| "ok" / "thanks" / "got it" | `passive` |
| "Actually, can you help me find a restaurant?" | `tangential` |
| "👍" / "🙏" | `emoji_only` |
| "Stop messaging me" / "Not now" | `opt_out` |
| User sends first message of conversation | `initiation` |
