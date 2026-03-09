import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.stats_engine import normalize_container_stats, fetch_server_stats


class TestNormalizeContainerStats(unittest.TestCase):
    """Tests for the pure normalize_container_stats() function.

    This handles field-name differences across Podman versions,
    so we test multiple real-world JSON shapes.
    """

    def test_podman_v4_format(self):
        """Podman 4.x uses keys like 'CPUPerc', 'MemPerc', etc."""
        raw = {
            "Name": "nginx",
            "CPUPerc": "12.34%",
            "MemPerc": "5.67%",
            "MemUsage": "128MiB / 2GiB",
            "NetIO": "1.2kB / 3.4kB",
            "BlockIO": "500B / 1kB",
            "PIDs": "4",
        }
        result = normalize_container_stats(raw)

        self.assertEqual(result["name"], "nginx")
        self.assertEqual(result["cpu"], "12.34%")
        self.assertEqual(result["mem"], "5.67%")
        self.assertEqual(result["mem_usage"], "128MiB / 2GiB")
        self.assertEqual(result["net_io"], "1.2kB / 3.4kB")
        self.assertEqual(result["block_io"], "500B / 1kB")
        self.assertEqual(result["pids"], "4")

    def test_podman_v3_format(self):
        """Podman 3.x uses lowercase keys like 'cpu_percent', 'mem_percent'."""
        raw = {
            "name": "redis",
            "cpu_percent": "0.50%",
            "mem_percent": "2.10%",
            "mem_usage": "64MiB / 1GiB",
            "net_io": "800B / 200B",
            "block_io": "0B / 0B",
            "pids": "1",
        }
        result = normalize_container_stats(raw)

        self.assertEqual(result["name"], "redis")
        self.assertEqual(result["cpu"], "0.50%")
        self.assertEqual(result["mem"], "2.10%")
        self.assertEqual(result["net_io"], "800B / 200B")
        self.assertEqual(result["pids"], "1")

    def test_missing_fields_fallback_to_defaults(self):
        """If a field is completely absent, we get safe defaults (no KeyError)."""
        raw = {}
        result = normalize_container_stats(raw)

        self.assertEqual(result["name"], "unknown")
        self.assertEqual(result["cpu"], "0%")
        self.assertEqual(result["mem"], "0%")
        self.assertEqual(result["mem_usage"], "—")
        self.assertEqual(result["net_io"], "—")
        self.assertEqual(result["block_io"], "—")
        self.assertEqual(result["pids"], "0")

    def test_mixed_keys_prefers_lowercase(self):
        """When both v3 and v4 keys exist, lowercase (v3) wins because
        of the `or` chain order in normalize_container_stats."""
        raw = {
            "name": "mixed",
            "Name": "MIXED_UPPER",
            "cpu_percent": "1.00%",
            "CPUPerc": "99.00%",
        }
        result = normalize_container_stats(raw)

        self.assertEqual(result["name"], "mixed")
        self.assertEqual(result["cpu"], "1.00%")

    def test_empty_string_values_treated_as_missing(self):
        """Empty strings are falsy, so the fallback should kick in."""
        raw = {
            "name": "",
            "cpu_percent": "",
            "mem_percent": "",
        }
        result = normalize_container_stats(raw)

        # Empty name falls through to "Name" key (also missing) → "unknown"
        self.assertEqual(result["name"], "unknown")
        self.assertEqual(result["cpu"], "0%")
        self.assertEqual(result["mem"], "0%")

    def test_all_keys_present_in_output(self):
        """Verify the output always contains exactly the expected keys."""
        raw = {"name": "test"}
        result = normalize_container_stats(raw)
        expected_keys = {"name", "cpu", "mem", "mem_usage", "net_io", "block_io", "pids"}

        self.assertEqual(set(result.keys()), expected_keys)


class TestFetchServerStats(unittest.IsolatedAsyncioTestCase):
    """Tests for fetch_server_stats() with mocked SSH pool, DB, and publisher."""

    @staticmethod
    def _make_db_mock(server_rows):
        """Build a mock that satisfies:
            async with await get_db_connection() as db:
                async with db.execute(...) as cursor:
                    rows = await cursor.fetchall()
        """
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=server_rows)

        # db.execute(...) must return an async context manager yielding the cursor
        mock_cursor_cm = AsyncMock()
        mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor_cm.__aexit__ = AsyncMock(return_value=False)

        mock_db = AsyncMock()
        mock_db.execute = MagicMock(return_value=mock_cursor_cm)

        # get_db_connection() is awaited, then used as async CM → returns mock_db
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)

        mock_get_db = AsyncMock(return_value=mock_db_cm)
        return mock_get_db

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine.pool")
    @patch("services.stats_engine.get_db_connection")
    async def test_publishes_normalized_stats(self, mock_get_db, mock_pool, mock_publisher):
        """Verifies the full flow: DB query → SSH command → normalize → publish."""
        mock_get_db.side_effect = self._make_db_mock([(1, "testbox")])

        podman_output = json.dumps([{
            "Name": "web",
            "CPUPerc": "3.21%",
            "MemPerc": "8.50%",
            "MemUsage": "256MiB / 4GiB",
            "NetIO": "12kB / 5kB",
            "BlockIO": "1kB / 2kB",
            "PIDs": "7",
        }])
        mock_pool.execute_command = AsyncMock(return_value=podman_output)
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        mock_pool.execute_command.assert_called_once_with(1, "podman stats --no-stream --format json")

        mock_publisher.publish.assert_called_once()
        call_args = mock_publisher.publish.call_args
        self.assertEqual(call_args[0][0], "stats_update")

        payload = call_args[0][1]
        self.assertEqual(payload["server_id"], 1)
        self.assertEqual(payload["server_name"], "testbox")
        self.assertEqual(len(payload["containers"]), 1)
        self.assertEqual(payload["containers"][0]["name"], "web")
        self.assertEqual(payload["containers"][0]["cpu"], "3.21%")

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine.pool")
    @patch("services.stats_engine.get_db_connection")
    async def test_empty_stats_output_publishes_empty_list(self, mock_get_db, mock_pool, mock_publisher):
        """When podman returns empty output (no containers), we still publish an empty update."""
        mock_get_db.side_effect = self._make_db_mock([(2, "emptybox")])

        mock_pool.execute_command = AsyncMock(return_value="   \n")
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        mock_publisher.publish.assert_called_once_with("stats_update", {
            "server_id": 2,
            "server_name": "emptybox",
            "containers": []
        })

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine.pool")
    @patch("services.stats_engine.get_db_connection")
    async def test_ssh_error_does_not_crash(self, mock_get_db, mock_pool, mock_publisher):
        """If SSH fails for a server, the function logs the error but doesn't raise."""
        mock_get_db.side_effect = self._make_db_mock([(3, "badbox")])

        mock_pool.execute_command = AsyncMock(side_effect=ConnectionError("SSH timeout"))
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        mock_publisher.publish.assert_not_called()

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine.pool")
    @patch("services.stats_engine.get_db_connection")
    async def test_invalid_json_does_not_crash(self, mock_get_db, mock_pool, mock_publisher):
        """If podman returns garbage, we log the error but don't crash."""
        mock_get_db.side_effect = self._make_db_mock([(4, "garblebox")])

        mock_pool.execute_command = AsyncMock(return_value="not valid json {{{")
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        mock_publisher.publish.assert_not_called()

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine.pool")
    @patch("services.stats_engine.get_db_connection")
    async def test_multiple_servers_each_publish(self, mock_get_db, mock_pool, mock_publisher):
        """When multiple servers exist, stats are fetched and published for each."""
        mock_get_db.side_effect = self._make_db_mock([(1, "server-a"), (2, "server-b")])

        stats_a = json.dumps([{"name": "app-a", "cpu_percent": "1%", "mem_percent": "2%"}])
        stats_b = json.dumps([{"name": "app-b", "cpu_percent": "3%", "mem_percent": "4%"}])
        mock_pool.execute_command = AsyncMock(side_effect=[stats_a, stats_b])
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        self.assertEqual(mock_publisher.publish.call_count, 2)

        first_call = mock_publisher.publish.call_args_list[0][0]
        self.assertEqual(first_call[1]["server_name"], "server-a")
        self.assertEqual(first_call[1]["containers"][0]["name"], "app-a")

        second_call = mock_publisher.publish.call_args_list[1][0]
        self.assertEqual(second_call[1]["server_name"], "server-b")
        self.assertEqual(second_call[1]["containers"][0]["name"], "app-b")


if __name__ == "__main__":
    unittest.main()
