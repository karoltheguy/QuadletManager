import asyncio
import logging
import shlex
import time
from core.database import get_db_connection
from services.ssh_manager import pool
from services.remote_fs import is_global_scope
from core.events_manager import publisher

logger = logging.getLogger("quadlet-manager.sync")

POLL_INTERVAL_SEC = 10

SLOW_FETCH_THRESHOLD_SEC = 5
CONSECUTIVE_FAILURES_THRESHOLD = 3
CYCLE_BUDGET_RATIO = 0.8


class PollHealthTracker:
    """Tracks per-server fetch health and per-cycle budget usage.

    Events are edge-triggered: methods return a payload dict only when the
    health/budget state transitions, and ``None`` otherwise.
    """

    def __init__(self):
        self._servers = {}
        self._cycle = None

    def record_fetch(self, server_id, duration, success) -> dict | None:
        """Record a single server's fetch outcome and return a transition event, if any."""
        prev = self._servers.get(server_id, {"healthy": True, "consecutive_failures": 0, "last_duration": None})
        prev_healthy = prev["healthy"]

        if success:
            consecutive_failures = 0
            unhealthy = duration > SLOW_FETCH_THRESHOLD_SEC
            reason_if_unhealthy = "slow_fetch"
        else:
            consecutive_failures = prev["consecutive_failures"] + 1
            unhealthy = consecutive_failures >= CONSECUTIVE_FAILURES_THRESHOLD
            reason_if_unhealthy = "consecutive_failures"

        new_healthy = not unhealthy

        self._servers[server_id] = {
            "healthy": new_healthy,
            "consecutive_failures": consecutive_failures,
            "last_duration": duration,
        }

        if new_healthy == prev_healthy:
            return None

        reason = "recovered" if new_healthy else reason_if_unhealthy
        return {
            "scope": "server",
            "server_id": server_id,
            "healthy": new_healthy,
            "reason": reason,
            "consecutive_failures": consecutive_failures,
            "last_duration": duration,
        }

    def record_cycle(self, duration, interval) -> dict | None:
        """Record a full poll cycle's duration and return a budget transition event, if any."""
        prev_exceeded = self._cycle["budget_exceeded"] if self._cycle else False
        budget_exceeded = duration > (CYCLE_BUDGET_RATIO * interval)

        self._cycle = {
            "duration": duration,
            "interval": interval,
            "budget_exceeded": budget_exceeded,
        }

        if budget_exceeded == prev_exceeded:
            return None

        return dict(self._cycle, scope="cycle")

    def snapshot(self) -> dict:
        """Return the current per-server and per-cycle health state."""
        return {
            "servers": dict(self._servers),
            "cycle": dict(self._cycle) if self._cycle else None,
        }

    def prune(self, active_server_ids):
        """Drop tracked servers that are no longer present in ``active_server_ids``."""
        active = set(active_server_ids)
        for server_id in list(self._servers.keys()):
            if server_id not in active:
                del self._servers[server_id]


health_tracker = PollHealthTracker()

async def parse_mtime(stdout: str) -> int:
    try:
        return int(stdout.strip())
    except ValueError:
        return 0

def _quote_remote_path(path: str) -> str:
    """Quote a remote path for safe shell use.

    Preserves a leading ~/ so the remote shell still performs tilde
    (home directory) expansion.
    """
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)

async def _fetch_mtimes(server_id, use_sudo, paths) -> dict[str, int]:
    """Fetch mtimes for multiple remote paths on the same server and scope.

    Performs this in a single SSH round-trip, mapping the stat output back to
    the caller's (possibly tilde-prefixed) DB paths.
    """
    quoted = [_quote_remote_path(p) for p in paths]
    cmd = "stat -c '%n %Y' " + " ".join(quoted) + " 2>/dev/null; true"

    output = await pool.execute_command(server_id, cmd, use_sudo=use_sudo)

    printed = {}
    for line in (output or "").splitlines():
        if not line.strip():
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        printed_path, mtime_str = parts
        try:
            mtime = int(mtime_str)
        except ValueError:
            continue
        printed[printed_path] = mtime

    result = {}
    for p in paths:
        if p in printed:
            result[p] = printed[p]
        elif p.startswith("~"):
            suffix = p[1:]
            for printed_path, mtime in printed.items():
                if printed_path.endswith(suffix):
                    result[p] = mtime
                    break
    return result


async def _timed_fetch(server_id, use_sudo, paths):
    """Run ``_fetch_mtimes`` while timing it, capturing failure instead of raising.

    Returns a ``(result_or_exception, duration, success)`` tuple so callers can
    feed the outcome into the poll-health tracker regardless of the group's fate.
    """
    start = time.monotonic()
    try:
        result = await _fetch_mtimes(server_id, use_sudo, paths)
        return result, time.monotonic() - start, True
    except Exception as e:
        return e, time.monotonic() - start, False


async def check_quadlets():
    """Polls all registered quadlets to see if the remote file has been modified."""
    cycle_start = time.monotonic()

    async with get_db_connection() as db:
        db.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
        async with db.execute("SELECT id, server_id, file_path, scope, last_known_mtime FROM quadlets") as cursor:
            quadlets = await cursor.fetchall()

    groups = {}
    for q in quadlets:
        key = (q['server_id'], is_global_scope(q['scope']))
        groups.setdefault(key, []).append(q)

    group_keys = list(groups.keys())
    tasks = [
        _timed_fetch(server_id, use_sudo, [q['file_path'] for q in groups[(server_id, use_sudo)]])
        for (server_id, use_sudo) in group_keys
    ]
    timed_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Aggregate per server_id across its (server_id, use_sudo) groups: any
    # group failure marks the server as failed, and its duration is the max
    # across its groups.
    server_health = {}

    for (server_id, use_sudo), timed in zip(group_keys, timed_results):
        rows = groups[(server_id, use_sudo)]

        if isinstance(timed, Exception):
            result, duration, success = timed, 0.0, False
        else:
            result, duration, success = timed

        agg = server_health.setdefault(server_id, {"failed": False, "duration": 0.0})
        agg["duration"] = max(agg["duration"], duration)
        if not success:
            agg["failed"] = True

        if not success:
            logger.error(f"Error polling server {server_id} (use_sudo={use_sudo}): {result}")
            continue

        for q in rows:
            try:
                if q['file_path'] not in result:
                    continue

                remote_mtime = result[q['file_path']]

                # If the remote is newer than the DB timestamp
                if q['last_known_mtime'] is not None and remote_mtime > q['last_known_mtime']:
                    logger.warning(f"File {q['file_path']} on server {q['server_id']} was modified externally!")

                    # Emit Server-Sent Event broadcast (SSE)
                    await publisher.publish("file_changed", {
                        "server_id": q['server_id'],
                        "file_path": q['file_path'],
                        "message": "File modified externally!"
                    })

                    async with get_db_connection() as db:
                        await db.execute(
                            "UPDATE quadlets SET last_known_mtime = ? WHERE id = ?",
                            (remote_mtime, q['id'])
                        )
                        await db.commit()

            except Exception:
                logger.exception(f"Error polling quadlet {q['id']}")

    for server_id, agg in server_health.items():
        event = health_tracker.record_fetch(server_id, agg["duration"], success=not agg["failed"])
        if event:
            await publisher.publish("poll_health", event)

    cycle_event = health_tracker.record_cycle(time.monotonic() - cycle_start, POLL_INTERVAL_SEC)
    if cycle_event:
        await publisher.publish("poll_health", cycle_event)

    health_tracker.prune([q['server_id'] for q in quadlets])

async def polling_engine_loop():
    logger.info("Starting Timestamp Polling background task.")
    try:
        while True:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                await check_quadlets()
            except asyncio.CancelledError:
                raise  # Re-raise to exit the loop
            except Exception:
                logger.exception("Polling engine error")
    except asyncio.CancelledError:
        logger.info("Polling engine stopped.")
