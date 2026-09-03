from __future__ import annotations

import unittest
from datetime import datetime, timezone

from daily_pipeline import (
    apply_override,
    day_completion,
    evaluate_day_status,
    select_day_records,
    snapshot_hash,
    retry_metadata,
)


NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)


def sleep_record(*, state="SCORED", offset="-04:00", end="2026-09-03T14:00:00Z"):
    return {
        "id": "sleep-1", "score_state": state, "nap": False,
        "start": "2026-09-03T06:00:00Z", "end": end,
        "timezone_offset": offset,
        "score": {
            "sleep_efficiency_percentage": 90,
            "stage_summary": {"total_light_sleep_time_milli": 10_000},
        },
    }


def recovery_record(*, state="SCORED", score=70):
    return {
        "id": "recovery-1", "sleep_id": "sleep-1", "score_state": state,
        "created_at": "2026-09-03T14:10:00Z", "updated_at": "2026-09-03T14:15:00Z",
        "score": {"recovery_score": score, "spo2_percentage": 95},
    }


class DailyPipelineTests(unittest.TestCase):
    def test_incomplete_matching_pair_is_not_model_valid(self):
        records = {"sleep": sleep_record(), "recovery": None}
        status = evaluate_day_status("2026-09-03", records, None, now=NOW)
        self.assertEqual(status["data_status"], "incomplete")
        self.assertFalse(status["valid_for_model"])

    def test_revised_record_changes_snapshot_hash(self):
        original = {"date": "2026-09-02", "recovery": {"recovery_score": 61}}
        revised = {"date": "2026-09-02", "recovery": {"recovery_score": 66}}
        self.assertNotEqual(snapshot_hash(original), snapshot_hash(revised))
        self.assertEqual(snapshot_hash(original), snapshot_hash(dict(original)))

    def test_manual_invalidation_wins_over_scored_records(self):
        records = {"sleep": sleep_record(), "recovery": recovery_record()}
        override = {"invalidated": True, "reason": "User confirmed wake time was wrong."}
        status = evaluate_day_status("2026-09-03", records, override, now=NOW)
        self.assertEqual(status["data_status"], "manually_invalidated")
        self.assertFalse(status["valid_for_model"])

    def test_timezone_shift_assigns_sleep_by_local_end_date(self):
        shifted = sleep_record(offset="-06:00", end="2026-09-03T04:30:00Z")
        shifted["start"] = "2026-09-02T21:00:00Z"
        selected = select_day_records(
            "2026-09-02", [recovery_record()], [shifted], [], []
        )
        self.assertEqual(selected["sleep"]["id"], "sleep-1")

    def test_correction_override_is_applied_without_mutating_source(self):
        source = recovery_record(score=40)
        corrected = apply_override(
            "recovery", source,
            {"corrections": {"recovery": {"score.recovery_score": 55}}},
        )
        self.assertEqual(corrected["score"]["recovery_score"], 55)
        self.assertEqual(source["score"]["recovery_score"], 40)

    def test_current_day_calories_are_partial_and_prior_day_is_completed(self):
        cycle = {"timezone_offset": "-04:00"}
        self.assertEqual(day_completion("2026-09-03", cycle, now=NOW), "partial_day")
        self.assertEqual(day_completion("2026-09-02", cycle, now=NOW), "completed_day")

    def test_implausible_recovery_is_rejected(self):
        records = {"sleep": sleep_record(), "recovery": recovery_record(score=140)}
        status = evaluate_day_status("2026-09-03", records, None, now=NOW)
        self.assertEqual(status["data_status"], "implausible")
        self.assertIn("recovery_score_out_of_range", status["plausibility_issues"])

    def test_pending_day_requests_a_retry_but_invalidated_day_does_not(self):
        retry = retry_metadata("pending", now=NOW)
        self.assertEqual(retry["retry_after_seconds"], 900)
        self.assertIsNone(retry_metadata("manually_invalidated", now=NOW))


if __name__ == "__main__":
    unittest.main()
