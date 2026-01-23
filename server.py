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
mcp = FastMCP(
    "whoop-mcp-server",
    instructions="Use these tools to get WHOOP health data including recovery scores, sleep metrics, strain, and weekly trends.",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
)


# ============== State Classification Helpers ==============

def classify_state(
    buffer_hours: Optional[float],
    recovery_score: Optional[float],
    sleep_efficiency: Optional[float]
) -> str:
    """
    Core state classification logic.

    Primary signal: buffer_hours (commitment proximity)
    Modifier: recovery_score and sleep_efficiency
    """

    # If we don't have commitment data, use recovery-only classification
    if buffer_hours is None:
        if recovery_score is None:
            return "unknown"
        elif recovery_score < 60:
            return "drift_risk"  # No structure + low recovery = assume drift risk
        elif recovery_score >= 80 and (sleep_efficiency is None or sleep_efficiency >= 85):
            return "primed"
        else:
            return "anchored"  # Default to middle state without commitment context

    # Primary classification based on buffer hours
    if buffer_hours <= 1.5:
        base_state = "urgent"
    elif buffer_hours <= 3:
        base_state = "anchored"
    else:
        base_state = "drift_risk"

    # Apply modifiers
    if base_state == "drift_risk" and recovery_score is not None and recovery_score < 60:
        return "high_drift_risk"

    if base_state == "anchored":
        if (recovery_score is not None and recovery_score >= 80 and
            sleep_efficiency is not None and sleep_efficiency >= 85):
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

    Args:
        next_commitment_time: ISO format datetime string of next hard commitment (e.g., "2026-01-23T10:00:00")
        estimated_wake_time: ISO format datetime string of when user woke/will wake (e.g., "2026-01-23T08:30:00")

    Returns:
        State classification with reasoning and metrics.

    States:
        - urgent: commitment within 90 min of waking, need immediate action
        - anchored: commitment 1.5-3 hours away, natural structure exists
        - drift_risk: commitment 3+ hours away or none, structure may dissolve
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

        # State classification logic
        state = classify_state(buffer_hours, recovery_score, sleep_efficiency)
        reasoning = generate_reasoning(state, buffer_hours, recovery_score, sleep_efficiency)

        return {
            "state": state,
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
    Useful for understanding and debugging the model.
    """
    return {
        "states": {
            "urgent": {
                "description": "Commitment within 90 min of waking",
                "buffer_hours": "<= 1.5",
                "poke_behavior": "Immediate time math, no fluff, get out the door"
            },
            "anchored": {
                "description": "Commitment 1.5-3 hours away, natural structure exists",
                "buffer_hours": "1.5 - 3.0",
                "poke_behavior": "Standard briefing, check-ins every 3-4 hours"
            },
            "drift_risk": {
                "description": "Commitment 3+ hours away or none, structure may dissolve",
                "buffer_hours": "> 3.0 or none",
                "poke_behavior": "Offer structure, check-ins every 2 hours, meal prompts"
            },
            "high_drift_risk": {
                "description": "Drift risk + low recovery, both structure and physiology compromised",
                "condition": "drift_risk AND recovery < 60%",
                "poke_behavior": "More assertive structure, shorter task blocks, frequent meal prompts"
            },
            "primed": {
                "description": "Anchored + high recovery + good sleep, peak state",
                "condition": "anchored AND recovery >= 80% AND sleep_efficiency >= 85%",
                "poke_behavior": "Push hard problems, minimize interruptions, trust self-regulation"
            }
        },
        "thresholds": {
            "buffer_urgent": 1.5,
            "buffer_anchored": 3.0,
            "recovery_low": 60,
            "recovery_high": 80,
            "sleep_efficiency_good": 85
        }
    }


# ============== Custom HTTP Routes ==============

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    """Server info endpoint."""
    return JSONResponse({
        "name": "WHOOP MCP Server",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health (also refreshes token if expiring)",
            "token_status": "/token-status (check token expiry)",
            "keep_alive": "/keep-alive (use with external cron)",
            "oauth_start": "/oauth/whoop/start",
            "mcp": "/mcp"
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
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.applications import Starlette
    from starlette.routing import Mount

    port = int(os.getenv("PORT", 8080))
    print(f"[Startup] Starting server on port {port}...")

    # Get the ASGI app
    mcp_app = mcp.streamable_http_app()

    # Wrap with middleware to fix host header for Railway
    class HostFixMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Override scope to use localhost for internal validation
            request.scope["headers"] = [
                (b"host", b"localhost") if k == b"host" else (k, v)
                for k, v in request.scope["headers"]
            ]
            return await call_next(request)

    # Lifespan that initializes everything in the correct event loop
    @asynccontextmanager
    async def lifespan(app):
        # Initialize database (must be in uvicorn's event loop)
        print("[Startup] Initializing database...")
        await database.init_db()

        # Check and refresh token on startup
        print("[Startup] Checking token status...")
        await refresh_token_if_needed()

        async with mcp.session_manager.run():
            print("[Startup] MCP session manager started")

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
            print("[Shutdown] MCP session manager stopped")

    # Create wrapper app with middleware and lifespan
    wrapper = Starlette(
        routes=[Mount("/", app=mcp_app)],
        middleware=[Middleware(HostFixMiddleware)],
        lifespan=lifespan
    )

    uvicorn.run(
        wrapper,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
