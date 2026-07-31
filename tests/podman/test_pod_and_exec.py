"""Pod actions, the exec PTY, and the log stream, against a real podman host.

`.pod` quadlets are a podman 5 feature and `POST /api/pod-action/{id}` shells
out to `podman pod {action} {name}`; neither had live coverage.

Note the unit name. `services/quadlet_naming.unit_name_for` maps every quadlet
to `<base>.service`, but podman only names *containers* that way: a `.pod`
generates `<base>-pod.service`, and likewise `-volume` / `-network`. These tests
use the real generated name, which is why POD_UNIT is spelled out rather than
derived.

On the event loop: the async helpers here open pool connections on the test's
loop, while TestClient runs the app on its own. `pool.close_all()` is called
between the two so neither reuses an asyncssh connection bound to the other's
loop.
"""

import json

import pytest
from fastapi.testclient import TestClient

import api.routes as api_routes
from main import app
from services.remote_fs import is_global_scope
from services.ssh_manager import pool
from services.systemd_manager import ROOTLESS_ENV_PREFIX, reload_and_restart
from tests.podman.conftest import install_fixture, wait_for_active_state

pytestmark = pytest.mark.podman

POD_FIXTURE = "e2e-test.pod"
POD_UNIT = "e2e-test-pod.service"  # not e2e-test.service; see module docstring
POD_NAME = "e2e-test"

SLEEP_FIXTURE = "e2e-sleep.container"
SLEEP_UNIT = "e2e-sleep.service"
SLEEP_CONTAINER = "e2e-sleep"

SCOPE = "user"


def _podman(scope: str) -> str:
    return "" if is_global_scope(scope) else f"{ROOTLESS_ENV_PREFIX} "


async def _pod_state(server_id: int, scope: str) -> str:
    """Status of our pod according to podman, or "(absent)"."""
    raw = await pool.execute_command(
        server_id,
        f"{_podman(scope)}podman pod ps --format json",
        use_sudo=is_global_scope(scope),
    )
    for pod in json.loads(raw or "[]"):
        if pod.get("Name") == POD_NAME:
            return str(pod.get("Status", "")).lower()
    return "(absent)"


def _editor_client() -> TestClient:
    """A TestClient carrying a valid editor session cookie.

    pod-action returns 403 for any role other than editor, and reads
    session["username"] to record the container event.
    """
    client = TestClient(app)
    cookie = api_routes._create_session_cookie("alice", "editor", is_admin=False)
    client.cookies.set(api_routes.COOKIE_NAME, cookie)
    return client


@pytest.fixture
async def running_pod(podman_server):
    """Install and start the .pod quadlet; yield its server_id."""
    await install_fixture(podman_server, SCOPE, POD_FIXTURE)
    await reload_and_restart(podman_server, POD_UNIT, scope=SCOPE)
    state = await wait_for_active_state(
        podman_server, POD_UNIT, SCOPE, expected={"active", "failed"}
    )
    assert state == "active", f"{POD_UNIT} did not start: {state}"
    return podman_server


@pytest.fixture
async def running_sleep_container(podman_server):
    """Install and start the long-running container; yield its server_id."""
    await install_fixture(podman_server, SCOPE, SLEEP_FIXTURE)
    await reload_and_restart(podman_server, SLEEP_UNIT, scope=SCOPE)
    state = await wait_for_active_state(
        podman_server, SLEEP_UNIT, SCOPE, expected={"active", "failed"}
    )
    assert state == "active", f"{SLEEP_UNIT} did not start: {state}"
    return podman_server


@pytest.mark.timeout(300)
async def test_pod_quadlet_creates_a_real_pod(running_pod):
    """Guards the podman-5 premise: .pod quadlets do not exist on 4.x."""
    assert "running" in await _pod_state(running_pod, SCOPE)


@pytest.mark.timeout(300)
async def test_pod_action_route_stops_a_quadlet_managed_pod(running_pod):
    """POST /api/pod-action/{id} builds `podman pod {action} {name}` and runs it.

    Asserted against podman's own view of the pod, not the route's response
    body, so a route that returns 200 while doing nothing still fails.

    Only `stop` is exercised against a quadlet-managed pod. Stopping it makes
    the systemd unit go inactive, and the generated unit's ExecStopPost then
    removes the pod outright, so a follow-up `start` would find nothing.
    That is podman/systemd behaving correctly, not a bug, which is why `start`
    is covered separately against an ad-hoc pod below.
    """
    server_id = running_pod
    await pool.close_all()  # hand the connection over to the app's loop

    with _editor_client() as client:
        stop = client.post(
            f"/api/pod-action/{server_id}",
            params={"action": "stop", "pod_name": POD_NAME, "scope": SCOPE},
        )
        assert stop.status_code == 200, stop.text

    await pool.close_all()
    assert "running" not in await _pod_state(server_id, SCOPE)


@pytest.mark.timeout(300)
async def test_pod_action_route_starts_a_stopped_pod(podman_server):
    """`start` against a pod that exists but is stopped.

    Uses a pod created directly rather than through a quadlet, so systemd does
    not clean it up between the stop and the start. Removed in a finally: the
    conftest teardown only sweeps quadlet *files*, so a pod created here is
    this test's own responsibility.
    """
    server_id = podman_server
    adhoc = "e2e-adhoc-pod"

    await pool.execute_command(
        server_id, f"{_podman(SCOPE)}podman pod create --name {adhoc}", use_sudo=False
    )
    try:
        await pool.close_all()
        with _editor_client() as client:
            started = client.post(
                f"/api/pod-action/{server_id}",
                params={"action": "start", "pod_name": adhoc, "scope": SCOPE},
            )
            assert started.status_code == 200, started.text

        await pool.close_all()
        raw = await pool.execute_command(
            server_id, f"{_podman(SCOPE)}podman pod ps --format json", use_sudo=False
        )
        state = next(
            (p.get("Status", "").lower() for p in json.loads(raw or "[]") if p.get("Name") == adhoc),
            "(absent)",
        )
        assert "running" in state, f"{adhoc} was {state!r} after the route's start"
    finally:
        await pool.close_all()
        await pool.execute_command(
            server_id, f"{_podman(SCOPE)}podman pod rm -f {adhoc}", use_sudo=False
        )


@pytest.mark.timeout(300)
async def test_pod_action_rejects_unknown_actions(running_pod):
    """The action allowlist is what keeps this route from being a shell."""
    await pool.close_all()
    with _editor_client() as client:
        response = client.post(
            f"/api/pod-action/{running_pod}",
            params={"action": "rm -rf /", "pod_name": POD_NAME, "scope": SCOPE},
        )
    assert response.status_code == 400


@pytest.mark.timeout(300)
async def test_log_websocket_streams_real_journal_output(running_sleep_container):
    """/ws/logs runs `journalctl --user -u <unit> -f` over the SSH connection.

    The unit really has journal entries, so this exercises the streaming path
    rather than a mocked process.
    """
    server_id = running_sleep_container
    await pool.close_all()

    with _editor_client() as client:
        with client.websocket_connect(
            f"/ws/logs/{server_id}/{SLEEP_UNIT}?scope={SCOPE}"
        ) as websocket:
            received = websocket.receive_text()

    assert received, "no output from the log stream"
    assert "error: invalid unit name" not in received


@pytest.mark.timeout(300)
async def test_log_websocket_rejects_a_malformed_unit_name(running_sleep_container):
    """The unit name goes into a shell command, so the regex guard matters.

    No slash in the payload: a `/` would add path segments and the route would
    simply not match, which tests routing rather than the guard.
    """
    await pool.close_all()
    with _editor_client() as client:
        with client.websocket_connect(
            f"/ws/logs/{running_sleep_container}/bad;whoami?scope={SCOPE}"
        ) as websocket:
            assert "invalid unit name" in websocket.receive_text()


@pytest.mark.timeout(300)
async def test_exec_websocket_runs_a_command_in_a_real_container(running_sleep_container):
    """/ws/exec attaches a PTY to `podman exec`. cmd=sh, because the busybox
    test image has no bash and the route defaults to bash."""
    server_id = running_sleep_container
    await pool.close_all()

    marker = "QM_EXEC_MARKER"
    with _editor_client() as client:
        with client.websocket_connect(
            f"/ws/exec/{server_id}/{SLEEP_CONTAINER}?scope={SCOPE}&cmd=sh"
        ) as websocket:
            websocket.send_text(f"echo {marker}\n")
            # PTY output arrives as *binary* frames (the handler creates the
            # process with encoding=None and uses send_bytes), while the
            # process-exited notice is text. Read frames generically so either
            # kind is tolerated.
            #
            # A PTY also echoes the input back before the output arrives, hence
            # waiting for the marker twice rather than asserting on frame one.
            transcript = ""
            for _ in range(20):
                frame = websocket.receive()
                chunk = frame.get("text") or frame.get("bytes") or b""
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("utf-8", "replace")
                transcript += chunk
                if transcript.count(marker) >= 2:
                    break

    assert transcript.count(marker) >= 2, (
        f"expected the echoed command and its output, got: {transcript!r}"
    )
