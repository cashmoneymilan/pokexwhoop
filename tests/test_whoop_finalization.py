from __future__ import annotations

import unittest
from datetime import datetime, timezone

from whoop_client import select_stable_whoop_records


NOW = datetime(2026, 6, 23, 14, 0, tzinfo=timezone.utc)


def sleep(
    sleep_id: str,
    *,
    score_state: str = "SCORED",
    end: str = "2026-06-23T12:00:00.000Z",
    nap: bool = False,
) -> dict:
    return {
        "id": sleep_id,
        "score_state": score_state,
        "start": "2026-06-23T04:00:00.000Z",
        "end": end,
        "nap": nap,
        "score": {"sleep_efficiency_percentage": 93},
    }


def recovery(sleep_id: str, *, score_state: str = "SCORED", recovery_score: int = 50) -> dict:
    return {
        "id": f"recovery-{sleep_id}",
        "sleep_id": sleep_id,
        "created_at": "2026-06-23T12:10:00.000Z",
        "score_state": score_state,
        "score": {
            "recovery_score": recovery_score,
            "hrv_rmssd_milli": 54.2,
            "resting_heart_rate": 67,
        },
    }


class WhoopFinalizationTests(unittest.TestCase):
    def test_pending_sleep_is_rejected(self) -> None:
        result = select_stable_whoop_records(
            [recovery("sleep-1")],
            [sleep("sleep-1", score_state="PENDING_SCORE")],
            now=NOW,
        )

        self.assertIsNone(result["recovery"])
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "pending_score")
        self.assertEqual(result["metadata"]["sleep_score_state"], "PENDING_SCORE")

    def test_pending_recovery_is_rejected(self) -> None:
        result = select_stable_whoop_records(
            [recovery("sleep-1", score_state="PENDING_SCORE", recovery_score=29)],
            [sleep("sleep-1")],
            now=NOW,
        )

        self.assertEqual(result["sleep"]["id"], "sleep-1")
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "pending_score")
        self.assertEqual(result["metadata"]["recovery_score_state"], "PENDING_SCORE")

    def test_recovery_must_match_selected_sleep_id(self) -> None:
        result = select_stable_whoop_records(
            [recovery("different-sleep")],
            [sleep("sleep-1")],
            now=NOW,
        )

        self.assertEqual(result["metadata"]["whoop_data_freshness"], "missing")
        self.assertEqual(result["metadata"]["freshness_reason"], "No recovery matched the selected finalized sleep_id.")

    def test_non_nap_scored_sleep_is_preferred_over_newer_nap(self) -> None:
        result = select_stable_whoop_records(
            [recovery("main-sleep")],
            [
                sleep("nap-1", end="2026-06-23T13:00:00.000Z", nap=True),
                sleep("main-sleep", end="2026-06-23T11:00:00.000Z", nap=False),
            ],
            now=NOW,
        )

        self.assertEqual(result["sleep"]["id"], "main-sleep")
        self.assertEqual(result["recovery"]["sleep_id"], "main-sleep")
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "finalized_current")

    def test_recent_sleep_inside_delay_is_too_fresh(self) -> None:
        result = select_stable_whoop_records(
            [recovery("sleep-1")],
            [sleep("sleep-1", end="2026-06-23T13:45:00.000Z")],
            now=NOW,
            finalization_delay_minutes=30,
        )

        self.assertIsNone(result["recovery"])
        self.assertEqual(result["metadata"]["whoop_data_freshness"], "too_fresh")


if __name__ == "__main__":
    unittest.main()
