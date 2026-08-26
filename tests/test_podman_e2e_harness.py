"""Verify `podman-e2e.sh test` is self-sufficient (see #374).

Today `cmd_test()` just shells out to `pytest -m podman` against whatever is
listening on the configured host and port. It never seeds a database and
never starts an app, so the browser journeys in tests/e2e/test_podman_e2e.py
fail as Playwright timeouts against a server that was never provisioned, not
as legible skips. These tests pin down two contracts a later fix must
satisfy:

* `cmd_test` must provision its own seeded app (via scripts/seed_test_db.py
  and uvicorn) whenever the caller has not already exported QM_APP_URL, so
  `./scripts/podman-e2e.sh test` works out of the box.
* The journeys themselves must be able to detect an unseeded host and skip
  with a legible message pointing at scripts/seed_test_db.py, rather than
  failing deep inside a UI assertion.
"""

import importlib
import os
import re

import pytest


def _podman_e2e_script_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "scripts", "podman-e2e.sh")


def _shell_function_body(name):
    """Return the body of the named shell function, from its opening brace
    line to the closing brace at column 0, so assertions can inspect just
    that function rather than the whole script."""
    path = _podman_e2e_script_path()
    with open(path, "r") as f:
        text = f.read()

    match = re.search(
        r"^%s\(\) \{\n(.*?)^\}\n" % re.escape(name), text, re.DOTALL | re.MULTILINE
    )
    assert match is not None, f"{name}() function not found in {path}"
    return match.group(1)


def _strip_comment_lines(body):
    return "\n".join(
        line for line in body.splitlines() if line.strip()[:1] != "#"
    )


def _cmd_test_provisioning_text():
    """Return the executable text of the provisioning path: cmd_test() and
    start_scratch_app() concatenated, with comment lines stripped.

    The assertions below are about what the script *does*, not about what it
    says about itself: a comment mentioning uvicorn is not a script that runs
    it, and leaving comments in would let the provisioning code be deleted
    while the test stayed green.
    """
    return _strip_comment_lines(
        _shell_function_body("cmd_test") + _shell_function_body("start_scratch_app")
    )


@pytest.mark.unit
def test_cmd_test_provisions_a_seeded_app():
    """cmd_test must seed a database and start its own app (via uvicorn),
    exposing the result as QM_APP_URL, rather than assuming something is
    already listening."""
    body = _cmd_test_provisioning_text()

    assert "scripts/seed_test_db.py" in body, (
        "cmd_test must invoke scripts/seed_test_db.py to seed a database"
    )
    assert "QM_SEED_PODMAN" in body, (
        "cmd_test must set QM_SEED_PODMAN so the seed script targets the podman host"
    )
    assert "uvicorn" in body, (
        "cmd_test must start its own app instance via uvicorn"
    )
    assert "QM_APP_URL" in body, (
        "cmd_test must export QM_APP_URL pointing at the app it provisioned"
    )


@pytest.mark.unit
def test_cmd_test_defers_to_an_explicit_app_url():
    """cmd_test must only provision an app when QM_APP_URL is not already
    set, so the documented manual path (exporting QM_APP_URL to point at a
    second instance) keeps working."""
    body = _strip_comment_lines(_shell_function_body("cmd_test"))

    assert "${QM_APP_URL:-}" in body, (
        "cmd_test must guard its provisioning on QM_APP_URL being unset "
        "(bash's ${QM_APP_URL:-} unset-or-empty test)"
    )


@pytest.mark.unit
def test_journeys_skip_when_the_podman_host_is_not_seeded(monkeypatch):
    """podman_ui must expose podman_host_is_seeded() and
    skip_unless_seeded() so a run against an unseeded host produces a
    legible pytest.skip pointing at scripts/seed_test_db.py, instead of a
    Playwright timeout deep inside a UI assertion."""
    podman_ui = importlib.import_module("tests.e2e.podman_ui")

    monkeypatch.setattr(podman_ui, "podman_host_is_seeded", lambda base_url: False)
    with pytest.raises(pytest.skip.Exception) as exc_info:
        podman_ui.skip_unless_seeded("http://localhost:8000")
    assert "scripts/seed_test_db.py" in str(exc_info.value), (
        "the skip message must point at scripts/seed_test_db.py so the "
        "caller knows how to fix it"
    )

    monkeypatch.setattr(podman_ui, "podman_host_is_seeded", lambda base_url: True)
    assert podman_ui.skip_unless_seeded("http://localhost:8000") is None, (
        "skip_unless_seeded must not skip when the host is already seeded"
    )
