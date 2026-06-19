"""Deterministic behavior policy contract for PokeXWhoop."""

from __future__ import annotations

from datetime import datetime
from typing import Any


ALLOWED_MESSAGE_TYPES = {
    "silent",
    "critical_alert",
    "commitment_reminder",
    "structure_prompt",
    "deep_work_prompt",
    "recovery_prompt",
    "task_check",
    "daily_brief",
}

STATE_DEFAULTS: dict[str, dict[str, Any]] = {
    "urgent": {
        "allow_message": False,
        "message_type": "silent",
        "tone": "minimal",
        "max_items": 0,
        "allowed_urgency": "critical_only",
        "blocked_behaviors": ["routine_checkin", "large_task_dump", "generic_motivation", "admin_nudge"],
    },
    "anchored": {
        "allow_message": True,
        "message_type": "task_check",
        "tone": "direct_light",
        "max_items": 1,
        "allowed_urgency": "high_or_scheduled",
        "blocked_behaviors": ["large_task_dump", "generic_motivation"],
    },
    "drift_risk": {
        "allow_message": True,
        "message_type": "structure_prompt",
        "tone": "direct_gentle",
        "max_items": 1,
        "allowed_urgency": "decision_or_structure",
        "blocked_behaviors": ["large_task_dump", "generic_motivation", "ambitious_push"],
    },
    "high_drift_risk": {
        "allow_message": True,
        "message_type": "recovery_prompt",
        "tone": "gentle_low_pressure",
        "max_items": 1,
        "allowed_urgency": "blocker_or_recovery",
        "blocked_behaviors": ["large_task_dump", "generic_motivation", "ambitious_push", "deep_work_push"],
    },
    "primed": {
        "allow_message": True,
        "message_type": "deep_work_prompt",
        "tone": "direct_protective",
        "max_items": 1,
        "allowed_urgency": "high_leverage",
        "blocked_behaviors": ["routine_admin_nudge", "generic_motivation", "large_task_dump"],
    },
    "unknown": {
        "allow_message": False,
        "message_type": "silent",
        "tone": "conservative",
        "max_items": 0,
        "allowed_urgency": "digest_only",
        "blocked_behaviors": ["proactive_checkin", "large_task_dump", "generic_motivation"],
    },
}

CRITICAL_TRIGGER_WORDS = {
    "critical",
    "deadline",
    "blocker",
    "approval",
    "identity",
    "urgent",
    "payment_failed",
}

DEFAULT_CHOICES = ["Forge follow-ups", "Gmail cleanup", "Food/health setup"]


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(context: dict[str, Any]) -> str:
    value = str(context.get("timestamp") or "")
    if value:
        return value
    return datetime.now().replace(microsecond=0).isoformat()


def _state(context: dict[str, Any]) -> str:
    whoop_data = context.get("whoop_data") or {}
    state_context = context.get("state_context") or {}
    state = str(whoop_data.get("state") or state_context.get("current") or "unknown")
    return state if state in STATE_DEFAULTS else "unknown"


def _critical_trigger(trigger_source: str, life_os_context: dict[str, Any]) -> bool:
    trigger = trigger_source.lower()
    if any(word in trigger for word in CRITICAL_TRIGGER_WORDS):
        return True
    return bool(
        life_os_context.get("critical_deadlines")
        or life_os_context.get("overdue_p1_tasks")
        or life_os_context.get("pending_critical_approvals")
    )


def _policy_for_state(
    state: str,
    *,
    trigger_source: str,
    calendar_buffer_hours: float | None,
    unanswered_checkins: int,
    life_os_context: dict[str, Any],
) -> dict[str, Any]:
    policy = dict(STATE_DEFAULTS.get(state, STATE_DEFAULTS["unknown"]))
    trigger = trigger_source.lower()

    if state == "urgent" and _critical_trigger(trigger_source, life_os_context):
        policy.update(
            {
                "allow_message": True,
                "message_type": "critical_alert",
                "tone": "terse_direct",
                "max_items": 1,
                "allowed_urgency": "critical_only",
            }
        )
    elif state == "anchored" and calendar_buffer_hours is not None and calendar_buffer_hours <= 2:
        policy.update({"message_type": "commitment_reminder", "allowed_urgency": "scheduled_commitment"})
    elif state == "anchored" and unanswered_checkins > 1:
        policy.update({"message_type": "silent", "allow_message": False, "max_items": 0})
    elif state == "unknown" and "daily_brief" in trigger:
        policy.update(
            {
                "allow_message": True,
                "message_type": "daily_brief",
                "tone": "neutral_digest",
                "max_items": 3,
            }
        )

    policy["required_actions"] = ["log_policy_decision"]
    if policy.get("allow_message"):
        policy["required_actions"].append("record_checkin_if_sent")
    return policy


def _choices(life_os_context: dict[str, Any]) -> list[str]:
    top_choices = life_os_context.get("top_choices") or []
    choices = [str(item).strip() for item in top_choices if str(item).strip()]
    return choices[:3] or DEFAULT_CHOICES


def _approved_message(state: str, policy: dict[str, Any], inputs: dict[str, Any], life_os_context: dict[str, Any]) -> dict[str, Any]:
    if not policy.get("allow_message"):
        return {"text": "", "choices": []}

    choices = _choices(life_os_context)
    message_type = policy.get("message_type")
    recovery = inputs.get("recovery_score")

    if message_type == "critical_alert":
        item = choices[0]
        return {"text": f"Critical item only: {item}. Handle or explicitly defer it.", "choices": [item, "Defer with reason"]}
    if message_type == "commitment_reminder":
        return {"text": "Next commitment is close. Confirm the one prep item or clear it.", "choices": choices[:2]}
    if message_type == "structure_prompt":
        recovery_text = f"Recovery is {recovery:.0f}%" if isinstance(recovery, (int, float)) else "Recovery is low/unclear"
        return {"text": f"{recovery_text}. Pick one thing to move now.", "choices": choices}
    if message_type == "recovery_prompt":
        return {"text": "Low-capacity mode. Pick one low-pressure next step or call recovery.", "choices": choices[:2] + ["Recovery block"]}
    if message_type == "deep_work_prompt":
        return {"text": "This looks like a high-capacity window. Protect one hard-work block.", "choices": choices}
    if message_type == "task_check":
        return {"text": "Quick task check: choose the one item that should move next.", "choices": choices}
    if message_type == "daily_brief":
        return {"text": "Digest mode only. Review the top items without adding extra interruptions.", "choices": choices}
    return {"text": "", "choices": []}


def build_policy_contract(
    context: dict[str, Any],
    *,
    trigger_source: str = "",
    life_os_context: dict[str, Any] | None = None,
    audit_logged: bool = False,
    verification_status: str | None = None,
) -> dict[str, Any]:
    """Return a typed behavior contract Poke can obey without improvising."""
    life_context = life_os_context or {}
    whoop_data = context.get("whoop_data") or {}
    calendar = context.get("calendar") or {}
    checkin_status = context.get("checkin_status") or {}
    opt_out = context.get("opt_out") or {}
    state = _state(context)
    timestamp = _timestamp(context)
    calendar_buffer_hours = _num(calendar.get("buffer_hours"))
    unanswered_checkins = int(_num(checkin_status.get("unanswered_count")) or 0)

    inputs = {
        "recovery_score": _num(whoop_data.get("recovery_score")),
        "sleep_hours": _num(whoop_data.get("sleep_hours")),
        "sleep_efficiency": _num(whoop_data.get("sleep_efficiency")),
        "hrv": _num(whoop_data.get("hrv")),
        "resting_hr": _num(whoop_data.get("resting_hr")),
        "calendar_buffer_hours": calendar_buffer_hours,
        "open_p1_tasks": int(life_context.get("open_p1_tasks") or 0),
        "open_p2_tasks": int(life_context.get("open_p2_tasks") or 0),
        "overdue_p1_tasks": int(life_context.get("overdue_p1_tasks") or 0),
        "pending_approvals": int(life_context.get("pending_approvals") or 0),
        "review_queue_count": int(life_context.get("review_queue_count") or 0),
        "unanswered_checkins": unanswered_checkins,
        "opt_out_active": bool(opt_out.get("active")),
        "trigger_source": trigger_source or "unspecified",
        "life_os_context_available": bool(life_context),
    }

    policy = _policy_for_state(
        state,
        trigger_source=trigger_source,
        calendar_buffer_hours=calendar_buffer_hours,
        unanswered_checkins=unanswered_checkins,
        life_os_context=life_context,
    )
    if inputs["opt_out_active"] and policy.get("message_type") != "critical_alert":
        policy.update({"allow_message": False, "message_type": "silent", "max_items": 0})
        if "opt_out_active" not in policy["blocked_behaviors"]:
            policy["blocked_behaviors"].append("opt_out_active")

    decision_id = f"{timestamp[:19]}_{state}_{policy.get('message_type')}"
    approved_message = _approved_message(state, policy, inputs, life_context)
    if policy.get("message_type") not in ALLOWED_MESSAGE_TYPES:
        policy["message_type"] = "silent"
        policy["allow_message"] = False
        approved_message = {"text": "", "choices": []}

    return {
        "decision_id": decision_id,
        "state": state,
        "inputs": inputs,
        "policy": policy,
        "approved_message": approved_message,
        "audit": {
            "logged": bool(audit_logged),
            "verification_status": verification_status or ("Verified Log" if audit_logged else "Policy Preview - Not Logged"),
        },
        "context_timestamp": timestamp,
    }
