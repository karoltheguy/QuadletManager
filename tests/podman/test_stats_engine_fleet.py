"""fetch_server_stats() against a fleet, not a single host.

Issue #369 item 2: an "Unreachable Host" row (valid ssh_key_id, dead port) is
what lets this module assert on a *real* stats_error frame instead of a
mocked exception. The invariant worth having is isolation: one pass over
`servers` must report each row independently, so a dead server's failure
cannot swallow or mislabel a live server's frame.

Depends on `podman_fleet`, a fixture tests/podman/conftest.py does not define
yet. Its expected contract: build on the same per-test isolated database as
`podman_server`, and return a mapping with at least "reachable" and
"unreachable", each holding that row's server_id.
"""

import pytest

from services.stats_engine import fetch_server_stats

pytestmark = pytest.mark.podman


@pytest.mark.timeout(300)
async def test_one_pass_reports_each_server_independently(podman_fleet, monkeypatch):
    published = []

    def _record(event, payload):
        published.append((event, payload))

    monkeypatch.setattr("services.stats_engine.publisher.publish", _record)

    await fetch_server_stats()

    reachable_id = podman_fleet["reachable"]
    unreachable_id = podman_fleet["unreachable"]

    stats_updates = [payload for event, payload in published if event == "stats_update"]
    stats_errors = [payload for event, payload in published if event == "stats_error"]

    reachable_updates = [p for p in stats_updates if p["server_id"] == reachable_id]
    unreachable_errors = [p for p in stats_errors if p["server_id"] == unreachable_id]

    assert len(reachable_updates) == 1, (
        f"expected exactly one stats_update for the reachable server, got {stats_updates}"
    )
    assert len(unreachable_errors) == 1, (
        f"expected exactly one stats_error for the unreachable server, got {stats_errors}"
    )

    # A dead server must not poison a live one's frame.
    reachable_errors = [p for p in stats_errors if p["server_id"] == reachable_id]
    unreachable_updates = [p for p in stats_updates if p["server_id"] == unreachable_id]
    assert reachable_errors == [], (
        f"reachable server published a stats_error too: {reachable_errors}"
    )
    assert unreachable_updates == [], (
        f"unreachable server published a stats_update too: {unreachable_updates}"
    )
