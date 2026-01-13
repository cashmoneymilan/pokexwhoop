"""
WHOOP API client with automatic token refresh.
"""

import os
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import database

WHOOP_API_BASE = "https://api.prod.whoop.com/developer"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

# Refresh token 5 minutes before expiry
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)


class WhoopClient:
    def __init__(self):
        self.client_id = os.getenv("WHOOP_CLIENT_ID")
        self.client_secret = os.getenv("WHOOP_CLIENT_SECRET")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if necessary."""
        token = await database.get_token()

        if not token:
            raise Exception("No WHOOP token found. Please authorize at /oauth/whoop/start")

        expires_at = datetime.fromisoformat(token["expires_at"].replace("Z", "+00:00"))
        now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()

        # Refresh if expiring soon
        if expires_at - now < TOKEN_REFRESH_BUFFER:
            print("[WHOOP] Token expiring soon, refreshing...")
            await self._refresh_token(token["refresh_token"])
            token = await database.get_token()

        return token["access_token"]

    async def _refresh_token(self, refresh_token: str):
        """Refresh the access token."""
        session = await self._get_session()

        async with session.post(
            WHOOP_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Token refresh failed: {error_text}")

            data = await response.json()
            expires_at = datetime.now() + timedelta(seconds=data["expires_in"])

            await database.save_token(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=expires_at.isoformat(),
                scope=data.get("scope")
            )

        print("[WHOOP] Token refreshed successfully")

    async def _request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make an authenticated request to the WHOOP API."""
        access_token = await self._ensure_valid_token()
        session = await self._get_session()

        url = f"{WHOOP_API_BASE}{endpoint}"
        print(f"[WHOOP] Requesting: {url} with params: {params}")

        async with session.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params
        ) as response:
            print(f"[WHOOP] Response status: {response.status}")
            if response.status == 401:
                # Try refreshing token and retry
                token = await database.get_token()
                if token:
                    await self._refresh_token(token["refresh_token"])
                    return await self._request(endpoint, params)
                raise Exception("Unauthorized - please re-authorize")

            if response.status != 200:
                error_text = await response.text()
                print(f"[WHOOP] Error {response.status} for {url}: {error_text}")
                raise Exception(f"WHOOP API error: {response.status} - {error_text}")

            return await response.json()

    async def get_recovery(self, limit: int = 1) -> List[Dict]:
        """Get recovery data."""
        # Use date range - last 7 days
        end = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        data = await self._request("/v1/recovery", {"start": start, "end": end, "limit": limit})
        print(f"[WHOOP] Recovery response: {data}")
        return data.get("records", [])

    async def get_sleep(self, limit: int = 1) -> List[Dict]:
        """Get sleep data."""
        # Use date range - last 7 days
        end = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        data = await self._request("/v1/sleep", {"start": start, "end": end, "limit": limit})
        print(f"[WHOOP] Sleep response: {data}")
        return data.get("records", [])

    async def get_cycles(self, limit: int = 1) -> List[Dict]:
        """Get cycle/strain data."""
        data = await self._request("/v1/cycle", {"limit": limit})
        return data.get("records", [])

    async def get_workouts(self, limit: int = 7) -> List[Dict]:
        """Get workout data."""
        data = await self._request("/v1/activity/workout", {"limit": limit})
        return data.get("records", [])


# Helper functions to normalize WHOOP data

def normalize_recovery(recovery: Dict) -> Dict:
    """Normalize recovery data."""
    if not recovery:
        return None

    score = recovery.get("score", {})
    recovery_score = score.get("recovery_score")

    # Determine state based on score
    if recovery_score is None:
        state = "unknown"
    elif recovery_score >= 67:
        state = "green"
    elif recovery_score >= 34:
        state = "yellow"
    else:
        state = "red"

    return {
        "date": recovery.get("created_at", "")[:10],
        "recovery_score": recovery_score,
        "hrv": score.get("hrv_rmssd_milli"),
        "resting_hr": score.get("resting_heart_rate"),
        "spo2": score.get("spo2_percentage"),
        "state": state,
        "confidence": "calibrating" if score.get("user_calibrating") else "normal"
    }


def normalize_sleep(sleep: Dict) -> Dict:
    """Normalize sleep data."""
    if not sleep:
        return None

    score = sleep.get("score", {})
    stage_summary = score.get("stage_summary", {})
    sleep_needed = score.get("sleep_needed", {})

    # Convert milliseconds to seconds
    def ms_to_sec(ms):
        return round(ms / 1000) if ms else None

    total_sleep = ms_to_sec(stage_summary.get("total_sleep_time_milli"))

    return {
        "date": sleep.get("start", "")[:10],
        "total_sleep": total_sleep,
        "total_sleep_formatted": format_duration(total_sleep),
        "sleep_efficiency": score.get("sleep_efficiency_percentage"),
        "sleep_debt": ms_to_sec(sleep_needed.get("need_from_sleep_debt_milli")),
        "disturbances": stage_summary.get("disturbance_count"),
        "stages": {
            "rem": format_duration(ms_to_sec(stage_summary.get("total_rem_sleep_time_milli"))),
            "deep": format_duration(ms_to_sec(stage_summary.get("total_slow_wave_sleep_time_milli"))),
            "light": format_duration(ms_to_sec(stage_summary.get("total_light_sleep_time_milli"))),
            "awake": format_duration(ms_to_sec(stage_summary.get("total_awake_time_milli")))
        }
    }


def normalize_cycle(cycle: Dict) -> Dict:
    """Normalize cycle/strain data."""
    if not cycle:
        return None

    score = cycle.get("score", {})

    return {
        "date": cycle.get("start", "")[:10],
        "strain": score.get("strain"),
        "kilojoules": score.get("kilojoule"),
        "average_hr": score.get("average_heart_rate"),
        "max_hr": score.get("max_heart_rate")
    }


def format_duration(seconds: int) -> Optional[str]:
    """Format duration in seconds to human readable string."""
    if seconds is None:
        return None

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def get_recommended_strain(recovery_score: int) -> Dict:
    """Get recommended strain range based on recovery score."""
    if recovery_score is None:
        return None

    if recovery_score >= 67:
        return {"min": 14, "max": 21, "description": "Peak day - push hard"}
    elif recovery_score >= 34:
        return {"min": 10, "max": 14, "description": "Moderate day - maintain"}
    else:
        return {"min": 0, "max": 10, "description": "Recovery day - take it easy"}


# Singleton instance
whoop_client = WhoopClient()
