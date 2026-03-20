import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.stats_engine import (
    normalize_container_stats,
    fetch_server_stats,
    _fetch_scope_stats,
    ROOTLESS_ENV_PREFIX,
)


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


class TestFetchScopeStats(unittest.IsolatedAsyncioTestCase):
    """Tests for the new _fetch_scope_stats() helper."""

    @patch("services.stats_engine.pool")
    async def test_rootless_commands_include_env_prefix(self, mock_pool):
        """Rootless (user) scope must prefix commands with XDG_RUNTIME_DIR."""
        stats_json = json.dumps([{"name": "app", "cpu_percent": "1%", "mem_percent": "2%"}])
        mock_pool.execute_command = AsyncMock(side_effect=["app", stats_json])

        result = await _fetch_scope_stats(server_id=1, rootful=False)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "app")

        # Verify the ps command includes the env prefix
        ps_call = mock_pool.execute_command.call_args_list[0]
        self.assertIn(ROOTLESS_ENV_PREFIX, ps_call[0][1])
        self.assertNotIn("sudo", ps_call[0][1])

        # Verify the stats command also includes the env prefix
        stats_call = mock_pool.execute_command.call_args_list[1]
        self.assertIn(ROOTLESS_ENV_PREFIX, stats_call[0][1])
        self.assertNotIn("sudo", stats_call[0][1])

    @patch("services.stats_engine.pool")
    async def test_rootful_commands_use_sudo(self, mock_pool):
        """Global (rootful) scope must use sudo, not the env prefix."""
        stats_json = json.dumps([{"Name": "system-app", "CPUPerc": "5%", "MemPerc": "10%"}])
        mock_pool.execute_command = AsyncMock(side_effect=["system-app", stats_json])

        result = await _fetch_scope_stats(server_id=1, rootful=True)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "system-app")

        # Verify sudo is used
        ps_call = mock_pool.execute_command.call_args_list[0]
        self.assertIn("sudo", ps_call[0][1])

        stats_call = mock_pool.execute_command.call_args_list[1]
        self.assertIn("sudo", stats_call[0][1])

    @patch("services.stats_engine.pool")
    async def test_no_running_containers_returns_empty(self, mock_pool):
        """If podman ps returns nothing, we get an empty list (no crash)."""
        mock_pool.execute_command = AsyncMock(return_value="  \n")

        result = await _fetch_scope_stats(server_id=1, rootful=False)

        self.assertEqual(result, [])
        # Only one call (ps), no stats call needed
        self.assertEqual(mock_pool.execute_command.call_count, 1)

    @patch("services.stats_engine.pool")
    async def test_ssh_error_returns_empty_list(self, mock_pool):
        """SSH errors are caught and logged; an empty list is returned."""
        mock_pool.execute_command = AsyncMock(side_effect=Exception("Connection refused"))

        result = await _fetch_scope_stats(server_id=1, rootful=False)

        self.assertEqual(result, [])

    @patch("services.stats_engine.pool")
    async def test_invalid_json_returns_empty_list(self, mock_pool):
        """If podman stats returns garbage, we return an empty list."""
        mock_pool.execute_command = AsyncMock(side_effect=["app", "not json"])

        result = await _fetch_scope_stats(server_id=1, rootful=True)

        self.assertEqual(result, [])


class TestFetchServerStats(unittest.IsolatedAsyncioTestCase):
    """Tests for fetch_server_stats() with mocked SSH pool, DB, and publisher."""

    @staticmethod
    def _make_db_mock(server_rows):
        """Build a mock that satisfies:
            async with get_db_connection() as db:
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

        # get_db_connection() is now a regular function returning an async CM
        mock_db_cm = AsyncMock()
        mock_db_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db_cm.__aexit__ = AsyncMock(return_value=False)

        mock_get_db = MagicMock(return_value=mock_db_cm)
        return mock_get_db

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine._fetch_scope_stats")
    @patch("services.stats_engine.get_db_connection")
    async def test_merges_user_and_global_containers(self, mock_get_db, mock_fetch, mock_publisher):
        """fetch_server_stats should merge rootless + rootful containers."""
        mock_get_db.side_effect = self._make_db_mock([(1, "testbox")])

        user_containers = [{"name": "user-app", "cpu": "1%", "mem": "2%",
                            "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
        global_containers = [{"name": "system-svc", "cpu": "3%", "mem": "4%",
                              "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "2"}]

        # _fetch_scope_stats is called twice: once rootful=False, once rootful=True
        mock_fetch.side_effect = [user_containers, global_containers]
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        mock_publisher.publish.assert_called_once()
        call_args = mock_publisher.publish.call_args
        self.assertEqual(call_args[0][0], "stats_update")

        payload = call_args[0][1]
        self.assertEqual(payload["server_id"], 1)
        self.assertEqual(payload["server_name"], "testbox")
        self.assertEqual(len(payload["containers"]), 2)
        names = [c["name"] for c in payload["containers"]]
        self.assertIn("user-app", names)
        self.assertIn("system-svc", names)

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine._fetch_scope_stats")
    @patch("services.stats_engine.get_db_connection")
    async def test_empty_both_scopes_publishes_empty(self, mock_get_db, mock_fetch, mock_publisher):
        """When no containers run in either scope, publish empty update."""
        mock_get_db.side_effect = self._make_db_mock([(2, "emptybox")])

        mock_fetch.side_effect = [[], []]
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        mock_publisher.publish.assert_called_once_with("stats_update", {
            "server_id": 2,
            "server_name": "emptybox",
            "containers": [],
        })

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine._fetch_scope_stats")
    @patch("services.stats_engine.get_db_connection")
    async def test_gather_exception_publishes_error(self, mock_get_db, mock_fetch, mock_publisher):
        """If the gather itself raises, we publish a stats_error event."""
        mock_get_db.side_effect = self._make_db_mock([(3, "badbox")])

        mock_fetch.side_effect = Exception("something broke")
        mock_publisher.publish = AsyncMock()

        await fetch_server_stats()

        mock_publisher.publish.assert_called_once_with("stats_error", {
            "server_id": 3,
            "server_name": "badbox",
            "error": "something broke",
        })

    @patch("services.stats_engine.publisher")
    @patch("services.stats_engine._fetch_scope_stats")
    @patch("services.stats_engine.get_db_connection")
    async def test_multiple_servers_each_publish(self, mock_get_db, mock_fetch, mock_publisher):
        """When multiple servers exist, stats are fetched and published for each."""
        mock_get_db.side_effect = self._make_db_mock([(1, "server-a"), (2, "server-b")])

        # Each server gets two _fetch_scope_stats calls (user + global)
        containers_a = [{"name": "app-a", "cpu": "1%", "mem": "2%",
                         "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
        containers_b = [{"name": "app-b", "cpu": "3%", "mem": "4%",
                         "mem_usage": "—", "net_io": "—", "block_io": "—", "pids": "1"}]
        mock_fetch.side_effect = [containers_a, [], [], containers_b]
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
