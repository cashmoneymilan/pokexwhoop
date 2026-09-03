from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import server


def sleep_record(day: str, sleep_id: str):
    return {
        "id": sleep_id, "score_state": "SCORED", "nap": False,
        "start": f"{day}T04:00:00Z", "end": f"{day}T12:00:00Z",
        "timezone_offset": "+00:00", "updated_at": f"{day}T12:30:00Z",
        "score": {
            "sleep_efficiency_percentage": 90,
            "sleep_performance_percentage": 85,
            "sleep_consistency_percentage": 80,
            "respiratory_rate": 14,
            "stage_summary": {
                "total_light_sleep_time_milli": 12_000_000,
                "total_slow_wave_sleep_time_milli": 5_000_000,
                "total_rem_sleep_time_milli": 6_000_000,
                "total_awake_time_milli": 1_000_000,
                "disturbance_count": 4,
            },
            "sleep_needed": {"baseline_milli": 28_800_000},
        },
    }


def recovery_record(day: str, sleep_id: str, score: int):
    return {
        "id": f"recovery-{sleep_id}", "sleep_id": sleep_id, "score_state": "SCORED",
        "created_at": f"{day}T12:10:00Z", "updated_at": f"{day}T12:20:00Z",
        "timezone_offset": "+00:00",
        "score": {"recovery_score": score, "hrv_rmssd_milli": 50, "resting_heart_rate": 60},
    }


class DailySummaryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_persists_and_compares_previous_valid_day(self):
        sleeps = [sleep_record("2026-09-02", "sleep-2"), sleep_record("2026-09-01", "sleep-1")]
        recoveries = [
            recovery_record("2026-09-02", "sleep-2", 70),
            recovery_record("2026-09-01", "sleep-1", 60),
        ]
        cycles = [{
            "id": "cycle-2", "score_state": "SCORED", "start": "2026-09-02T00:00:00Z",
            "end": "2026-09-03T00:00:00Z", "timezone_offset": "+00:00",
            "score": {"kilojoule": 8368, "strain": 10, "average_heart_rate": 75, "max_heart_rate": 150},
        }]
        with (
            patch.object(server.whoop_client, "get_recovery", AsyncMock(return_value=recoveries)),
            patch.object(server.whoop_client, "get_sleep", AsyncMock(return_value=sleeps)),
            patch.object(server.whoop_client, "get_cycles", AsyncMock(return_value=cycles)),
            patch.object(server.whoop_client, "get_workouts", AsyncMock(return_value=[])),
            patch.object(server.database, "save_daily_report", AsyncMock(return_value={"revision": 1, "is_revision": False, "snapshot_hash": "abc"})) as save,
            patch.object(server.database, "update_daily_sync_job", AsyncMock()),
        ):
            result = await server.get_historical_day("2026-09-02")

        self.assertEqual(result["data_status"], "finalized")
        self.assertTrue(result["valid_for_model"])
        self.assertTrue(result["calories_valid_for_weight_loss_model"])
        self.assertEqual(result["cycle"]["calories_kcal"], 2000.0)
        self.assertEqual(result["comparison"]["previous_date"], "2026-09-01")
        self.assertEqual(result["comparison"]["deltas"]["recovery_score"], 10.0)
        save.assert_awaited_once()

    async def test_known_august_23_day_is_manually_invalidated(self):
        sleep = sleep_record("2026-08-23", "bad-sleep")
        recovery = recovery_record("2026-08-23", "bad-sleep", 80)
        with (
            patch.object(server.whoop_client, "get_recovery", AsyncMock(return_value=[recovery])),
            patch.object(server.whoop_client, "get_sleep", AsyncMock(return_value=[sleep])),
            patch.object(server.whoop_client, "get_cycles", AsyncMock(return_value=[])),
            patch.object(server.whoop_client, "get_workouts", AsyncMock(return_value=[])),
            patch.object(server.database, "save_daily_report", AsyncMock(return_value={"revision": 1, "is_revision": False, "snapshot_hash": "abc"})),
            patch.object(server.database, "update_daily_sync_job", AsyncMock()),
        ):
            result = await server.get_historical_day("2026-08-23")

        self.assertEqual(result["data_status"], "manually_invalidated")
        self.assertFalse(result["valid_for_model"])
        self.assertIsNone(result["sleep"])
        self.assertIsNone(result["recovery"])


if __name__ == "__main__":
    unittest.main()
