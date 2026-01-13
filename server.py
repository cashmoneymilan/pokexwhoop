"""
WHOOP MCP Server using FastMCP + FastAPI
Exposes WHOOP health data as MCP tools for Poke AI
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from contextlib import asynccontextmanager

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
import uvicorn

from mcp.server.fastmcp import FastMCP

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
SERVER_API_KEY = os.getenv("SERVER_API_KEY")

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"


# Initialize FastMCP server
mcp = FastMCP("whoop-mcp-server")


# ============== MCP Tools ==============

@mcp.tool()
async def get_today_summary() -> dict:
    """
    Get a comprehensive summary of today's WHOOP data including recovery score,
    strain, sleep duration and quality, HRV, resting heart rate, and recommended
    strain range.
    """
    try:
        # Fetch all data
        recovery_data = await whoop_client.get_recovery(limit=1)
        sleep_data = await whoop_client.get_sleep(limit=1)
        cycle_data = await whoop_client.get_cycles(limit=1)

        # Normalize data
        recovery = normalize_recovery(recovery_data[0]) if recovery_data else None
        sleep = normalize_sleep(sleep_data[0]) if sleep_data else None
        cycle = normalize_cycle(cycle_data[0]) if cycle_data else None

        # Build summary
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

        recovery = normalize_recovery(recovery_data[0])
        return recovery

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

        sleep = normalize_sleep(sleep_data[0])
        return sleep

    except Exception as e:
        return {"error": str(e), "message": "Failed to fetch sleep data"}


@mcp.tool()
async def get_week_trends(metric: str) -> dict:
    """
    Get 7-day trends for a specific health metric.

    Args:
        metric: The metric to analyze - "recovery" (recovery score),
                "strain" (daily strain), or "sleep" (total sleep hours)

    Returns:
        Weekly average, trend direction, percentage change, daily data points,
        and any notable outliers.
    """
    try:
        if metric not in ["recovery", "strain", "sleep"]:
            return {
                "error": "invalid_metric",
                "message": "Metric must be one of: recovery, strain, sleep"
            }

        # Fetch 7 days of data
        if metric == "recovery":
            data = await whoop_client.get_recovery(limit=7)
            values = []
            for item in data:
                normalized = normalize_recovery(item)
                if normalized and normalized.get("recovery_score") is not None:
                    values.append({
                        "date": normalized["date"],
                        "value": normalized["recovery_score"]
                    })

        elif metric == "strain":
            data = await whoop_client.get_cycles(limit=7)
            values = []
            for item in data:
                normalized = normalize_cycle(item)
                if normalized and normalized.get("strain") is not None:
                    values.append({
                        "date": normalized["date"],
                        "value": round(normalized["strain"], 1)
                    })

        else:  # sleep
            data = await whoop_client.get_sleep(limit=7)
            values = []
            for item in data:
                normalized = normalize_sleep(item)
                if normalized and normalized.get("total_sleep") is not None:
                    hours = round(normalized["total_sleep"] / 3600, 1)
                    values.append({
                        "date": normalized["date"],
                        "value": hours
                    })

        if not values:
            return {"error": "no_data", "message": f"No {metric} data available for the past week"}

        # Calculate statistics
        numeric_values = [v["value"] for v in values]
        avg = round(sum(numeric_values) / len(numeric_values), 1)

        # Trend calculation (compare first half to second half)
        if len(numeric_values) >= 4:
            first_half = numeric_values[:len(numeric_values)//2]
            second_half = numeric_values[len(numeric_values)//2:]
            first_avg = sum(first_half) / len(first_half)
            second_avg = sum(second_half) / len(second_half)

            if second_avg > first_avg * 1.05:
                trend = "improving"
            elif second_avg < first_avg * 0.95:
                trend = "declining"
            else:
                trend = "stable"

            change = round(((second_avg - first_avg) / first_avg) * 100, 1) if first_avg else 0
        else:
            trend = "insufficient_data"
            change = 0

        # Find outliers (values more than 1.5 std dev from mean)
        if len(numeric_values) >= 3:
            mean = sum(numeric_values) / len(numeric_values)
            variance = sum((x - mean) ** 2 for x in numeric_values) / len(numeric_values)
            std_dev = variance ** 0.5
            threshold = 1.5 * std_dev

            outliers = [v for v in values if abs(v["value"] - mean) > threshold]
        else:
            outliers = []

        return {
            "metric": metric,
            "period": "7 days",
            "average": avg,
            "trend": trend,
            "change_percent": change,
            "data_points": values,
            "outliers": outliers,
            "unit": "%" if metric == "recovery" else ("strain" if metric == "strain" else "hours")
        }

    except Exception as e:
        return {"error": str(e), "message": f"Failed to fetch {metric} trends"}


# ============== FastAPI App ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup, cleanup on shutdown."""
    print("[Startup] Initializing database...")
    await database.init_db()
    print("[Startup] Server ready")
    yield
    print("[Shutdown] Closing WHOOP client...")
    await whoop_client.close()


# Create FastAPI app with lifespan
api = FastAPI(title="WHOOP MCP Server", lifespan=lifespan)


@api.get("/")
async def root():
    """Server info endpoint."""
    return {
        "name": "WHOOP MCP Server",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "oauth_start": "/oauth/whoop/start",
            "mcp": "/mcp"
        }
    }


@api.get("/health")
async def health():
    """Health check endpoint."""
    token_exists = await database.token_exists()
    last_sync = await database.get_last_sync_time()

    return {
        "status": "healthy",
        "whoop_connected": token_exists,
        "last_sync": last_sync,
        "timestamp": datetime.now().isoformat()
    }


@api.get("/oauth/whoop/start")
async def oauth_start():
    """Start WHOOP OAuth flow."""
    if not WHOOP_CLIENT_ID or not WHOOP_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="OAuth not configured")

    scopes = "read:recovery read:sleep read:workout read:cycles read:profile"

    auth_url = (
        f"{WHOOP_AUTH_URL}"
        f"?client_id={WHOOP_CLIENT_ID}"
        f"&redirect_uri={WHOOP_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scopes}"
    )

    return RedirectResponse(url=auth_url)


@api.get("/oauth/whoop/callback")
async def oauth_callback(code: str = None, error: str = None):
    """Handle WHOOP OAuth callback."""
    if error:
        return JSONResponse(
            status_code=400,
            content={"error": "oauth_error", "message": error}
        )

    if not code:
        return JSONResponse(
            status_code=400,
            content={"error": "missing_code", "message": "No authorization code provided"}
        )

    # Exchange code for tokens
    async with aiohttp.ClientSession() as session:
        async with session.post(
            WHOOP_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": WHOOP_REDIRECT_URI,
                "client_id": WHOOP_CLIENT_ID,
                "client_secret": WHOOP_CLIENT_SECRET
            }
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                return JSONResponse(
                    status_code=400,
                    content={"error": "token_exchange_failed", "message": error_text}
                )

            data = await response.json()

    # Calculate expiry
    expires_at = datetime.now() + timedelta(seconds=data["expires_in"])

    # Save token
    await database.save_token(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=expires_at.isoformat(),
        scope=data.get("scope")
    )

    return {
        "status": "success",
        "message": "WHOOP connected successfully!",
        "expires_at": expires_at.isoformat()
    }


# Mount MCP server at /mcp
app = mcp.streamable_http_app()

# Combine FastAPI and MCP
from starlette.routing import Mount

api.mount("/mcp", app)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(api, host="0.0.0.0", port=port)
