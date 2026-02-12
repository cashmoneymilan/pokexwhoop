# Demo Assets Guide

This document outlines the demo assets to create for showcasing PokeXWhoop.

---

## Recommended Demo Assets

### 1. Morning Check-in GIF (15-30 seconds)

**What to capture:**
- Poke AI sending a morning check-in
- The message referencing actual WHOOP data ("Recovery at 72%...")
- User response
- Agent acknowledging and suggesting something appropriate for the state

**Scenario to stage:**
1. Wait for an actual morning where you have decent recovery (60-80%)
2. Have a calendar event 2-3 hours out (creates `anchored` state)
3. Screen record Poke's check-in message
4. Respond naturally
5. Capture agent's follow-up

**File:** `docs/demo-morning-checkin.gif`

---

### 2. State-Aware Intervention GIF (15-30 seconds)

**What to capture:**
- User in `drift_risk` or `high_drift_risk` state
- Poke proactively offering structure
- The contrast with what a generic assistant would say

**Scenario to stage:**
1. Pick a weekend afternoon with no events
2. Have low-ish recovery if possible (creates `high_drift_risk`)
3. Capture Poke's proactive message
4. Show how it acknowledges the physiological state

**File:** `docs/demo-drift-intervention.gif`

---

### 3. Primed State Suggestion GIF (15-30 seconds)

**What to capture:**
- High recovery day (80%+)
- Poke suggesting ambitious/challenging work
- The difference from standard "how can I help?" prompts

**Scenario to stage:**
1. Wait for a genuinely high-recovery morning
2. Have a commitment 2-3 hours out
3. Capture Poke's message encouraging deep work

**File:** `docs/demo-primed-state.gif`

---

### 4. Full Walkthrough Loom (60-90 seconds)

**Script outline:**

```
0:00 - 0:10  "This is PokeXWhoop—an MCP server connecting WHOOP health
             data to Poke AI."

0:10 - 0:25  [Show terminal] "Here's the live API response showing my
             current state..."
             curl https://pokexwhoop-production.up.railway.app/api/poke-context

0:25 - 0:40  [Show Poke chat] "And here's how Poke uses this. This morning
             my recovery was [X]%, so instead of a generic greeting, it
             knew to [describe actual behavior]."

0:40 - 0:55  [Show state transition] "When I have no commitments and low
             recovery, it shifts to gentle re-anchoring instead of
             productivity pressure."

0:55 - 1:10  [Show architecture diagram] "Under the hood: WHOOP OAuth,
             state classification engine, MCP transport to Poke, plus
             engagement tracking for learning what works."

1:10 - 1:20  "Check it out on GitHub—link in description."
```

**File:** Upload to Loom, embed link in README

---

## How to Create GIFs

### Option 1: macOS Screen Recording + Gifski

```bash
# Record screen (Cmd+Shift+5)
# Convert to GIF
gifski --fps 10 --width 600 -o output.gif recording.mov
```

### Option 2: LICEcap (Cross-platform)

Download from: https://www.cockos.com/licecap/

### Option 3: Kap (macOS)

Download from: https://getkap.co/

---

## Asset Checklist

| Asset | Status | File |
|-------|--------|------|
| Morning check-in GIF | [ ] | `docs/demo-morning-checkin.gif` |
| Drift intervention GIF | [ ] | `docs/demo-drift-intervention.gif` |
| Primed state GIF | [ ] | `docs/demo-primed-state.gif` |
| Full walkthrough Loom | [ ] | (external link) |
| Architecture diagram | [x] | `docs/architecture.svg` |

---

## Tips for Good Demos

1. **Use real data** — Staged demos feel fake. Wait for genuine scenarios.

2. **Crop aggressively** — Only show the relevant part of the screen.

3. **Add captions** — Brief text overlays explaining what's happening.

4. **Keep it short** — GIFs should be under 30 seconds. Attention spans are limited.

5. **Show the contrast** — What would a normal assistant do? What does this do instead?

6. **Include the "why"** — "Recovery at 45%" is more compelling than just "drift_risk state."

---

## Where to Use These

- **README.md** — Embed 1-2 GIFs inline
- **GitHub repo** — Link to Loom in description
- **Portfolio/pitch** — Use the full Loom walkthrough
- **Social/Twitter** — Individual GIFs work well as standalone posts
