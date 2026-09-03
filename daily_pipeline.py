"""Pure daily WHOOP record selection, validation, and provenance helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from whoop_client import parse_whoop_datetime, record_local_date, score_state, sleep_sort_key


PIPELINE_VERSION = "3.0.0"
RETRY_AFTER_SECONDS = int(os.getenv("WHOOP_PENDING_RETRY_SECONDS", "900") or "900")
DEFAULT_OVERRIDES_PATH = Path(__file__).with_name("whoop_overrides.json")


def load_overrides(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Load reviewable, version-controlled manual record overrides."""
    override_path = Path(path or os.getenv("WHOOP_OVERRIDES_PATH") or DEFAULT_OVERRIDES_PATH)
    if not override_path.exists():
        return {}
    with override_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("WHOOP overrides must be a JSON object keyed by YYYY-MM-DD.")
    return data


def _set_path(target: Dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cursor = target
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


def apply_override(
    record_type: str,
    record: Optional[Dict[str, Any]],
    override: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Apply explicit dotted-path corrections to a copied upstream record."""
    if record is None:
        return None
    corrected = copy.deepcopy(record)
    corrections = (override or {}).get("corrections") or {}
    typed = corrections.get(record_type) or {}
    if not isinstance(typed, dict):
        raise ValueError(f"Corrections for {record_type} must be an object.")
    for dotted_path, value in typed.items():
        _set_path(corrected, str(dotted_path), value)
    return corrected


def select_day_records(
    requested_date: str,
    recoveries: Iterable[Dict[str, Any]],
    sleeps: Iterable[Dict[str, Any]],
    cycles: Iterable[Dict[str, Any]],
    workouts: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Select the latest WHOOP records assigned to one local calendar date."""
    day_sleeps = [
        item for item in sleeps
        if record_local_date(item, timestamp_field="end") == requested_date
    ]
    main_sleeps = [item for item in day_sleeps if not item.get("nap")]
    naps = [item for item in day_sleeps if item.get("nap")]
    selected_sleep = max(main_sleeps, key=sleep_sort_key) if main_sleeps else None
    matching_recoveries = [
        item for item in recoveries
        if selected_sleep and str(item.get("sleep_id") or "") == str(selected_sleep.get("id") or "")
    ]
    selected_recovery = max(
        matching_recoveries,
        key=lambda item: parse_whoop_datetime(item.get("updated_at"))
        or parse_whoop_datetime(item.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
    ) if matching_recoveries else None
    day_cycles = [item for item in cycles if record_local_date(item) == requested_date]
    selected_cycle = max(
        day_cycles,
        key=lambda item: parse_whoop_datetime(item.get("updated_at"))
        or parse_whoop_datetime(item.get("start"))
        or datetime.min.replace(tzinfo=timezone.utc),
    ) if day_cycles else None
    day_workouts = [item for item in workouts if record_local_date(item) == requested_date]
    return {
        "sleep": selected_sleep,
        "recovery": selected_recovery,
        "cycle": selected_cycle,
        "naps": sorted(naps, key=sleep_sort_key),
        "workouts": sorted(day_workouts, key=lambda item: item.get("start") or ""),
    }


def plausible_record_issues(
    sleep: Optional[Dict[str, Any]],
    recovery: Optional[Dict[str, Any]],
    cycle: Optional[Dict[str, Any]] = None,
) -> list[str]:
    """Reject only physically or structurally impossible values, not lifestyle choices."""
    issues: list[str] = []
    if sleep:
        start = parse_whoop_datetime(sleep.get("start"))
        end = parse_whoop_datetime(sleep.get("end"))
        if not start or not end:
            issues.append("sleep_start_or_end_missing")
        elif end <= start:
            issues.append("sleep_end_not_after_start")
        else:
            duration_hours = (end - start).total_seconds() / 3600
            if duration_hours > 24:
                issues.append("time_in_bed_exceeds_24_hours")
        score = sleep.get("score") or {}
        efficiency = score.get("sleep_efficiency_percentage")
        if efficiency is not None and not 0 <= float(efficiency) <= 100:
            issues.append("sleep_efficiency_out_of_range")
        stages = score.get("stage_summary") or {}
        stage_values = [
            stages.get("total_light_sleep_time_milli"),
            stages.get("total_slow_wave_sleep_time_milli"),
            stages.get("total_rem_sleep_time_milli"),
            stages.get("total_awake_time_milli"),
        ]
        if any(value is not None and float(value) < 0 for value in stage_values):
            issues.append("negative_sleep_stage_duration")
    if recovery:
        score = recovery.get("score") or {}
        recovery_score = score.get("recovery_score")
        if recovery_score is not None and not 0 <= float(recovery_score) <= 100:
            issues.append("recovery_score_out_of_range")
        spo2 = score.get("spo2_percentage")
        if spo2 is not None and not 0 <= float(spo2) <= 100:
            issues.append("spo2_out_of_range")
    if cycle and score_state(cycle) == "SCORED":
        score = cycle.get("score") or {}
        strain = score.get("strain")
        kilojoules = score.get("kilojoule")
        if strain is not None and not 0 <= float(strain) <= 21:
            issues.append("cycle_strain_out_of_range")
        if kilojoules is not None and float(kilojoules) < 0:
            issues.append("negative_cycle_energy")
    return issues


def evaluate_day_status(
    requested_date: str,
    records: Dict[str, Any],
    override: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    finalization_delay_minutes: int = 30,
) -> Dict[str, Any]:
    """Classify a day without letting SCORED alone imply trustworthy/final."""
    if override and override.get("invalidated"):
        return {
            "data_status": "manually_invalidated",
            "valid_for_model": False,
            "reason": override.get("reason") or "Manually invalidated.",
            "plausibility_issues": [],
        }

    sleep = records.get("sleep")
    recovery = records.get("recovery")
    if not sleep:
        return {"data_status": "missing", "valid_for_model": False, "reason": "No main sleep record for local date.", "plausibility_issues": []}
    if score_state(sleep) != "SCORED":
        return {"data_status": "pending", "valid_for_model": False, "reason": f"Sleep score_state is {score_state(sleep) or 'missing'}.", "plausibility_issues": []}
    if not recovery:
        return {"data_status": "incomplete", "valid_for_model": False, "reason": "No recovery matches the selected sleep_id.", "plausibility_issues": []}
    if score_state(recovery) != "SCORED":
        return {"data_status": "pending", "valid_for_model": False, "reason": f"Recovery score_state is {score_state(recovery) or 'missing'}.", "plausibility_issues": []}

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    sleep_end = parse_whoop_datetime(sleep.get("end"))
    if sleep_end and (current_time - sleep_end).total_seconds() < finalization_delay_minutes * 60:
        return {
            "data_status": "pending",
            "valid_for_model": False,
            "reason": f"Sleep is inside the {finalization_delay_minutes}-minute finalization delay.",
            "plausibility_issues": [],
        }

    issues = plausible_record_issues(sleep, recovery, records.get("cycle"))
    if issues:
        return {"data_status": "implausible", "valid_for_model": False, "reason": "Plausibility guard failed.", "plausibility_issues": issues}
    return {"data_status": "finalized", "valid_for_model": True, "reason": "Matched SCORED records passed finalization and plausibility checks.", "plausibility_issues": []}


def day_completion(requested_date: str, cycle: Optional[Dict[str, Any]], *, now: Optional[datetime] = None) -> str:
    """Distinguish an accumulating current cycle from a completed calendar day."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    offset = str((cycle or {}).get("timezone_offset") or "+00:00")
    try:
        sign = -1 if offset.startswith("-") else 1
        hours, minutes = (int(part) for part in offset.lstrip("+-").split(":", 1))
        local_now = current_time.astimezone(timezone(sign * timedelta(hours=hours, minutes=minutes)))
    except (TypeError, ValueError):
        local_now = current_time
    requested = date_type.fromisoformat(requested_date)
    return "completed_day" if requested < local_now.date() else "partial_day"


def retry_metadata(data_status: str, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    if data_status not in {"pending", "incomplete", "missing"}:
        return None
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    retry_at = current_time + timedelta(seconds=RETRY_AFTER_SECONDS)
    return {"scheduled": True, "retry_after_seconds": RETRY_AFTER_SECONDS, "retry_at": retry_at.isoformat()}


def snapshot_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def source_provenance(records: Dict[str, Any], *, retrieved_at: Optional[datetime] = None) -> Dict[str, Any]:
    observed = retrieved_at or datetime.now(timezone.utc)
    return {
        "pipeline_version": PIPELINE_VERSION,
        "source": "WHOOP Developer API v2",
        "retrieved_at": observed.isoformat(),
        "record_ids": {
            "sleep": (records.get("sleep") or {}).get("id"),
            "recovery": (records.get("recovery") or {}).get("id"),
            "cycle": (records.get("cycle") or {}).get("id"),
            "naps": [item.get("id") for item in records.get("naps") or []],
            "workouts": [item.get("id") for item in records.get("workouts") or []],
        },
        "source_updated_at": {
            key: (records.get(key) or {}).get("updated_at")
            for key in ("sleep", "recovery", "cycle")
        },
        "source_record_hashes": {
            key: snapshot_hash(records[key]) if records.get(key) else None
            for key in ("sleep", "recovery", "cycle")
        },
    }


def numeric_comparison(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Return model-friendly deltas from the previous finalized valid day."""
    fields = {
        "recovery_score": ((current.get("recovery") or {}).get("recovery_score"), (previous.get("recovery") or {}).get("recovery_score")),
        "sleep_seconds": ((current.get("sleep") or {}).get("total_sleep"), (previous.get("sleep") or {}).get("total_sleep")),
        "hrv_ms": ((current.get("recovery") or {}).get("hrv"), (previous.get("recovery") or {}).get("hrv")),
        "resting_hr": ((current.get("recovery") or {}).get("resting_hr"), (previous.get("recovery") or {}).get("resting_hr")),
        "day_strain": ((current.get("cycle") or {}).get("strain"), (previous.get("cycle") or {}).get("strain")),
        "calories_kcal": ((current.get("cycle") or {}).get("calories_kcal"), (previous.get("cycle") or {}).get("calories_kcal")),
    }
    comparison: Dict[str, Any] = {"previous_date": previous.get("date"), "deltas": {}}
    for name, (current_value, previous_value) in fields.items():
        comparison["deltas"][name] = (
            round(float(current_value) - float(previous_value), 2)
            if current_value is not None and previous_value is not None else None
        )
    return comparison
