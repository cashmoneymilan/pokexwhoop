from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from whoop_client import WhoopClient


class WhoopPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_collection_follows_next_token_until_requested_limit(self):
        client = WhoopClient()
        client._request = AsyncMock(side_effect=[
            {"records": [{"id": index} for index in range(25)], "next_token": "page-2"},
            {"records": [{"id": index} for index in range(25, 40)]},
        ])

        records = await client._get_collection("/v2/activity/sleep", limit=40)

        self.assertEqual(len(records), 40)
        self.assertEqual(
            client._request.await_args_list[1].args[1]["nextToken"],
            "page-2",
        )

    async def test_collection_stops_when_token_repeats(self):
        client = WhoopClient()
        client._request = AsyncMock(side_effect=[
            {"records": [{"id": 1}], "next_token": "same"},
            {"records": [{"id": 2}], "next_token": "same"},
        ])

        records = await client._get_collection("/v2/cycle", limit=30)

        self.assertEqual([record["id"] for record in records], [1, 2])
        self.assertEqual(client._request.await_count, 2)


if __name__ == "__main__":
    unittest.main()
