import asyncio
import json
import logging
import re
import shlex
import time
from collections import namedtuple
from core.database import get_db_connection
from services.ssh_manager import pool
from core.events_manager import publisher
from services.systemd_manager import ROOTLESS_ENV_PREFIX, build_unit_state_command, parse_systemctl_show
from services.quadlet_naming import base_name_of, quadlet_type_of, unit_name_for
from services.container_events import record_container_event

# Mirrors the INSERT column order for container_health_history.
# Using a namedtuple here lets tests assert by field name rather than magic index.
HealthRecord = namedtuple(
    "HealthRecord",
    ["server_id", "container_name", "is_running", "cpu_pct", "mem_pct", "recorded_at", "resolution_sec", "health_status"],
)

# Fetched together: podman ps stats for a scope, plus systemd unit states for
# that scope's quadlet-backed container units.
ScopeResult = namedtuple("ScopeResult", ["containers", "unit_states"])

# Marker used to split a batched `podman ps ...; echo '<sentinel>'; systemctl show ...`
# SSH response back into its two halves. Must not be able to appear in podman
# JSON output or systemctl show output.
_UNIT_STATE_SENTINEL = "---QM-UNIT-STATE---"

logger = logging.getLogger("quadlet-manager.stats")

STATS_INTERVAL_SEC = 5
ROLLUP_INTERVAL_SEC = 300  # Run rollup every 5 minutes

_last_rollup_time: float = 0

# Track previously-running containers per server so we can write is_running=0
# records when a container disappears.
_prev_running_by_sid: dict[int, set] = {}

# Track previous unit state per server so we can detect transitions (e.g.
# entering the failed state) and record them as durable container events.
_prev_unit_state_by_sid: dict[int, dict] = {}


def _parse_pct(val) -> float:
    """Parse a percentage value from '5.23%' string or numeric."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.rstrip('%'))
        except ValueError:
            return 0.0
    return 0.0


async def _record_health_history(server_id: int, containers: list[dict]) -> None:
    """Persist a health snapshot. Pruning is handled by rollup_health_history()."""
    now = int(time.time())

    current_names = {c['name'] for c in containers}
    prev_names = _prev_running_by_sid.get(server_id, set())
    stopped_names = prev_names - current_names

    records = []
    for c in containers:
        records.append(HealthRecord(server_id, c['name'], 1, _parse_pct(c.get('cpu', 0)), _parse_pct(c.get('mem', 0)), now, 5, c.get('health', '') or None))
    for name in stopped_names:
        records.append(HealthRecord(server_id, name, 0, 0.0, 0.0, now, 5, None))

    _prev_running_by_sid[server_id] = current_names

    if not records:
        return

    async with get_db_connection() as db:
        await db.executemany(
            "INSERT INTO container_health_history "
            "(server_id, container_name, is_running, cpu_pct, mem_pct, recorded_at, resolution_sec, health_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            records,
        )
        await db.commit()


async def rollup_health_history() -> None:
    """Downsample aged history rows to keep DB size bounded across all servers.

    Tier transitions (all in one transaction):
      raw 5s  → 1-min average  once rows are older than 1 hour
      1-min   → 5-min average  once rows are older than 24 hours
      5-min+  → deleted        once rows are older than 7 days
    """
    now = int(time.time())
    hour_cutoff = now - 3600
    day_cutoff = now - 86400
    week_cutoff = now - 604800

    async with get_db_connection() as db:
        # Step 1a: Insert 1-minute averages for raw rows older than 1 hour
        await db.execute("""
            INSERT INTO container_health_history
              (server_id, container_name, is_running, cpu_pct, mem_pct,
               recorded_at, resolution_sec, health_status)
            SELECT server_id, container_name,
              CAST(ROUND(AVG(is_running)) AS INTEGER),
              AVG(cpu_pct), AVG(mem_pct),
              (recorded_at / 60) * 60,
              60,
              (SELECT h2.health_status
               FROM container_health_history h2
               WHERE h2.server_id = h.server_id
                 AND h2.container_name = h.container_name
                 AND h2.recorded_at / 60 = h.recorded_at / 60
                 AND h2.resolution_sec = 5
               ORDER BY h2.recorded_at DESC LIMIT 1)
            FROM container_health_history h
            WHERE recorded_at < ?
              AND resolution_sec = 5
            GROUP BY server_id, container_name, recorded_at / 60
            HAVING COUNT(*) > 1
        """, (hour_cutoff,))

        # Step 1b: Delete the raw rows that have now been rolled up (or are lone strays)
        await db.execute("""
            DELETE FROM container_health_history
            WHERE recorded_at < ? AND resolution_sec = 5
        """, (hour_cutoff,))

        # Step 2a: Insert 5-minute averages for 1-min rows older than 24 hours
        await db.execute("""
            INSERT INTO container_health_history
              (server_id, container_name, is_running, cpu_pct, mem_pct,
               recorded_at, resolution_sec, health_status)
            SELECT server_id, container_name,
              CAST(ROUND(AVG(is_running)) AS INTEGER),
              AVG(cpu_pct), AVG(mem_pct),
              (recorded_at / 300) * 300,
              300,
              (SELECT h2.health_status
               FROM container_health_history h2
               WHERE h2.server_id = h.server_id
                 AND h2.container_name = h.container_name
                 AND h2.recorded_at / 300 = h.recorded_at / 300
                 AND h2.resolution_sec = 60
               ORDER BY h2.recorded_at DESC LIMIT 1)
            FROM container_health_history h
            WHERE recorded_at < ?
              AND resolution_sec = 60
            GROUP BY server_id, container_name, recorded_at / 300
            HAVING COUNT(*) > 1
        """, (day_cutoff,))

        # Step 2b: Delete the 1-min rows that have now been rolled up (or are lone strays)
        await db.execute("""
            DELETE FROM container_health_history
            WHERE recorded_at < ? AND resolution_sec = 60
        """, (day_cutoff,))

        # Step 3: Prune everything older than 7 days
        await db.execute("""
            DELETE FROM container_health_history WHERE recorded_at < ?
        """, (week_cutoff,))

        await db.commit()

    logger.debug("Health history rollup complete.")


PODMAN_PS_TIMEOUT = 5   # seconds – `podman ps` is near-instant; fail fast if Podman is frozen
STATS_CMD_TIMEOUT = 15  # seconds – --no-stream should return quickly


async def _unit_names_for_scope(server_id: int, scope: str) -> list[str]:
    """Return the systemd unit names for a server's .container quadlets in a scope.

    Only .container quadlets are mapped to a unit name -- Podman names other
    quadlet types' units differently (foo.volume -> foo-volume.service, etc),
    so blindly mapping every quadlet to <base>.service would query units that
    do not exist.
    """
    async with get_db_connection() as db:
        async with db.execute(
            "SELECT file_path FROM quadlets WHERE server_id = ? AND scope = ?",
            (server_id, scope),
        ) as cursor:
            rows = await cursor.fetchall()

    names: list[str] = []
    seen = set()
    for row in rows:
        file_path = row[0]
        basename = file_path.rsplit('/', 1)[-1]
        if quadlet_type_of(basename) != "container":
            continue
        unit_name = unit_name_for(basename)
        if unit_name not in seen:
            seen.add(unit_name)
            names.append(unit_name)
    return names


def normalize_container_stats(raw: dict) -> dict:
    """Normalize podman stats JSON keys across different Podman versions."""
    return {
        "name": raw.get("name") or raw.get("Name", "unknown"),
        "cpu": raw.get("cpu_percent") or raw.get("CPUPerc") or raw.get("CPU", "0%"),
        "mem": raw.get("mem_percent") or raw.get("MemPerc") or raw.get("Mem", "0%"),
        "mem_usage": raw.get("mem_usage") or raw.get("MemUsage", "—"),
        "net_io": raw.get("net_io") or raw.get("NetIO", "—"),
        "block_io": raw.get("block_io") or raw.get("BlockIO", "—"),
        "pids": raw.get("pids") or raw.get("PIDs", "0"),
    }


def _extract_name(names_field) -> str:
    """Normalise the Names field from podman ps --format json.

    Podman 3.x returns a list, Podman 4.x may return a plain string.
    """
    if isinstance(names_field, list):
        return names_field[0] if names_field else ""
    return str(names_field) if names_field else ""


def _build_podman_commands(rootful: bool) -> tuple[str, str]:
    """Construct command strings for ps and stats based on rootful/rootless scope."""
    if rootful:
        return "sudo podman ps --format json", "sudo podman stats"
    return (
        f"{ROOTLESS_ENV_PREFIX} podman ps --format json",
        f"{ROOTLESS_ENV_PREFIX} podman stats",
    )


def _extract_single_container_health(c: dict) -> str:
    """Extract health status string from raw podman container dict."""
    raw_health = c.get("HealthStatus") or c.get("Health") or ""
    if isinstance(raw_health, dict):
        raw_health = raw_health.get("Status", "")
    if not raw_health:
        # Fallback: some Podman versions omit HealthStatus/Health but
        # embed the state in the human-readable Status string, e.g.
        # "Up 3 hours (healthy)" or "Up 10 minutes (unhealthy)".
        m = re.search(r'\((healthy|unhealthy|starting)\)', c.get("Status", ""), re.IGNORECASE)
        if m:
            raw_health = m.group(1)
    return str(raw_health).lower()


def _parse_running_containers_and_health(ps_data: list[dict]) -> tuple[list[str], dict[str, str]]:
    """Build running container names list and health_map dictionary from podman ps JSON data."""
    running_names: list[str] = []
    health_map: dict[str, str] = {}
    for c in ps_data:
        name = _extract_name(c.get("Names", ""))
        if not name:
            continue
        running_names.append(name)
        health_map[name] = _extract_single_container_health(c)
    return running_names, health_map


def _merge_stats_and_health(stats_data: list[dict], health_map: dict[str, str]) -> list[dict]:
    """Combine normalized stats dicts with matching container health status."""
    result = []
    for raw in stats_data:
        container = normalize_container_stats(raw)
        container["health"] = health_map.get(container["name"], "")
        result.append(container)
    return result


async def _build_first_command(server_id: int, scope: str, ps_cmd: str, rootful: bool) -> str:
    """Batch the scope's systemctl show call onto the podman ps call.

    Returns ps_cmd unchanged when the scope has no quadlet-backed container
    units, so a server with no quadlets keeps issuing a plain podman ps.
    """
    unit_names = await _unit_names_for_scope(server_id, scope)
    if not unit_names:
        return ps_cmd

    systemctl_segment = build_unit_state_command(unit_names, scope)
    if rootful:
        systemctl_segment = f"sudo {systemctl_segment}"
    return f"{ps_cmd}; echo '{_UNIT_STATE_SENTINEL}'; {systemctl_segment}"


def _split_batched_output(first_stdout: str) -> tuple[str, dict]:
    """Split a batched ps+systemctl response into ps JSON and parsed unit states."""
    if _UNIT_STATE_SENTINEL not in first_stdout:
        return first_stdout, {}
    ps_json_str, _, systemctl_output = first_stdout.partition(_UNIT_STATE_SENTINEL)
    return ps_json_str, parse_systemctl_show(systemctl_output)


async def _fetch_scope_stats(server_id: int, rootful: bool) -> ScopeResult:
    """Fetch container stats and unit states for one scope (rootful or rootless).

    Uses podman ps --format json to get running names AND healthcheck status
    in a single SSH call, batched with a systemctl show call for this
    scope's quadlet-backed container units when there are any, then
    fetches resource stats separately.

    Returns a ScopeResult(containers, unit_states). unit_states may be
    non-empty even when containers is empty (e.g. all units stopped).
    """
    scope = "global" if rootful else "user"
    unit_states: dict = {}
    ps_cmd, stats_prefix = _build_podman_commands(rootful)

    try:
        first_cmd = await _build_first_command(server_id, scope, ps_cmd, rootful)
        first_stdout = await pool.execute_command(
            server_id, first_cmd, timeout=PODMAN_PS_TIMEOUT,
        )
        ps_json_str, unit_states = _split_batched_output(first_stdout)

        if not ps_json_str.strip():
            return ScopeResult([], unit_states)

        ps_data = json.loads(ps_json_str)
        running_names, health_map = _parse_running_containers_and_health(ps_data)
        if not running_names:
            return ScopeResult([], unit_states)

        names_arg = " ".join(shlex.quote(n) for n in running_names)
        cmd = f"{stats_prefix} --no-stream --format json {names_arg}"
        stats_json_str = await pool.execute_command(
            server_id, cmd, timeout=STATS_CMD_TIMEOUT,
        )

        if not stats_json_str.strip():
            return ScopeResult([], unit_states)

        stats_data = json.loads(stats_json_str)
        return ScopeResult(_merge_stats_and_health(stats_data, health_map), unit_states)

    except Exception as e:
        scope_label = "global" if rootful else "user"
        logger.warning(
            f"Could not fetch {scope_label}-scope stats for server {server_id}: {e}"
        )
        return ScopeResult([], unit_states)


async def _record_unit_states(server_id: int, unit_states_by_scope: dict) -> None:
    """Persist the latest known state for each unit, keyed by (server_id, unit_name, scope)."""
    now = int(time.time())

    records = []
    for scope, unit_states in unit_states_by_scope.items():
        for unit_name, state in unit_states.items():
            records.append((
                server_id,
                unit_name,
                scope,
                state.get("load_state"),
                state.get("active_state"),
                state.get("sub_state"),
                state.get("n_restarts", 0),
                now,
            ))

    if not records:
        return

    async with get_db_connection() as db:
        await db.executemany(
            "INSERT INTO unit_state "
            "(server_id, unit_name, scope, load_state, active_state, sub_state, n_restarts, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(server_id, unit_name, scope) DO UPDATE SET "
            "load_state = excluded.load_state, "
            "active_state = excluded.active_state, "
            "sub_state = excluded.sub_state, "
            "n_restarts = excluded.n_restarts, "
            "recorded_at = excluded.recorded_at",
            records,
        )
        await db.commit()


async def _record_unit_events(server_id: int, unit_states_by_scope: dict) -> None:
    """Detect durable unit-state transitions and record them as events.

    `unit_state` holds only the latest state, so a unit that fails and is
    then repaired leaves no trace there. This writes the transitions
    themselves into `container_events`, which already lists `failure` in its
    event_type CHECK constraint and uses age-based retention rather than the
    numeric rollup applied to CPU and memory (averaging a categorical state
    would be meaningless, and averaging a monotonic restart counter wrong).

    Compares each unit against its state on the previous poll and records
    `restart` and `failure` events on transitions only, not on every poll
    where a unit happens to be in a given state. `triggered_by="poller"`
    distinguishes these from the user-initiated events written by
    `api/routes.py`.
    """
    current = {
        (scope, unit_name): {
            "active_state": state.get("active_state", ""),
            "n_restarts": state.get("n_restarts", 0),
        }
        for scope, unit_states in unit_states_by_scope.items()
        for unit_name, state in unit_states.items()
    }

    prev = _prev_unit_state_by_sid.get(server_id)
    _prev_unit_state_by_sid[server_id] = current

    if prev is None:
        # First poll after process start: no baseline to compare against, so
        # seed silently rather than replaying every pre-existing failed unit
        # as a fresh event.
        return

    for (scope, unit_name), curr_entry in current.items():
        prev_entry = prev.get((scope, unit_name))
        if prev_entry is None:
            # Unit appeared mid-run: no baseline for it either, skip.
            continue

        stem = base_name_of(unit_name)

        if curr_entry["n_restarts"] > prev_entry["n_restarts"]:
            await record_container_event(
                server_id, stem, "restart",
                triggered_by="poller", details=f"scope={scope}",
            )

        if curr_entry["active_state"] == "failed" and prev_entry["active_state"] != "failed":
            await record_container_event(
                server_id, stem, "failure",
                triggered_by="poller", details=f"scope={scope}",
            )


def _scope_stat_tasks(server_id: int, scope_filter: str):
    """Return (tasks, scope_labels) for the scopes this server is configured for."""
    tasks = []
    scope_labels = []
    if scope_filter in ("both", "user"):
        tasks.append(_fetch_scope_stats(server_id, rootful=False))
        scope_labels.append("user")
    if scope_filter in ("both", "global"):
        tasks.append(_fetch_scope_stats(server_id, rootful=True))
        scope_labels.append("global")
    return tasks, scope_labels


def _merge_scope_results(scope_labels, results):
    """Return (containers, unit_states_by_scope) merged across scopes."""
    seen: dict[str, dict] = {}
    unit_states_by_scope: dict[str, dict] = {}
    for scope_label, scope_result in zip(scope_labels, results):
        for c in scope_result.containers:
            if c["name"] not in seen:
                seen[c["name"]] = c
        unit_states_by_scope[scope_label] = scope_result.unit_states
    containers = list(seen.values())
    return containers, unit_states_by_scope


def _build_unit_rows(unit_states_by_scope: dict) -> list[dict]:
    """Return the flattened unit rows for a stats_update payload."""
    return [
        {
            "unit": unit_name,
            "scope": scope_label,
            "load_state": state.get("load_state"),
            "active_state": state.get("active_state"),
            "sub_state": state.get("sub_state"),
            "n_restarts": state.get("n_restarts", 0),
        }
        for scope_label, unit_states in unit_states_by_scope.items()
        for unit_name, state in unit_states.items()
    ]


async def fetch_server_stats():
    """Polls all registered servers for Podman stats and pushes via SSE."""
    async with get_db_connection() as db:
        async with db.execute("SELECT id, name, scope_filter FROM servers") as cursor:
            servers = await cursor.fetchall()

    for server in servers:
        server_id = server[0]
        server_name = server[1]
        scope_filter = server[2] if len(server) > 2 else "both"
        try:
            # Fetch containers only for the scopes configured on this server.
            tasks, scope_labels = _scope_stat_tasks(server_id, scope_filter)

            results = await asyncio.gather(*tasks)
            containers, unit_states_by_scope = _merge_scope_results(scope_labels, results)

            units = _build_unit_rows(unit_states_by_scope)

            publisher.publish("stats_update", {
                "server_id": server_id,
                "server_name": server_name,
                "containers": containers,
                "units": units,
            })
            await _record_health_history(server_id, containers)
            await _record_unit_states(server_id, unit_states_by_scope)
            await _record_unit_events(server_id, unit_states_by_scope)

        except Exception as e:
            logger.exception(f"Error polling stats for server {server_id} ({server_name})")
            # Publish an error event so the frontend can show feedback
            # instead of forever displaying "Waiting for stats data..."
            publisher.publish("stats_error", {
                "server_id": server_id,
                "server_name": server_name,
                "error": str(e),
            })


async def stats_engine_loop():
    global _last_rollup_time
    logger.info("Starting Resource Stats polling background task.")
    try:
        while True:
            await asyncio.sleep(STATS_INTERVAL_SEC)
            try:
                await fetch_server_stats()
                now = time.time()
                if now - _last_rollup_time >= ROLLUP_INTERVAL_SEC:
                    await rollup_health_history()
                    _last_rollup_time = now
            except asyncio.CancelledError:
                raise  # Re-raise to exit the loop
            except Exception:
                logger.exception("Stats engine error")
    except asyncio.CancelledError:
        logger.info("Stats engine stopped.")
        raise
