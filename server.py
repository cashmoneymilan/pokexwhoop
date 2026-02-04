"""
WHOOP MCP Server using FastMCP standalone
Exposes WHOOP health data as MCP tools for Poke AI
"""

import os
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import aiohttp
from dotenv import load_dotenv
from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import database
from whoop_client import (
    whoop_client,
    normalize_recovery,
    normalize_sleep,
    normalize_cycle,
    get_recommended_strain
)

load_dotenv()

# Environment variables
WHOOP_CLIENT_ID = os.getenv("WHOOP_CLIENT_ID")
WHOOP_CLIENT_SECRET = os.getenv("WHOOP_CLIENT_SECRET")
WHOOP_REDIRECT_URI = os.getenv("WHOOP_REDIRECT_URI")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

# Simple in-memory state storage for OAuth
oauth_states = {}

# Initialize FastMCP server with settings
# Disable DNS rebinding protection for Railway deployment
# Server name changed to force Poke to refresh cached schema
mcp = FastMCP(
    "whoop-mcp-v2",
    instructions="Use these tools to get WHOOP health data including recovery scores, sleep metrics, strain, and weekly trends.",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
)


# ============== State Classification Helpers ==============

async def classify_state_async(
    buffer_hours: Optional[float],
    recovery_score: Optional[float],
    sleep_efficiency: Optional[float],
    settings: Optional[dict] = None
) -> str:
    """
    Core state classification logic with configurable thresholds.

    Primary signal: buffer_hours (commitment proximity)
    Modifier: recovery_score and sleep_efficiency

    Uses thresholds from database settings.
    """
    # Load settings if not provided
    if settings is None:
        settings = await database.get_user_settings()

    buffer_urgent = settings["buffer_urgent"]
    buffer_anchored = settings["buffer_anchored"]
    recovery_low = settings["recovery_low"]
    recovery_high = settings["recovery_high"]
    sleep_efficiency_good = settings["sleep_efficiency_good"]

    # If we don't have commitment data, use recovery-only classification
    if buffer_hours is None:
        if recovery_score is None:
            return "unknown"
        elif recovery_score < recovery_low:
            return "drift_risk"  # No structure + low recovery = assume drift risk
        elif recovery_score >= recovery_high and (sleep_efficiency is None or sleep_efficiency >= sleep_efficiency_good):
            return "primed"
        else:
            return "anchored"  # Default to middle state without commitment context

    # Primary classification based on buffer hours
    if buffer_hours <= buffer_urgent:
        base_state = "urgent"
    elif buffer_hours <= buffer_anchored:
        base_state = "anchored"
    else:
        base_state = "drift_risk"

    # Apply modifiers
    if base_state == "drift_risk" and recovery_score is not None and recovery_score < recovery_low:
        return "high_drift_risk"

    if base_state == "anchored":
        if (recovery_score is not None and recovery_score >= recovery_high and
            sleep_efficiency is not None and sleep_efficiency >= sleep_efficiency_good):
            return "primed"

    return base_state


def classify_state(
    buffer_hours: Optional[float],
    recovery_score: Optional[float],
    sleep_efficiency: Optional[float]
) -> str:
    """
    Synchronous wrapper for classify_state_async with default thresholds.
    Used for backwards compatibility.
    """
    # Use default thresholds for sync calls
    buffer_urgent = 1.5
    buffer_anchored = 3.0
    recovery_low = 60
    recovery_high = 80
    sleep_efficiency_good = 85.0

    if buffer_hours is None:
        if recovery_score is None:
            return "unknown"
        elif recovery_score < recovery_low:
            return "drift_risk"
        elif recovery_score >= recovery_high and (sleep_efficiency is None or sleep_efficiency >= sleep_efficiency_good):
            return "primed"
        else:
            return "anchored"

    if buffer_hours <= buffer_urgent:
        base_state = "urgent"
    elif buffer_hours <= buffer_anchored:
        base_state = "anchored"
    else:
        base_state = "drift_risk"

    if base_state == "drift_risk" and recovery_score is not None and recovery_score < recovery_low:
        return "high_drift_risk"

    if base_state == "anchored":
        if (recovery_score is not None and recovery_score >= recovery_high and
            sleep_efficiency is not None and sleep_efficiency >= sleep_efficiency_good):
            return "primed"

    return base_state


def generate_reasoning(
    state: str,
    buffer_hours: Optional[float],
    recovery_score: Optional[float],
    sleep_efficiency: Optional[float]
) -> str:
    """
    Generate human-readable explanation for the state classification.
    Useful for debugging and for the pitch demo.
    """

    parts = []

    # Buffer hours component
    if buffer_hours is not None:
        if buffer_hours <= 1.5:
            parts.append(f"{buffer_hours:.1f}h until commitment (urgent)")
        elif buffer_hours <= 3:
            parts.append(f"{buffer_hours:.1f}h until commitment (structured)")
        else:
            parts.append(f"{buffer_hours:.1f}h until commitment (high slack)")
    else:
        parts.append("no commitment data provided")

    # Recovery component
    if recovery_score is not None:
        if recovery_score < 60:
            parts.append(f"recovery {recovery_score}% (low)")
        elif recovery_score >= 80:
            parts.append(f"recovery {recovery_score}% (high)")
        else:
            parts.append(f"recovery {recovery_score}% (moderate)")

    # Sleep efficiency component
    if sleep_efficiency is not None:
        if sleep_efficiency >= 85:
            parts.append(f"sleep efficiency {sleep_efficiency}% (good)")
        else:
            parts.append(f"sleep efficiency {sleep_efficiency}% (suboptimal)")

    return " | ".join(parts)


# ============== MCP Tools ==============

@mcp.tool()
async def get_today_summary() -> dict:
    """
    Get a comprehensive summary of today's WHOOP data including recovery score,
    strain, sleep duration and quality, HRV, resting heart rate, and recommended
    strain range.
    """
    try:
        print("[MCP] Fetching recovery data...")
        recovery_data = await whoop_client.get_recovery(limit=1)
        print(f"[MCP] Recovery: {recovery_data}")

        print("[MCP] Fetching sleep data...")
        sleep_data = await whoop_client.get_sleep(limit=1)
        print(f"[MCP] Sleep: {sleep_data}")

        print("[MCP] Fetching cycle data...")
        cycle_data = await whoop_client.get_cycles(limit=1)
        print(f"[MCP] Cycle: {cycle_data}")

        recovery = normalize_recovery(recovery_data[0]) if recovery_data else None
        sleep = normalize_sleep(sleep_data[0]) if sleep_data else None
        cycle = normalize_cycle(cycle_data[0]) if cycle_data else None

        summary = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "recovery": None,
            "sleep": None,
            "strain": None,
            "recommendation": None
        }

        if recovery:
            summary["recovery"] = {
                "score": recovery["recovery_score"],
                "state": recovery["state"],
                "hrv": recovery["hrv"],
                "resting_hr": recovery["resting_hr"]
            }
            summary["recommendation"] = get_recommended_strain(recovery["recovery_score"])

        if sleep:
            summary["sleep"] = {
                "total": sleep["total_sleep_formatted"],
                "efficiency": sleep["sleep_efficiency"],
                "debt": sleep["sleep_debt"],
                "disturbances": sleep["disturbances"]
            }

        if cycle:
            summary["strain"] = {
                "score": cycle["strain"],
                "calories": cycle["kilojoules"],
                "avg_hr": cycle["average_hr"],
                "max_hr": cycle["max_hr"]
            }

        return summary

    except Exception as e:
        return {"error": str(e), "message": "Failed to fetch today's summary. Make sure WHOOP is authorized."}


@mcp.tool()
async def get_latest_recovery() -> dict:
    """
    Get the most recent recovery data including recovery score (0-100),
    HRV (heart rate variability in milliseconds), resting heart rate,
    and recovery state (green/yellow/red).
    """
    try:
        recovery_data = await whoop_client.get_recovery(limit=1)
        if not recovery_data:
            return {"error": "no_data", "message": "No recovery data available"}
        return normalize_recovery(recovery_data[0])
    except Exception as e:
        return {"error": str(e), "message": "Failed to fetch recovery data"}


@mcp.tool()
async def get_last_sleep() -> dict:
    """
    Get the most recent sleep data including total sleep time, sleep debt,
    sleep efficiency percentage, number of disturbances, and time spent
    in each sleep stage (REM, deep, light, awake).
    """
    try:
        sleep_data = await whoop_client.get_sleep(limit=1)
        if not sleep_data:
            return {"error": "no_data", "message": "No sleep data available"}
        return normalize_sleep(sleep_data[0])
    except Exception as e:
        return {"error": str(e), "message": "Failed to fetch sleep data"}


@mcp.tool()
async def get_trends(metric: str, days: int = 7) -> dict:
    """
    Get trends for a specific health metric over a custom time period.

    Args:
        metric: The metric to analyze - "recovery", "strain", "sleep", or "hrv"
        days: Number of days to look back (default 7, max 90)
    """
    try:
        if metric not in ["recovery", "strain", "sleep", "hrv"]:
            return {"error": "invalid_metric", "message": "Metric must be: recovery, strain, sleep, or hrv"}

        # Cap at 90 days to avoid excessive API calls
        days = min(max(1, days), 90)

        if metric == "recovery":
            data = await whoop_client.get_recovery(limit=days, days=days)
            values = [{"date": normalize_recovery(d)["date"], "value": normalize_recovery(d)["recovery_score"]}
                     for d in data if normalize_recovery(d)]
        elif metric == "hrv":
            data = await whoop_client.get_recovery(limit=days, days=days)
            values = []
            for d in data:
                normalized = normalize_recovery(d)
                if normalized and normalized.get("hrv"):
                    values.append({
                        "date": normalized["date"],
                        "value": round(normalized["hrv"], 1)
                    })
        elif metric == "strain":
            data = await whoop_client.get_cycles(limit=days, days=days)
            values = [{"date": normalize_cycle(d)["date"], "value": round(normalize_cycle(d)["strain"], 1)}
                     for d in data if normalize_cycle(d)]
        else:
            data = await whoop_client.get_sleep(limit=days, days=days)
            values = []
            for d in data:
                normalized = normalize_sleep(d)
                if normalized and normalized.get("total_sleep"):
                    values.append({
                        "date": normalized["date"],
                        "value": round(normalized["total_sleep"] / 3600, 1)
                    })

        if not values:
            return {"error": "no_data", "message": f"No {metric} data available"}

        numeric = [v["value"] for v in values]
        avg = round(sum(numeric) / len(numeric), 1)

        # Determine unit based on metric
        units = {"recovery": "%", "strain": "strain", "sleep": "hours", "hrv": "ms"}

        return {
            "metric": metric,
            "period": f"{days} days",
            "average": avg,
            "data_points": values,
            "unit": units[metric]
        }

    except Exception as e:
        return {"error": str(e), "message": f"Failed to fetch {metric} trends"}


@mcp.tool()
async def get_user_state(
    next_commitment_time: Optional[str] = None,
    estimated_wake_time: Optional[str] = None
) -> dict:
    """
    Get the user's current state classification based on WHOOP data and schedule context.

    This is the core intelligence layer that determines how Poke should behave.
    Now auto-logs state transitions when state changes.

    Args:
        next_commitment_time: ISO format datetime string of next hard commitment (e.g., "2026-01-23T10:00:00")
        estimated_wake_time: ISO format datetime string of when user woke/will wake (e.g., "2026-01-23T08:30:00")

    Returns:
        State classification with reasoning and metrics.

    States:
        - urgent: commitment within buffer_urgent hours of waking, need immediate action
        - anchored: commitment buffer_urgent-buffer_anchored hours away, natural structure exists
        - drift_risk: commitment buffer_anchored+ hours away or none, structure may dissolve
        - high_drift_risk: drift_risk + low recovery, both structure and physiology compromised
        - primed: anchored + high recovery + good sleep, peak performance state
    """
    try:
        # Fetch WHOOP data
        recovery_data = await whoop_client.get_recovery(limit=1)
        sleep_data = await whoop_client.get_sleep(limit=1)

        # Normalize
        recovery = normalize_recovery(recovery_data[0]) if recovery_data else None
        sleep = normalize_sleep(sleep_data[0]) if sleep_data else None

        # Extract key metrics (with corrected field names)
        recovery_score = recovery["recovery_score"] if recovery else None
        sleep_efficiency = sleep.get("sleep_efficiency") if sleep else None
        sleep_hours = (sleep.get("total_sleep") / 3600) if sleep and sleep.get("total_sleep") else None
        hrv = recovery["hrv"] if recovery else None
        resting_hr = recovery["resting_hr"] if recovery else None

        # Calculate buffer hours if commitment provided
        buffer_hours = None
        if next_commitment_time and estimated_wake_time:
            try:
                commitment_dt = datetime.fromisoformat(next_commitment_time.replace('Z', '+00:00'))
                wake_dt = datetime.fromisoformat(estimated_wake_time.replace('Z', '+00:00'))
                buffer_hours = (commitment_dt - wake_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                buffer_hours = None

        # State classification logic using async version with configurable thresholds
        settings = await database.get_user_settings()
        state = await classify_state_async(buffer_hours, recovery_score, sleep_efficiency, settings)
        reasoning = generate_reasoning(state, buffer_hours, recovery_score, sleep_efficiency)

        # Auto-log state transitions
        state_changed = False
        previous_state = None
        try:
            ctx = await database.get_poke_context()
            previous_state = ctx.get("current_state") if ctx else None

            if previous_state and previous_state != state:
                # Log the transition
                trigger = "time_passed"
                if next_commitment_time:
                    trigger = "commitment_approaching"
                elif recovery_score and recovery_score != ctx.get("last_recovery_score"):
                    trigger = "recovery_change"

                await database.log_state_transition(
                    from_state=previous_state,
                    to_state=state,
                    trigger=trigger,
                    recovery_at_transition=recovery_score
                )
                state_changed = True

            # Update poke context with current state
            await database.update_poke_context({
                "current_state": state,
                "previous_state": previous_state,
                "state_changed_at": datetime.now() if state_changed else (ctx.get("state_changed_at") if ctx else datetime.now())
            })

        except Exception as ctx_error:
            print(f"[get_user_state] Context update error (non-fatal): {ctx_error}")

        return {
            "state": state,
            "state_changed": state_changed,
            "previous_state": previous_state,
            "buffer_hours": round(buffer_hours, 1) if buffer_hours is not None else None,
            "next_commitment_time": next_commitment_time,
            "estimated_wake_time": estimated_wake_time,
            "recovery": {
                "score": recovery_score,
                "hrv": hrv,
                "resting_hr": resting_hr
            },
            "sleep": {
                "hours": round(sleep_hours, 1) if sleep_hours else None,
                "efficiency": round(sleep_efficiency, 1) if sleep_efficiency else None
            },
            "reasoning": reasoning,
            "thresholds_used": {
                "buffer_urgent": settings["buffer_urgent"],
                "buffer_anchored": settings["buffer_anchored"],
                "recovery_low": settings["recovery_low"],
                "recovery_high": settings["recovery_high"]
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "state": "unknown",
            "error": str(e),
            "reasoning": "Could not determine state due to data fetch error",
            "timestamp": datetime.now().isoformat()
        }


@mcp.tool()
async def get_state_thresholds() -> dict:
    """
    Returns the current state classification thresholds.
    These values are now configurable via update_thresholds().
    """
    settings = await database.get_user_settings()

    return {
        "states": {
            "urgent": {
                "description": "Commitment within buffer_urgent hours of waking",
                "buffer_hours": f"<= {settings['buffer_urgent']}",
                "poke_behavior": "Immediate time math, no fluff, get out the door"
            },
            "anchored": {
                "description": f"Commitment {settings['buffer_urgent']}-{settings['buffer_anchored']} hours away, natural structure exists",
                "buffer_hours": f"{settings['buffer_urgent']} - {settings['buffer_anchored']}",
                "poke_behavior": "Standard briefing, check-ins every 3-4 hours"
            },
            "drift_risk": {
                "description": f"Commitment {settings['buffer_anchored']}+ hours away or none, structure may dissolve",
                "buffer_hours": f"> {settings['buffer_anchored']} or none",
                "poke_behavior": "Offer structure, check-ins every 2 hours, meal prompts"
            },
            "high_drift_risk": {
                "description": f"Drift risk + low recovery, both structure and physiology compromised",
                "condition": f"drift_risk AND recovery < {settings['recovery_low']}%",
                "poke_behavior": "More assertive structure, shorter task blocks, frequent meal prompts"
            },
            "primed": {
                "description": "Anchored + high recovery + good sleep, peak state",
                "condition": f"anchored AND recovery >= {settings['recovery_high']}% AND sleep_efficiency >= {settings['sleep_efficiency_good']}%",
                "poke_behavior": "Push hard problems, minimize interruptions, trust self-regulation"
            }
        },
        "thresholds": {
            "buffer_urgent": settings["buffer_urgent"],
            "buffer_anchored": settings["buffer_anchored"],
            "recovery_low": settings["recovery_low"],
            "recovery_high": settings["recovery_high"],
            "sleep_efficiency_good": settings["sleep_efficiency_good"]
        },
        "configurable": True,
        "note": "Use update_thresholds() to adjust these values"
    }


# ============== Priority 1: Unified Context Tools ==============

@mcp.tool()
async def get_poke_context(
    next_commitment_time: Optional[str] = None,
    calendar_context: Optional[str] = None
) -> dict:
    """
    THE key tool Poke calls at every trigger.

    Returns comprehensive context including:
    - Wake status: whether user is confirmed awake today
    - Check-in status: last sent, unanswered count
    - State context: current state, recent changes
    - Opt-out status
    - Calendar: upcoming commitments and buffer time
    - Recommendation: whether to send, suggested type

    Args:
        next_commitment_time: ISO timestamp of user's next calendar commitment (optional)
        calendar_context: Brief description of upcoming events (optional)

    Call this at the START of every hourly trigger before deciding to send a message.
    """
    try:
        ctx = await database.get_poke_context()
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # Calculate buffer to next commitment
        buffer_hours = None
        if next_commitment_time:
            try:
                commitment_dt = datetime.fromisoformat(next_commitment_time.replace('Z', '+00:00'))
                buffer_hours = (commitment_dt - now).total_seconds() / 3600
                if buffer_hours < 0:
                    buffer_hours = None  # Commitment is in the past
            except:
                pass

        # Initialize defaults if no context exists
        if not ctx:
            ctx = {
                "last_user_activity": None,
                "last_user_activity_date": None,
                "last_response_quality": None,
                "last_checkin_sent": None,
                "last_checkin_type": None,
                "last_checkin_id": None,
                "checkins_since_response": 0,
                "current_state": None,
                "previous_state": None,
                "state_changed_at": None,
                "opt_out_until": None,
                "opt_out_reason": None
            }

        # Calculate wake status
        user_active_today = ctx.get("last_user_activity_date") == today
        hours_since_activity = None
        if ctx.get("last_user_activity"):
            activity_time = ctx["last_user_activity"]
            if isinstance(activity_time, str):
                activity_time = datetime.fromisoformat(activity_time.replace('Z', '+00:00'))
            hours_since_activity = (now - activity_time.replace(tzinfo=None)).total_seconds() / 3600

        # Calculate check-in status
        hours_since_checkin = None
        if ctx.get("last_checkin_sent"):
            checkin_time = ctx["last_checkin_sent"]
            if isinstance(checkin_time, str):
                checkin_time = datetime.fromisoformat(checkin_time.replace('Z', '+00:00'))
            hours_since_checkin = (now - checkin_time.replace(tzinfo=None)).total_seconds() / 3600

        # Check opt-out status
        opt_out_active = False
        opt_out_until = None
        if ctx.get("opt_out_until"):
            opt_until = ctx["opt_out_until"]
            if isinstance(opt_until, str):
                opt_until = datetime.fromisoformat(opt_until.replace('Z', '+00:00'))
            opt_out_active = opt_until.replace(tzinfo=None) > now
            opt_out_until = opt_until.isoformat() if opt_out_active else None

        # State change tracking
        state_changed_recently = False
        hours_in_current_state = None
        if ctx.get("state_changed_at"):
            change_time = ctx["state_changed_at"]
            if isinstance(change_time, str):
                change_time = datetime.fromisoformat(change_time.replace('Z', '+00:00'))
            hours_in_current_state = (now - change_time.replace(tzinfo=None)).total_seconds() / 3600
            state_changed_recently = hours_in_current_state < 2  # Changed in last 2 hours

        # Generate recommendation
        unanswered = ctx.get("checkins_since_response", 0)
        can_send = True
        reason_parts = []
        suggested_type = "energy_check"  # Default
        suggested_wait = False

        # Check opt-out first
        if opt_out_active:
            can_send = False
            reason_parts.append(f"User opted out until {opt_out_until}")
            suggested_wait = True

        # Check wake status
        elif not user_active_today and now.hour < 10:
            can_send = False
            reason_parts.append("User not confirmed awake yet (before 10am)")
            suggested_wait = True

        # Check unanswered count
        elif unanswered >= 2:
            can_send = False
            reason_parts.append(f"{unanswered} unanswered check-ins")
            suggested_wait = True

        # Check time since last check-in
        elif hours_since_checkin is not None and hours_since_checkin < 1.5:
            can_send = False
            reason_parts.append(f"Only {hours_since_checkin:.1f}h since last check-in")
            suggested_wait = True

        # If we can send, build positive reason
        if can_send:
            if user_active_today:
                reason_parts.append("User active today")
            if ctx.get("last_response_quality") == "substantive":
                reason_parts.append("Last response was substantive")
            if state_changed_recently and ctx.get("current_state") in ["anchored", "primed"]:
                reason_parts.append("State recently improved")
            if hours_since_checkin and hours_since_checkin > 3:
                reason_parts.append(f"{hours_since_checkin:.1f}h since last check-in")

            # Suggest message type based on context
            if now.hour < 10 and user_active_today:
                suggested_type = "morning_briefing"
            elif now.hour in [12, 13, 18, 19]:
                suggested_type = "meal_prompt"
            elif ctx.get("current_state") in ["drift_risk", "high_drift_risk"]:
                suggested_type = "task_check"
            elif ctx.get("current_state") == "anchored":
                suggested_type = "commitment_reminder"

        return {
            "wake_status": {
                "user_active_today": user_active_today,
                "last_activity": ctx.get("last_user_activity").isoformat() if ctx.get("last_user_activity") else None,
                "hours_since_activity": round(hours_since_activity, 1) if hours_since_activity else None,
                "last_response_quality": ctx.get("last_response_quality")
            },
            "checkin_status": {
                "last_sent": ctx.get("last_checkin_sent").isoformat() if ctx.get("last_checkin_sent") else None,
                "hours_since_checkin": round(hours_since_checkin, 1) if hours_since_checkin else None,
                "type": ctx.get("last_checkin_type"),
                "unanswered_count": unanswered,
                "last_checkin_id": ctx.get("last_checkin_id")
            },
            "state_context": {
                "current": ctx.get("current_state"),
                "previous": ctx.get("previous_state"),
                "changed_recently": state_changed_recently,
                "hours_in_current_state": round(hours_in_current_state, 1) if hours_in_current_state else None
            },
            "opt_out": {
                "active": opt_out_active,
                "until": opt_out_until,
                "reason": ctx.get("opt_out_reason") if opt_out_active else None
            },
            "recommendation": {
                "can_send": can_send,
                "reason": "; ".join(reason_parts) if reason_parts else "Ready to send",
                "suggested_type": suggested_type if can_send else None,
                "suggested_wait": suggested_wait
            },
            "calendar": {
                "next_commitment_time": next_commitment_time,
                "buffer_hours": round(buffer_hours, 1) if buffer_hours else None,
                "calendar_context": calendar_context
            },
            "timestamp": now.isoformat()
        }

    except Exception as e:
        return {
            "error": str(e),
            "recommendation": {
                "can_send": True,
                "reason": "Error fetching context, defaulting to allow",
                "suggested_type": "energy_check",
                "suggested_wait": False
            },
            "timestamp": datetime.now().isoformat()
        }


@mcp.tool()
async def record_user_activity(response_quality: str) -> dict:
    """
    Record user activity when they send ANY message.

    Call this whenever the user sends a message to confirm they're awake
    and track engagement quality.

    Args:
        response_quality: Quality of the response. One of:
            - "substantive": Multiple messages, detailed response
            - "passive": "ok", "thanks", brief acknowledgment
            - "tangential": Response about something else
            - "emoji_only": Just emoji reaction
            - "opt_out": "busy", "focus", "dnd"
            - "initiation": User messaged first (not responding to check-in)

    Returns:
        Confirmation of what was recorded.
    """
    valid_qualities = ["substantive", "passive", "tangential", "emoji_only", "opt_out", "initiation"]
    if response_quality not in valid_qualities:
        return {"error": f"Invalid quality. Must be one of: {valid_qualities}"}

    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # Get current context to find last check-in
        ctx = await database.get_poke_context()
        last_checkin_id = ctx.get("last_checkin_id") if ctx else None

        # Calculate response time if we have a last check-in
        response_time_minutes = None
        if last_checkin_id and ctx and ctx.get("last_checkin_sent"):
            checkin_time = ctx["last_checkin_sent"]
            if isinstance(checkin_time, str):
                checkin_time = datetime.fromisoformat(checkin_time.replace('Z', '+00:00'))
            response_time_minutes = int((now - checkin_time.replace(tzinfo=None)).total_seconds() / 60)

        # Mark the last check-in as responded (if it's a response, not initiation)
        if last_checkin_id and response_quality != "initiation":
            await database.mark_checkin_responded(
                last_checkin_id,
                response_quality,
                response_time_minutes
            )

        # Handle opt-out
        opt_out_updates = {}
        if response_quality == "opt_out":
            # Default 2-hour opt-out
            opt_out_updates = {
                "opt_out_until": now + timedelta(hours=2),
                "opt_out_reason": "User indicated busy"
            }

        # Update poke context
        updates = {
            "last_user_activity": now,
            "last_user_activity_date": today,
            "last_response_quality": response_quality,
            "checkins_since_response": 0,  # Reset counter
            **opt_out_updates
        }
        await database.update_poke_context(updates)

        return {
            "recorded": True,
            "quality": response_quality,
            "wake_confirmed": True,
            "date": today,
            "checkin_marked_responded": last_checkin_id if response_quality != "initiation" else None,
            "response_time_minutes": response_time_minutes,
            "opt_out_set": response_quality == "opt_out",
            "timestamp": now.isoformat()
        }

    except Exception as e:
        return {"error": str(e), "recorded": False}


@mcp.tool()
async def record_checkin_sent(
    checkin_type: str,
    trigger_source: str = "hourly",
    user_state: Optional[str] = None,
    recovery_score: Optional[int] = None
) -> dict:
    """
    Record that a check-in was sent.

    Call this AFTER sending any check-in message so we can track it.

    Args:
        checkin_type: Type of check-in. One of:
            - "morning_briefing": First message of day with day overview
            - "meal_prompt": Food/nutrition reminder
            - "commitment_reminder": Upcoming event prep
            - "energy_check": How are you feeling?
            - "task_check": Progress on current work
            - "generic": Open-ended check-in

        trigger_source: What triggered this check-in:
            - "hourly": Regular hourly trigger (default)
            - "recovery": Recovery-based trigger
            - "scheduled": Specific time-based trigger
            - "reactive": Response to user behavior

        user_state: Current user state (optional, for logging)
        recovery_score: Current recovery score (optional, for logging)

    Returns:
        The check-in ID for reference.
    """
    valid_types = ["morning_briefing", "meal_prompt", "commitment_reminder",
                   "energy_check", "task_check", "generic"]
    valid_sources = ["hourly", "recovery", "scheduled", "reactive"]

    if checkin_type not in valid_types:
        return {"error": f"Invalid checkin_type. Must be one of: {valid_types}"}
    if trigger_source not in valid_sources:
        return {"error": f"Invalid trigger_source. Must be one of: {valid_sources}"}

    try:
        now = datetime.now()

        # Get current context for previous checkin ID
        ctx = await database.get_poke_context()
        previous_id = ctx.get("last_checkin_id") if ctx else None

        # Close out any unanswered check-ins
        await database.close_unanswered_checkins()

        # Log the new check-in
        checkin_id = await database.log_checkin(
            checkin_type=checkin_type,
            trigger_source=trigger_source,
            user_state=user_state,
            recovery_score=recovery_score,
            previous_checkin_id=previous_id
        )

        # Update poke context
        checkins_since = (ctx.get("checkins_since_response", 0) + 1) if ctx else 1
        await database.update_poke_context({
            "last_checkin_sent": now,
            "last_checkin_type": checkin_type,
            "last_checkin_id": checkin_id,
            "checkins_since_response": checkins_since
        })

        return {
            "recorded": True,
            "checkin_id": checkin_id,
            "type": checkin_type,
            "trigger": trigger_source,
            "checkins_since_response": checkins_since,
            "timestamp": now.isoformat()
        }

    except Exception as e:
        return {"error": str(e), "recorded": False}


# ============== Priority 2: Engagement Tracking ==============

@mcp.tool()
async def get_engagement_insights(days: int = 30) -> dict:
    """
    Get insights on what types of check-ins actually get responses.

    Use this periodically (e.g., weekly) to understand what's working
    and adjust your messaging strategy.

    Args:
        days: Number of days to analyze (default 30)

    Returns:
        Response rates by type, quality breakdown, best/worst hours,
        and actionable recommendations.
    """
    try:
        stats = await database.get_engagement_stats(days)

        # Calculate response rates by type
        response_rates = {}
        for ts in stats["type_stats"]:
            if ts["total"] > 0:
                rate = ts["responded_count"] / ts["total"]
                response_rates[ts["checkin_type"]] = round(rate, 2)

        # Calculate quality breakdown
        total_with_quality = sum(qs["count"] for qs in stats["quality_stats"])
        quality_breakdown = {}
        for qs in stats["quality_stats"]:
            if total_with_quality > 0:
                quality_breakdown[qs["response_quality"]] = round(qs["count"] / total_with_quality, 2)

        # Find best and worst hours
        hour_rates = []
        for hs in stats["hour_stats"]:
            if hs["total"] > 0:
                rate = hs["responded_count"] / hs["total"]
                hour_rates.append((hs["hour_of_day"], rate, hs["total"]))

        hour_rates.sort(key=lambda x: x[1], reverse=True)
        best_hours = [h[0] for h in hour_rates[:3] if h[1] > 0.4]
        worst_hours = [h[0] for h in hour_rates[-3:] if h[1] < 0.3]

        # Calculate overall response rate
        total_checkins = stats["total"]
        total_responded = sum(ts["responded_count"] for ts in stats["type_stats"])
        overall_rate = round(total_responded / total_checkins, 2) if total_checkins > 0 else 0

        # Generate recommendation
        recommendations = []
        if response_rates:
            best_type = max(response_rates.items(), key=lambda x: x[1])
            worst_type = min(response_rates.items(), key=lambda x: x[1])
            if best_type[1] > worst_type[1] + 0.2:
                recommendations.append(f"{best_type[0]} messages get {int(best_type[1]*100)}% response rate - use more")
            if worst_type[1] < 0.3:
                recommendations.append(f"{worst_type[0]} messages get only {int(worst_type[1]*100)}% response - reduce or improve")

        if quality_breakdown.get("substantive", 0) < 0.2:
            recommendations.append("Low substantive responses - try more specific, actionable prompts")

        if stats["initiations"] > 5:
            recommendations.append(f"User initiated {stats['initiations']} times - engagement is healthy")

        return {
            "response_rates": response_rates,
            "response_quality_breakdown": quality_breakdown,
            "engagement_depth": {
                "user_initiated_count": stats["initiations"],
                "user_initiated_pct": round(stats["initiations"] / total_checkins, 2) if total_checkins > 0 else 0
            },
            "best_hours": best_hours,
            "worst_hours": worst_hours,
            "total_checkins": total_checkins,
            "overall_response_rate": overall_rate,
            "period_days": days,
            "recommendations": recommendations if recommendations else ["Not enough data for recommendations yet"]
        }

    except Exception as e:
        return {"error": str(e), "message": "Failed to calculate engagement insights"}


# ============== Priority 2B: State Transition Tracking ==============

@mcp.tool()
async def get_day_flow_patterns(days: int = 30) -> dict:
    """
    Understand how the user's day typically flows between states.

    Shows common transitions, typical timing, and state duration patterns.

    Args:
        days: Number of days to analyze (default 30)

    Returns:
        Typical morning pattern, common transitions, and average state durations.
    """
    try:
        stats = await database.get_state_transition_stats(days)

        # Format transitions
        common_transitions = []
        for t in stats["transitions"][:10]:  # Top 10
            common_transitions.append({
                "from": t["from_state"],
                "to": t["to_state"],
                "frequency": t["frequency"],
                "avg_hour": round(t["avg_hour"], 1) if t["avg_hour"] else None
            })

        # Determine typical morning pattern
        morning_transitions = [t for t in common_transitions
                             if t["avg_hour"] and 6 <= t["avg_hour"] <= 11]
        typical_morning = None
        if morning_transitions:
            most_common_morning = morning_transitions[0]
            typical_morning = f"{most_common_morning['from']} → {most_common_morning['to']} (around {most_common_morning['avg_hour']}am)"

        # State entry counts
        state_entries = {s["state"]: s["entries"] for s in stats["state_entries"]}

        return {
            "typical_morning": typical_morning,
            "common_transitions": common_transitions,
            "state_entries": state_entries,
            "period_days": days,
            "note": "State durations require more data points for accurate calculation"
        }

    except Exception as e:
        return {"error": str(e), "message": "Failed to get day flow patterns"}


# ============== Priority 3: Data Validation ==============

@mcp.tool()
async def validate_today_data() -> dict:
    """
    Validate today's WHOOP data for anomalies.

    Checks for unusual jumps in recovery (>30%) which may indicate
    sensor issues or data quality problems.

    Returns:
        Anomaly status, data quality assessment, and credibility score.
    """
    try:
        # Get today's and yesterday's recovery
        recovery_data = await whoop_client.get_recovery(limit=2, days=2)

        if not recovery_data:
            return {
                "has_anomalies": False,
                "data_quality": "no_data",
                "message": "No recovery data available"
            }

        today_recovery = normalize_recovery(recovery_data[0]) if recovery_data else None
        yesterday_recovery = normalize_recovery(recovery_data[1]) if len(recovery_data) > 1 else None

        anomalies = []
        current_score = today_recovery["recovery_score"] if today_recovery else None
        previous_score = yesterday_recovery["recovery_score"] if yesterday_recovery else None

        # Log recovery for history tracking
        if current_score is not None and today_recovery:
            await database.log_recovery(
                date=today_recovery["date"],
                recovery_score=current_score,
                previous_day_score=previous_score
            )

        # Check for anomaly
        if current_score is not None and previous_score is not None:
            delta = current_score - previous_score
            if abs(delta) > 30:
                direction = "jump" if delta > 0 else "drop"
                anomalies.append({
                    "metric": "recovery",
                    "previous": previous_score,
                    "current": current_score,
                    "delta": delta,
                    "recommendation": f"Unusual {direction} of {abs(delta)}% - verify WHOOP band positioning or consider using previous baseline"
                })

        # Calculate credibility score
        anomaly_count = await database.get_anomaly_count(days=14)
        if anomaly_count == 0:
            credibility_score = 1.0
            anomaly_note = "No anomalies in last 14 days"
        elif anomaly_count == 1:
            credibility_score = 0.85
            anomaly_note = "1 anomaly in last 14 days"
        elif anomaly_count <= 3:
            credibility_score = 0.7
            anomaly_note = f"{anomaly_count} anomalies in last 14 days"
        else:
            credibility_score = 0.5
            anomaly_note = f"{anomaly_count} anomalies in last 14 days - data quality concerns"

        # Determine data quality
        if anomalies:
            data_quality = "review_recommended"
        elif credibility_score < 0.7:
            data_quality = "historically_erratic"
        else:
            data_quality = "good"

        return {
            "has_anomalies": len(anomalies) > 0,
            "anomalies": anomalies,
            "data_quality": data_quality,
            "credibility": {
                "score": credibility_score,
                "anomaly_frequency": anomaly_note
            },
            "today": {
                "recovery": current_score,
                "date": today_recovery["date"] if today_recovery else None
            },
            "yesterday": {
                "recovery": previous_score,
                "date": yesterday_recovery["date"] if yesterday_recovery else None
            }
        }

    except Exception as e:
        return {"error": str(e), "message": "Failed to validate data"}


# ============== Priority 4: Configurable Thresholds ==============

@mcp.tool()
async def update_thresholds(
    buffer_urgent: Optional[float] = None,
    buffer_anchored: Optional[float] = None,
    recovery_low: Optional[int] = None,
    recovery_high: Optional[int] = None,
    sleep_efficiency_good: Optional[float] = None
) -> dict:
    """
    Update state classification thresholds.

    Only specify the values you want to change.

    Args:
        buffer_urgent: Hours until commitment for "urgent" state (default 1.5)
        buffer_anchored: Hours until commitment for "anchored" state (default 3.0)
        recovery_low: Recovery % below which is considered low (default 60)
        recovery_high: Recovery % above which is considered high (default 80)
        sleep_efficiency_good: Sleep efficiency % considered good (default 85)

    Returns:
        Updated threshold values.
    """
    try:
        updates = {}
        if buffer_urgent is not None:
            if buffer_urgent <= 0 or buffer_urgent >= 24:
                return {"error": "buffer_urgent must be between 0 and 24"}
            updates["buffer_urgent"] = buffer_urgent

        if buffer_anchored is not None:
            if buffer_anchored <= 0 or buffer_anchored >= 24:
                return {"error": "buffer_anchored must be between 0 and 24"}
            updates["buffer_anchored"] = buffer_anchored

        if recovery_low is not None:
            if recovery_low < 0 or recovery_low > 100:
                return {"error": "recovery_low must be between 0 and 100"}
            updates["recovery_low"] = recovery_low

        if recovery_high is not None:
            if recovery_high < 0 or recovery_high > 100:
                return {"error": "recovery_high must be between 0 and 100"}
            updates["recovery_high"] = recovery_high

        if sleep_efficiency_good is not None:
            if sleep_efficiency_good < 0 or sleep_efficiency_good > 100:
                return {"error": "sleep_efficiency_good must be between 0 and 100"}
            updates["sleep_efficiency_good"] = sleep_efficiency_good

        if not updates:
            return {"error": "No valid updates provided"}

        # Validate relationships
        current = await database.get_user_settings()
        new_settings = {**current, **updates}

        if new_settings["buffer_urgent"] >= new_settings["buffer_anchored"]:
            return {"error": "buffer_urgent must be less than buffer_anchored"}

        if new_settings["recovery_low"] >= new_settings["recovery_high"]:
            return {"error": "recovery_low must be less than recovery_high"}

        await database.update_user_settings(updates)

        return {
            "updated": True,
            "changes": updates,
            "current_thresholds": await database.get_user_settings()
        }

    except Exception as e:
        return {"error": str(e), "updated": False}


# ============== Priority 5: Opt-out Keywords ==============

@mcp.tool()
async def process_opt_out(keyword: str, duration_hours: Optional[float] = None) -> dict:
    """
    Process an opt-out request from the user.

    Call this when the user indicates they want to pause check-ins.

    Args:
        keyword: The opt-out keyword detected. Common ones:
            - "busy" → 2 hours
            - "focus" → 3 hours
            - "dnd" → 4 hours
            - "meeting" → 1 hour
        duration_hours: Override the default duration (optional)

    Returns:
        Opt-out status and when it expires.
    """
    try:
        # Default durations by keyword
        default_durations = {
            "busy": 2,
            "focus": 3,
            "dnd": 4,
            "meeting": 1,
            "sleep": 8,
            "break": 0.5
        }

        # Determine duration
        if duration_hours is not None:
            hours = duration_hours
        else:
            hours = default_durations.get(keyword.lower(), 2)  # Default 2 hours

        # Cap at 12 hours
        hours = min(hours, 12)

        now = datetime.now()
        opt_out_until = now + timedelta(hours=hours)

        # Update context
        await database.update_poke_context({
            "opt_out_until": opt_out_until,
            "opt_out_reason": keyword
        })

        return {
            "opt_out_set": True,
            "keyword": keyword,
            "duration_hours": hours,
            "until": opt_out_until.isoformat(),
            "message": f"Check-ins paused for {hours} hours"
        }

    except Exception as e:
        return {"error": str(e), "opt_out_set": False}


# ============== Custom HTTP Routes ==============

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    """Server info endpoint."""
    return JSONResponse({
        "name": "WHOOP MCP Server v2",
        "version": "2.3.0",
        "build": "sse-transport",
        "mcp_server_name": "whoop-mcp-v2",
        "status": "running",
        "tools_count": len(mcp._tool_manager._tools),
        "endpoints": {
            "health": "/health (also refreshes token if expiring)",
            "token_status": "/token-status (check token expiry)",
            "keep_alive": "/keep-alive (use with external cron)",
            "tools": "/tools (list all MCP tools - bypasses client caching)",
            "oauth_start": "/oauth/whoop/start",
            "mcp_sse": "/sse (SSE stream - configure Poke to use this)",
            "mcp_messages": "/messages (SSE message posting)",
            "api_poke_context": "/api/poke-context (GET - for automation without MCP)",
            "api_record_checkin": "/api/record-checkin (POST - log check-in sent)",
            "api_record_activity": "/api/record-activity (POST - log user activity)"
        },
        "tip": "Set up a cron job to hit /keep-alive every 30 min to prevent token expiry"
    })


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Health check endpoint - also proactively refreshes token if needed."""
    token = await database.get_token()
    token_status = "missing"
    expires_at = None
    refresh_attempted = False

    if token:
        try:
            expires_at = token.get("expires_at")
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if expires_at else None
            now = datetime.now(exp_dt.tzinfo) if exp_dt and exp_dt.tzinfo else datetime.now()

            if exp_dt and exp_dt > now:
                # Token still valid - check if we should proactively refresh
                time_left = exp_dt - now
                if time_left.total_seconds() < 3600:  # Less than 1 hour left
                    print("[Health] Token expiring soon, proactively refreshing...")
                    refresh_attempted = True
                    await whoop_client._refresh_token(token["refresh_token"])
                    token_status = "refreshed"
                else:
                    token_status = "valid"
            else:
                # Token expired - try to refresh
                print("[Health] Token expired, attempting refresh...")
                refresh_attempted = True
                await whoop_client._refresh_token(token["refresh_token"])
                token_status = "refreshed"
        except Exception as e:
            print(f"[Health] Token refresh failed: {e}")
            token_status = f"refresh_failed: {str(e)}"

    return JSONResponse({
        "status": "healthy",
        "whoop_connected": token_status in ["valid", "refreshed"],
        "token_status": token_status,
        "expires_at": expires_at,
        "refresh_attempted": refresh_attempted,
        "timestamp": datetime.now().isoformat()
    })


@mcp.custom_route("/token-status", methods=["GET"])
async def token_status(request: Request) -> JSONResponse:
    """Check detailed token status and time until expiry."""
    token = await database.get_token()

    if not token:
        return JSONResponse({
            "exists": False,
            "message": "No token found. Authorize at /oauth/whoop/start"
        })

    expires_at = token.get("expires_at")
    try:
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if expires_at else None
        now = datetime.now(exp_dt.tzinfo) if exp_dt and exp_dt.tzinfo else datetime.now()

        if exp_dt:
            time_left = exp_dt - now
            hours_left = time_left.total_seconds() / 3600
            is_valid = time_left.total_seconds() > 0

            return JSONResponse({
                "exists": True,
                "is_valid": is_valid,
                "expires_at": expires_at,
                "hours_until_expiry": round(hours_left, 2),
                "scope": token.get("scope"),
                "message": "Token valid" if is_valid else "Token expired - will refresh on next API call"
            })
    except Exception as e:
        return JSONResponse({
            "exists": True,
            "error": str(e),
            "expires_at": expires_at
        })


@mcp.custom_route("/tools", methods=["GET"])
async def list_tools(request: Request) -> JSONResponse:
    """List all MCP tools - bypasses client caching."""
    tools = []
    for name, tool in mcp._tool_manager._tools.items():
        desc = tool.description or ""
        tools.append({
            "name": name,
            "description": desc[:100] + "..." if len(desc) > 100 else desc
        })
    return JSONResponse({
        "count": len(tools),
        "tools": tools,
        "version": "2.1.0",
        "mcp_server_name": "whoop-mcp-v2"
    })


@mcp.custom_route("/keep-alive", methods=["GET"])
async def keep_alive(request: Request) -> JSONResponse:
    """
    Keep-alive endpoint for external cron jobs.
    Proactively refreshes token if it will expire within 2 hours.

    Set up a free cron service (cron-job.org, easycron.com, etc.) to hit this
    endpoint every 30 minutes to ensure your token never expires.
    """
    token = await database.get_token()

    if not token:
        return JSONResponse({
            "status": "no_token",
            "message": "No token to keep alive. Authorize at /oauth/whoop/start"
        })

    try:
        expires_at = token.get("expires_at")
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if expires_at else None
        now = datetime.now(exp_dt.tzinfo) if exp_dt and exp_dt.tzinfo else datetime.now()

        if exp_dt:
            time_left = exp_dt - now
            hours_left = time_left.total_seconds() / 3600

            # Refresh if less than 2 hours left
            if hours_left < 2:
                print(f"[Keep-Alive] Token expires in {hours_left:.1f}h, refreshing...")
                await whoop_client._refresh_token(token["refresh_token"])
                new_token = await database.get_token()
                return JSONResponse({
                    "status": "refreshed",
                    "message": "Token was refreshed",
                    "old_expires_at": expires_at,
                    "new_expires_at": new_token.get("expires_at") if new_token else None,
                    "timestamp": datetime.now().isoformat()
                })
            else:
                return JSONResponse({
                    "status": "ok",
                    "message": f"Token still valid for {hours_left:.1f} hours",
                    "expires_at": expires_at,
                    "hours_until_expiry": round(hours_left, 2),
                    "timestamp": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"[Keep-Alive] Error: {e}")
        return JSONResponse({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }, status_code=500)


# ============== HTTP API for Automation (bypasses MCP) ==============

@mcp.custom_route("/api/poke-context", methods=["GET"])
async def api_poke_context(request: Request) -> JSONResponse:
    """
    HTTP endpoint for Poke automation to get context without MCP.
    Same data as get_poke_context() MCP tool.

    Query params:
    - next_commitment_time: ISO timestamp of next calendar event (optional)
    - calendar_context: Brief description of upcoming events (optional)
    """
    params = request.query_params
    result = await get_poke_context(
        next_commitment_time=params.get("next_commitment_time"),
        calendar_context=params.get("calendar_context")
    )
    return JSONResponse(result)


@mcp.custom_route("/api/record-checkin", methods=["POST"])
async def api_record_checkin(request: Request) -> JSONResponse:
    """
    HTTP endpoint to record check-in sent.

    Query params:
    - checkin_type: Type of check-in (default: "energy_check")
    - trigger_source: What triggered this (default: "hourly")
    - user_state: Current user state (optional)
    - recovery_score: Current recovery score (optional)
    """
    params = request.query_params
    recovery = params.get("recovery_score")
    result = await record_checkin_sent(
        checkin_type=params.get("checkin_type", "energy_check"),
        trigger_source=params.get("trigger_source", "hourly"),
        user_state=params.get("user_state"),
        recovery_score=int(recovery) if recovery else None
    )
    return JSONResponse(result)


@mcp.custom_route("/api/record-activity", methods=["POST"])
async def api_record_activity(request: Request) -> JSONResponse:
    """
    HTTP endpoint to record user activity.

    Query params:
    - response_quality: Quality of response (default: "passive")
    """
    params = request.query_params
    result = await record_user_activity(
        response_quality=params.get("response_quality", "passive")
    )
    return JSONResponse(result)


@mcp.custom_route("/oauth/whoop/start", methods=["GET"])
async def oauth_start(request: Request) -> RedirectResponse:
    """Start WHOOP OAuth flow."""
    if not WHOOP_CLIENT_ID or not WHOOP_REDIRECT_URI:
        return JSONResponse({"error": "OAuth not configured"}, status_code=500)

    state = secrets.token_urlsafe(32)
    oauth_states[state] = datetime.now()

    # Clean old states
    cutoff = datetime.now() - timedelta(minutes=10)
    for s in [k for k, v in oauth_states.items() if v < cutoff]:
        del oauth_states[s]

    params = {
        "client_id": WHOOP_CLIENT_ID,
        "redirect_uri": WHOOP_REDIRECT_URI,
        "response_type": "code",
        "scope": "offline read:recovery read:sleep read:workout read:cycles read:profile",
        "state": state
    }

    return RedirectResponse(url=f"{WHOOP_AUTH_URL}?{urlencode(params)}")


@mcp.custom_route("/oauth/whoop/callback", methods=["GET"])
async def oauth_callback(request: Request) -> JSONResponse:
    """Handle WHOOP OAuth callback."""
    params = request.query_params

    if params.get("error"):
        return JSONResponse({"error": "oauth_error", "message": params.get("error")}, status_code=400)

    state = params.get("state")
    if not state or state not in oauth_states:
        return JSONResponse({"error": "invalid_state", "message": "Invalid or expired state"}, status_code=400)

    del oauth_states[state]
    code = params.get("code")

    if not code:
        return JSONResponse({"error": "missing_code", "message": "No authorization code"}, status_code=400)

    try:
        print("[OAuth] Exchanging code for tokens...")
        async with aiohttp.ClientSession() as session:
            async with session.post(WHOOP_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": WHOOP_REDIRECT_URI,
                "client_id": WHOOP_CLIENT_ID,
                "client_secret": WHOOP_CLIENT_SECRET
            }) as response:
                text = await response.text()
                print(f"[OAuth] Response status: {response.status}")

                if response.status != 200:
                    return JSONResponse({"error": "token_exchange_failed", "message": text}, status_code=400)

                data = json.loads(text)

        expires_at = datetime.now() + timedelta(seconds=data["expires_in"])

        await database.save_token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=expires_at.isoformat(),
            scope=data.get("scope")
        )

        print("[OAuth] Token saved!")
        return JSONResponse({
            "status": "success",
            "message": "WHOOP connected successfully!",
            "expires_at": expires_at.isoformat()
        })

    except Exception as e:
        print(f"[OAuth] Error: {e}")
        return JSONResponse({"error": "callback_error", "message": str(e)}, status_code=500)


# ============== Background Token Refresh ==============

async def background_token_refresh():
    """Background task that refreshes token every 30 minutes if needed."""
    import asyncio

    while True:
        try:
            await asyncio.sleep(1800)  # 30 minutes

            token = await database.get_token()
            if not token:
                print("[Background] No token to refresh")
                continue

            expires_at = token.get("expires_at")
            exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if expires_at else None
            now = datetime.now(exp_dt.tzinfo) if exp_dt and exp_dt.tzinfo else datetime.now()

            if exp_dt:
                hours_left = (exp_dt - now).total_seconds() / 3600

                if hours_left < 2:
                    print(f"[Background] Token expires in {hours_left:.1f}h, refreshing...")
                    await whoop_client._refresh_token(token["refresh_token"])
                    print("[Background] Token refreshed successfully")
                else:
                    print(f"[Background] Token valid for {hours_left:.1f}h, no refresh needed")

        except asyncio.CancelledError:
            print("[Background] Token refresh task cancelled")
            break
        except Exception as e:
            print(f"[Background] Error refreshing token: {e}")


async def refresh_token_if_needed():
    """Check and refresh token immediately on startup."""
    token = await database.get_token()
    if not token:
        print("[Startup] No token found, skipping refresh check")
        return

    try:
        expires_at = token.get("expires_at")
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) if expires_at else None
        now = datetime.now(exp_dt.tzinfo) if exp_dt and exp_dt.tzinfo else datetime.now()

        if exp_dt:
            time_left = (exp_dt - now).total_seconds()
            hours_left = time_left / 3600

            if time_left <= 0:
                print(f"[Startup] Token expired, attempting refresh...")
                await whoop_client._refresh_token(token["refresh_token"])
                print("[Startup] Token refreshed successfully")
            elif hours_left < 2:
                print(f"[Startup] Token expires in {hours_left:.1f}h, refreshing...")
                await whoop_client._refresh_token(token["refresh_token"])
                print("[Startup] Token refreshed successfully")
            else:
                print(f"[Startup] Token valid for {hours_left:.1f}h")
    except Exception as e:
        print(f"[Startup] Could not refresh token: {e}")


# ============== Startup ==============

async def init():
    """Initialize database on startup."""
    print("[Startup] Initializing database...")
    await database.init_db()
    print("[Startup] Checking token status...")
    await refresh_token_if_needed()
    print("[Startup] Ready!")


if __name__ == "__main__":
    import asyncio
    import uvicorn
    from contextlib import asynccontextmanager
    from starlette.applications import Starlette
    from starlette.routing import Mount

    port = int(os.getenv("PORT", 8080))
    print(f"[Startup] Starting server on port {port}...")

    # Create SSE transport app for Poke compatibility
    # SSE (2024-11-05) exposes: /sse (GET) and /messages (POST)
    # When mounted at /mcp, this gives /mcp/sse which Poke expects
    sse_app = mcp.sse_app()

    # Lifespan that initializes everything in the correct event loop
    @asynccontextmanager
    async def lifespan(app):
        # Initialize database (must be in uvicorn's event loop)
        print("[Startup] Initializing database...")
        await database.init_db()

        # Check and refresh token on startup
        print("[Startup] Checking token status...")
        await refresh_token_if_needed()

        # SSE transport doesn't use session_manager (that's only for streamable HTTP)
        print("[Startup] MCP SSE transport active")
        print("[Startup] Endpoints: /sse (stream), /messages (post)")

        # Start background token refresh task
        refresh_task = asyncio.create_task(background_token_refresh())
        print("[Startup] Background token refresh task started (runs every 30 min)")
        print("[Startup] Ready!")

        yield

        # Cancel background task on shutdown
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass

        # Close whoop client session
        await whoop_client.close()
        print("[Shutdown] Server stopped")

    # Create Starlette app with lifespan
    # SSE app includes custom routes (/, /health, /tools, etc.) plus SSE endpoints (/sse, /messages)
    # Mount at / so all routes work at expected paths
    # DNS rebinding protection is disabled via TransportSecuritySettings, so no host header middleware needed
    # Poke should connect to /sse
    wrapper = Starlette(
        routes=[
            Mount("/", app=sse_app),
        ],
        lifespan=lifespan
    )

    uvicorn.run(
        wrapper,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
