"""
WHOOP API client with automatic token refresh.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

WHOOP_API_BASE = "https://api.prod.whoop.com/developer"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

# Refresh token 5 minutes before expiry
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)
FINALIZATION_DELAY_MINUTES = int(os.getenv("WHOOP_FINALIZATION_DELAY_MINUTES", "30") or "30")
MAX_CURRENT_SLEEP_AGE_HOURS = int(os.getenv("WHOOP_MAX_CURRENT_SLEEP_AGE_HOURS", "36") or "36")


def _aiohttp():
    try:
        import aiohttp
    except ImportError as error:
        raise RuntimeError("aiohttp is required for live WHOOP API calls.") from error
    return aiohttp


def _database():
    import database
    return database


class WhoopClient:
    def __init__(self):
        self.client_id = os.getenv("WHOOP_CLIENT_ID")
        self.client_secret = os.getenv("WHOOP_CLIENT_SECRET")
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            aiohttp = _aiohttp()
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if necessary."""
        database = _database()
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
        database = _database()
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
                database = _database()
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

    async def get_recovery(self, limit: int = 1, days: int = 7) -> List[Dict]:
        """Get recovery data."""
        # V2 API uses start/end date range
        end = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        data = await self._request("/v2/recovery", {"start": start, "end": end, "limit": limit})
        print(f"[WHOOP] Recovery response: {data}")
        return data.get("records", [])

    async def get_sleep(self, limit: int = 1, days: int = 7) -> List[Dict]:
        """Get sleep data."""
        # V2 API uses /v2/activity/sleep with date range
        end = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        data = await self._request("/v2/activity/sleep", {"start": start, "end": end, "limit": limit})
        print(f"[WHOOP] Sleep response: {data}")
        return data.get("records", [])

    async def get_cycles(self, limit: int = 1, days: int = 7) -> List[Dict]:
        """Get cycle/strain data."""
        end = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        data = await self._request("/v2/cycle", {"start": start, "end": end, "limit": limit})
        return data.get("records", [])

    async def get_workouts(self, limit: int = 7) -> List[Dict]:
        """Get workout data."""
        data = await self._request("/v2/activity/workout", {"limit": limit})
        return data.get("records", [])


# Helper functions to normalize WHOOP data

def parse_whoop_datetime(value: str | None) -> Optional[datetime]:
    """Parse a WHOOP ISO timestamp into an aware datetime when possible."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def record_local_date(record: Dict, *, timestamp_field: str = "start") -> str:
    """Return a WHOOP record's calendar date in its recorded UTC offset."""
    parsed = parse_whoop_datetime(record.get(timestamp_field))
    if not parsed:
        return ""
    raw_offset = str(record.get("timezone_offset") or "").strip()
    try:
        sign = -1 if raw_offset.startswith("-") else 1
        hours, minutes = (int(part) for part in raw_offset.lstrip("+-").split(":", 1))
        local_zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return parsed.astimezone(local_zone).date().isoformat()
    except (TypeError, ValueError):
        return parsed.date().isoformat()


def score_state(record: Dict) -> str:
    return str(record.get("score_state") or "").upper()


def is_scored(record: Dict) -> bool:
    return score_state(record) == "SCORED"


def sleep_end_time(sleep: Dict) -> Optional[datetime]:
    return parse_whoop_datetime(sleep.get("end"))


def sleep_sort_key(sleep: Dict) -> datetime:
    return sleep_end_time(sleep) or parse_whoop_datetime(sleep.get("start")) or datetime.min.replace(tzinfo=timezone.utc)


def recovery_sort_key(recovery: Dict) -> datetime:
    return (
        parse_whoop_datetime(recovery.get("created_at"))
        or parse_whoop_datetime(recovery.get("updated_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def is_nap(sleep: Dict) -> bool:
    return bool(sleep.get("nap"))


def _sleep_status(sleep: Dict | None, now: datetime, finalization_delay_minutes: int) -> tuple[str, str]:
    if not sleep:
        return "missing", "No sleep record returned by WHOOP."
    if not is_scored(sleep):
        return "pending_score", f"Latest sleep score_state is {score_state(sleep) or 'missing'}, not SCORED."
    end_time = sleep_end_time(sleep)
    if end_time:
        age_minutes = (now - end_time).total_seconds() / 60
        if age_minutes < finalization_delay_minutes:
            return "too_fresh", f"Sleep ended {age_minutes:.0f} minutes ago; waiting {finalization_delay_minutes} minutes."
    return "finalized_current", "Latest sleep is SCORED and outside the freshness delay."


def _matching_recovery_status(recovery: Dict | None) -> tuple[str, str]:
    if not recovery:
        return "missing", "No matching recovery record returned for selected sleep."
    if not is_scored(recovery):
        return "pending_score", f"Matching recovery score_state is {score_state(recovery) or 'missing'}, not SCORED."
    return "finalized_current", "Matching recovery is SCORED."


def select_stable_whoop_records(
    recovery_records: List[Dict],
    sleep_records: List[Dict],
    *,
    now: datetime | None = None,
    finalization_delay_minutes: int = FINALIZATION_DELAY_MINUTES,
    max_current_sleep_age_hours: int = MAX_CURRENT_SLEEP_AGE_HOURS,
) -> Dict:
    """Select only finalized WHOOP sleep/recovery records for policy classification.

    WHOOP can expose latest sleep/recovery records while scores are still pending.
    Proactive behavior policy must not classify from those partial records.
    """
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    ordered_sleeps = sorted(sleep_records or [], key=sleep_sort_key, reverse=True)
    non_nap_sleeps = [item for item in ordered_sleeps if not is_nap(item)]
    considered_sleeps = non_nap_sleeps or ordered_sleeps
    latest_sleep = considered_sleeps[0] if considered_sleeps else None
    sleep_status, sleep_reason = _sleep_status(latest_sleep, current_time, finalization_delay_minutes)
    latest_sleep_end = sleep_end_time(latest_sleep) if latest_sleep else None
    if sleep_status == "finalized_current" and latest_sleep_end:
        age_hours = (current_time - latest_sleep_end).total_seconds() / 3600
        if age_hours > max_current_sleep_age_hours:
            sleep_status = "stale_finalized"
            sleep_reason = (
                f"Latest finalized sleep ended {age_hours:.1f} hours ago; "
                f"current-data limit is {max_current_sleep_age_hours} hours."
            )

    metadata = {
        "sleep_score_state": score_state(latest_sleep) if latest_sleep else None,
        "sleep_id": latest_sleep.get("id") if latest_sleep else None,
        "sleep_end": latest_sleep.get("end") if latest_sleep else None,
        "sleep_is_nap": is_nap(latest_sleep) if latest_sleep else None,
        "finalization_delay_minutes": finalization_delay_minutes,
        "max_current_sleep_age_hours": max_current_sleep_age_hours,
        "whoop_data_freshness": sleep_status,
        "classification_source": None,
        "freshness_reason": sleep_reason,
        "recovery_score_state": None,
        "recovery_sleep_id": None,
    }

    if sleep_status != "finalized_current":
        return {"sleep": latest_sleep, "recovery": None, "metadata": metadata}

    selected_sleep_id = latest_sleep.get("id") if latest_sleep else None
    recoveries = sorted(recovery_records or [], key=recovery_sort_key, reverse=True)
    matching = [
        item for item in recoveries
        if selected_sleep_id and str(item.get("sleep_id") or "") == str(selected_sleep_id)
    ]
    selected_recovery = matching[0] if matching else (recoveries[0] if recoveries else None)
    recovery_status, recovery_reason = _matching_recovery_status(selected_recovery)
    metadata.update(
        {
            "recovery_score_state": score_state(selected_recovery) if selected_recovery else None,
            "recovery_sleep_id": selected_recovery.get("sleep_id") if selected_recovery else None,
            "whoop_data_freshness": recovery_status,
            "freshness_reason": recovery_reason,
        }
    )

    if recovery_status != "finalized_current":
        return {"sleep": latest_sleep, "recovery": selected_recovery, "metadata": metadata}

    if selected_sleep_id and selected_recovery and str(selected_recovery.get("sleep_id") or "") != str(selected_sleep_id):
        metadata.update(
            {
                "whoop_data_freshness": "missing",
                "freshness_reason": "No recovery matched the selected finalized sleep_id.",
                "classification_source": None,
            }
        )
        return {"sleep": latest_sleep, "recovery": selected_recovery, "metadata": metadata}

    metadata.update(
        {
            "whoop_data_freshness": "finalized_current",
            "classification_source": "current_finalized",
            "freshness_reason": "Selected sleep and recovery are SCORED and matched.",
        }
    )
    return {"sleep": latest_sleep, "recovery": selected_recovery, "metadata": metadata}

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
        "confidence": "calibrating" if score.get("user_calibrating") else "normal",
        "score_state": score_state(recovery),
        "sleep_id": recovery.get("sleep_id"),
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

    # V2 API: calculate total sleep from stages (light + deep + REM)
    light_ms = stage_summary.get("total_light_sleep_time_milli") or 0
    deep_ms = stage_summary.get("total_slow_wave_sleep_time_milli") or 0
    rem_ms = stage_summary.get("total_rem_sleep_time_milli") or 0
    total_sleep_ms = light_ms + deep_ms + rem_ms
    total_sleep = ms_to_sec(total_sleep_ms) if total_sleep_ms > 0 else None

    return {
        "date": sleep.get("start", "")[:10],
        "id": sleep.get("id"),
        "score_state": score_state(sleep),
        "start": sleep.get("start"),
        "end": sleep.get("end"),
        "nap": bool(sleep.get("nap")),
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

    kilojoules = score.get("kilojoule")
    return {
        "date": record_local_date(cycle),
        "strain": score.get("strain"),
        "kilojoules": kilojoules,
        "calories_kcal": round(kilojoules / 4.184, 1) if kilojoules is not None else None,
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
