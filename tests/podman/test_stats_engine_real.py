"""services/stats_engine.py against real podman output.

This module was entirely mocked before: the `podman ps --format json` shape, the
`_UNIT_STATE_SENTINEL` batching trick, and health extraction had never met real
output from podman 5.

IMPORTANT: why these tests insert `quadlets` rows by hand.

`_unit_names_for_scope` reads the **`quadlets` DB table**, not the remote host.
With that table empty it returns [], `_build_first_command` appends no systemctl
segment, `unit_states` comes back {} and every assertion about unit state passes
vacuously.

The plan for this suite said to call `sync_engine.check_quadlets()` first. That
does not work: check_quadlets only *polls* rows that already exist. The single
`INSERT INTO quadlets` in the whole repository lives in
tests/test_stats_engine_unit_state.py, and no production code ever writes that
table. So the rows are inserted here directly, the same way that test does it.
"""

import asyncio
import json

import aiosqlite
import pytest

from services.ssh_manager import pool
from services.stats_engine import (
    _UNIT_STATE_SENTINEL,
    _build_first_command,
    _build_podman_commands,
    _extract_name,
    _extract_single_container_health,
    _fetch_scope_stats,
    _parse_pct,
    _split_batched_output,
    _unit_names_for_scope,
    normalize_container_stats,
)
from services.systemd_manager import ROOTLESS_ENV_PREFIX, reload_and_restart
from tests.podman.conftest import install_fixture, wait_for_active_state

pytestmark = pytest.mark.podman

FIXTURE = "e2e-health.container"
UNIT = "e2e-health.service"
CONTAINER_NAME = "e2e-health"
SCOPE = "user"


async def _register_quadlet_row(db_path, server_id: int, file_path: str) -> None:
    """Make the quadlet visible to _unit_names_for_scope. See module docstring."""
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO quadlets (server_id, file_path, scope) VALUES (?, ?, ?)",
            (server_id, file_path, SCOPE),
        )
        await db.commit()


@pytest.fixture
async def running_health_container(podman_server, isolated_database):
    """Install, register and start the healthcheck fixture; yield its server_id."""
    path = await install_fixture(podman_server, SCOPE, FIXTURE)
    await _register_quadlet_row(isolated_database, podman_server, path)

    await reload_and_restart(podman_server, UNIT, scope=SCOPE)
    state = await wait_for_active_state(
        podman_server, UNIT, SCOPE, expected={"active", "failed"}
    )
    assert state == "active", f"{UNIT} did not start: {state}"
    return podman_server


@pytest.mark.timeout(300)
async def test_unit_names_come_from_the_database(running_health_container, isolated_database):
    """Guard the vacuity trap described in the module docstring."""
    names = await _unit_names_for_scope(running_health_container, SCOPE)
    assert names == [UNIT], (
        f"expected exactly {UNIT} from the quadlets table, got {names}. "
        "An empty list here makes every other assertion in this module vacuous."
    )


@pytest.mark.timeout(300)
async def test_sentinel_batching_round_trips_through_real_output(running_health_container):
    """The batching trick sends `podman ps; echo SENTINEL; systemctl show` as one
    SSH call and splits the reply. Both halves must survive real output."""
    ps_cmd, _ = _build_podman_commands(rootful=False)
    command = await _build_first_command(running_health_container, SCOPE, ps_cmd, rootful=False)
    assert _UNIT_STATE_SENTINEL in command, (
        "no systemctl segment was appended, so the quadlets table was empty"
    )

    raw = await pool.execute_command(running_health_container, command)
    ps_json_str, unit_states = _split_batched_output(raw)

    # Left half is still parseable JSON after the split.
    ps_data = json.loads(ps_json_str)
    assert isinstance(ps_data, list) and ps_data, "no containers in podman ps output"

    # Right half parsed into real systemd state.
    assert UNIT in unit_states, f"{UNIT} missing from {list(unit_states)}"
    assert unit_states[UNIT]["active_state"] == "active"
    assert unit_states[UNIT]["load_state"] == "loaded"


@pytest.mark.timeout(300)
async def test_extract_name_handles_podman_5_list_valued_names(running_health_container):
    """podman 5 returns Names as a *list*. _extract_name exists for that; this
    asserts against the real field rather than a hand-written fixture."""
    ps_cmd, _ = _build_podman_commands(rootful=False)
    raw = await pool.execute_command(running_health_container, ps_cmd)
    ps_data = json.loads(raw)

    names_fields = [entry.get("Names") for entry in ps_data]
    assert any(isinstance(field, list) for field in names_fields), (
        f"expected at least one list-valued Names from podman 5, got {names_fields}"
    )
    extracted = [_extract_name(field) for field in names_fields]
    assert CONTAINER_NAME in extracted, extracted


@pytest.mark.timeout(300)
async def test_health_is_extracted_from_real_healthcheck_output(running_health_container):
    """e2e-health.container declares a HealthCmd, so podman reports a health
    state. Poll: the first probe has not run yet at start, so the honest initial
    value is "starting"."""
    ps_cmd, _ = _build_podman_commands(rootful=False)

    seen = "(never)"
    for _ in range(30):
        ps_data = json.loads(await pool.execute_command(running_health_container, ps_cmd))
        for entry in ps_data:
            if _extract_name(entry.get("Names")) == CONTAINER_NAME:
                seen = _extract_single_container_health(entry)
                break
        if seen == "healthy":
            break
        await asyncio.sleep(2)

    assert seen == "healthy", (
        f"health never became healthy (last saw {seen!r}). HealthCmd is /bin/true "
        "with a 2s interval, so this should settle quickly."
    )


@pytest.mark.timeout(300)
async def test_fetch_scope_stats_returns_real_containers_and_unit_states(
    running_health_container,
):
    """The whole path end to end. _fetch_scope_stats swallows exceptions and
    returns an empty result, so asserting non-emptiness is what makes this test
    meaningful rather than merely green."""
    result = await _fetch_scope_stats(running_health_container, rootful=False)

    assert result.unit_states.get(UNIT, {}).get("active_state") == "active", (
        f"unit states missing or wrong: {result.unit_states}"
    )

    names = [container.get("name") for container in result.containers]
    assert CONTAINER_NAME in names, (
        f"{CONTAINER_NAME} absent from stats containers {names}. An empty list "
        "here usually means the podman stats call failed and was swallowed."
    )

    entry = next(c for c in result.containers if c.get("name") == CONTAINER_NAME)
    assert entry.get("health") in {"healthy", "starting"}, entry


@pytest.mark.timeout(300)
async def test_normalize_container_stats_accepts_real_podman_stats(running_health_container):
    """podman stats percentages come through as strings like "0.15%"; the
    normalizer has to cope with the real formatting, not a tidied fixture."""
    _, stats_prefix = _build_podman_commands(rootful=False)
    raw = await pool.execute_command(
        running_health_container,
        f"{stats_prefix} --no-stream --format json {CONTAINER_NAME}",
    )
    stats_data = json.loads(raw)
    assert stats_data, "podman stats returned nothing"

    normalized = normalize_container_stats(stats_data[0])
    assert normalized["name"] == CONTAINER_NAME
    # The normalizer only unifies key names across podman versions; the values
    # stay as podman formatted them ("0.15%"). _parse_pct is what makes them
    # numeric, and it is the piece that has to survive the real formatting.
    assert _parse_pct(normalized["cpu"]) >= 0.0
    assert _parse_pct(normalized["mem"]) >= 0.0
    for key in ("mem_usage", "net_io", "block_io", "pids"):
        assert key in normalized


@pytest.mark.timeout(300)
async def test_rootless_commands_carry_the_runtime_dir(running_health_container):
    """_build_podman_commands must prefix XDG_RUNTIME_DIR for the rootless
    scope, or the commands run against root's socket and silently see nothing."""
    ps_cmd, stats_prefix = _build_podman_commands(rootful=False)
    assert ps_cmd.startswith(ROOTLESS_ENV_PREFIX)
    assert stats_prefix.startswith(ROOTLESS_ENV_PREFIX)
