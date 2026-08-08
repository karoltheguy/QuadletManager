"""Tests for pod-aware actions (issue #97).

#97's requirement still holds: a pod action must act on the whole pod, not
on a container that happens to share its name. The mechanism moved from
`podman pod {action} {name}` to systemctl (`systemctl {action} <base>-pod.service`)
because #334 made the pod's real generated unit name derivable via
`unit_name_for`, and because a never-started Quadlet pod has no `podman pod`
object for an ad-hoc `podman pod {action}` to act on: the pod object is only
created by the generated unit's own `ExecStartPre=podman pod create --replace`.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

MAIN_JS = os.path.join(os.path.dirname(__file__), '..', 'static', 'main.js')
EDITOR_PANE_HTML = os.path.join(os.path.dirname(__file__), '..', 'templates', 'partials', 'editor_pane.html')


def _read_js():
    with open(MAIN_JS, 'r') as f:
        return f.read()


def _read_editor():
    with open(EDITOR_PANE_HTML, 'r') as f:
        return f.read()


def _template_context(mock_template):
    call_args = mock_template.call_args[0]
    return call_args[2]


# =============================================================================
# Backend: fetch_file passes quadlet_type to template context
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_fetch_file_pod_passes_quadlet_type(mock_exec):
    """fetch_file must pass quadlet_type='pod' to the template for .pod files."""
    from api.routes import fetch_file

    mock_exec.return_value = "[Pod]\nNetwork=host\n"
    mock_request = MagicMock()

    with patch('api.routes.templates.TemplateResponse') as mock_template:
        mock_template.return_value = MagicMock()
        await fetch_file(
            request=mock_request,
            server_id=1,
            path='/etc/containers/systemd/kestra.pod',
            scope='global',
            name='kestra.pod',
            role='editor'
        )
        context = _template_context(mock_template)
        assert context.get('quadlet_type') == 'pod', \
            f"Expected quadlet_type='pod', got {context.get('quadlet_type')}"
        assert context.get('pod_name') == 'kestra', \
            f"Expected pod_name='kestra', got {context.get('pod_name')}"


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_fetch_file_container_passes_quadlet_type(mock_exec):
    """fetch_file must pass quadlet_type='container' for .container files."""
    from api.routes import fetch_file

    mock_exec.return_value = "[Container]\nImage=nginx:latest\n"
    mock_request = MagicMock()

    with patch('api.routes.templates.TemplateResponse') as mock_template:
        mock_template.return_value = MagicMock()
        await fetch_file(
            request=mock_request,
            server_id=1,
            path='/etc/containers/systemd/nginx.container',
            scope='global',
            name='nginx.container',
            role='editor'
        )
        context = _template_context(mock_template)
        assert context.get('quadlet_type') == 'container', \
            f"Expected quadlet_type='container', got {context.get('quadlet_type')}"
        assert context.get('pod_name') is None, \
            f"Expected pod_name=None for non-pod files, got {context.get('pod_name')}"


# =============================================================================
# Backend: pod-action route runs podman pod commands
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_pod_action_stop(mock_exec):
    """api_pod_action with action=stop must run `systemctl stop <base>-pod.service`."""
    from api.routes import api_pod_action

    mock_exec.return_value = "kestra pod stopped"
    mock_request = MagicMock()

    with patch('api.routes._get_session', new_callable=AsyncMock) as mock_session:
        mock_session.return_value = {"username": "editor_user"}
        with patch('api.routes.record_container_event', new_callable=AsyncMock):
            response = await api_pod_action(
                request=mock_request,
                server_id=1,
                action='stop',
                pod_name='kestra',
                scope='global',
                role='editor'
            )
            assert response.status_code == 200
            call_args = mock_exec.call_args[0][1]
            assert call_args == 'systemctl stop kestra-pod.service', \
                f"Expected 'systemctl stop kestra-pod.service', got '{call_args}'"


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_pod_action_start(mock_exec):
    """api_pod_action with action=start must run `systemctl start <base>-pod.service`."""
    from api.routes import api_pod_action

    mock_exec.return_value = "kestra pod started"
    mock_request = MagicMock()

    with patch('api.routes._get_session', new_callable=AsyncMock) as mock_session:
        mock_session.return_value = {"username": "editor_user"}
        with patch('api.routes.record_container_event', new_callable=AsyncMock):
            response = await api_pod_action(
                request=mock_request,
                server_id=1,
                action='start',
                pod_name='kestra',
                scope='global',
                role='editor'
            )
            assert response.status_code == 200
            call_args = mock_exec.call_args[0][1]
            assert call_args == 'systemctl start kestra-pod.service'


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_pod_action_restart(mock_exec):
    """api_pod_action with action=restart must run `systemctl restart <base>-pod.service`."""
    from api.routes import api_pod_action

    mock_exec.return_value = "kestra pod restarted"
    mock_request = MagicMock()

    with patch('api.routes._get_session', new_callable=AsyncMock) as mock_session:
        mock_session.return_value = {"username": "editor_user"}
        with patch('api.routes.record_container_event', new_callable=AsyncMock):
            response = await api_pod_action(
                request=mock_request,
                server_id=1,
                action='restart',
                pod_name='kestra',
                scope='global',
                role='editor'
            )
            assert response.status_code == 200
            call_args = mock_exec.call_args[0][1]
            assert call_args == 'systemctl restart kestra-pod.service'


@pytest.mark.asyncio
@pytest.mark.unit
async def test_pod_action_viewer_forbidden():
    """Viewers must be forbidden from pod actions (start/stop/restart)."""
    from api.routes import api_pod_action

    mock_request = MagicMock()
    response = await api_pod_action(
        request=mock_request,
        server_id=1,
        action='stop',
        pod_name='kestra',
        scope='global',
        role='viewer'
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.unit
async def test_pod_action_rejects_invalid_action():
    """Only start/stop/restart are valid pod actions."""
    from api.routes import api_pod_action

    mock_request = MagicMock()
    response = await api_pod_action(
        request=mock_request,
        server_id=1,
        action='status',
        pod_name='kestra',
        scope='global',
        role='editor'
    )
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.unit
async def test_pod_action_invalid_action_escapes_html():
    """Reflecting an invalid action back to the client must escape HTML (CWE-79)."""
    from api.routes import api_pod_action

    mock_request = MagicMock()
    malicious_action = '<script>alert(1)</script>'
    response = await api_pod_action(
        request=mock_request,
        server_id=1,
        action=malicious_action,
        pod_name='kestra',
        scope='global',
        role='editor'
    )
    assert response.status_code == 400
    body = response.body.decode()
    assert '<script>' not in body, \
        f"Response must not reflect raw <script> tag, got: {body}"
    assert '&lt;script&gt;' in body, \
        f"Expected escaped script tag in response, got: {body}"


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_pod_action_user_scope_no_sudo(mock_exec):
    """User scope pod actions must NOT use sudo, and must use `systemctl --user`."""
    from api.routes import api_pod_action
    from services.systemd_manager import ROOTLESS_ENV_PREFIX

    mock_exec.return_value = "ok"
    mock_request = MagicMock()

    with patch('api.routes._get_session', new_callable=AsyncMock) as mock_session:
        mock_session.return_value = {"username": "editor_user"}
        with patch('api.routes.record_container_event', new_callable=AsyncMock):
            await api_pod_action(
                request=mock_request,
                server_id=1,
                action='stop',
                pod_name='kestra',
                scope='user',
                role='editor'
            )
            call_args = mock_exec.call_args[0][1]
            call_kwargs = mock_exec.call_args[1]
            assert call_args == f'{ROOTLESS_ENV_PREFIX} systemctl --user stop kestra-pod.service'
            assert call_kwargs.get('use_sudo') is False, \
                f"User scope must NOT use sudo, got use_sudo={call_kwargs.get('use_sudo')}"


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_pod_action_global_scope_uses_sudo(mock_exec):
    """Global scope pod actions must use sudo, and must use plain `systemctl`."""
    from api.routes import api_pod_action

    mock_exec.return_value = "ok"
    mock_request = MagicMock()

    with patch('api.routes._get_session', new_callable=AsyncMock) as mock_session:
        mock_session.return_value = {"username": "editor_user"}
        with patch('api.routes.record_container_event', new_callable=AsyncMock):
            await api_pod_action(
                request=mock_request,
                server_id=1,
                action='stop',
                pod_name='kestra',
                scope='global',
                role='editor'
            )
            call_args = mock_exec.call_args[0][1]
            call_kwargs = mock_exec.call_args[1]
            assert call_args == 'systemctl stop kestra-pod.service'
            assert call_kwargs.get('use_sudo') is True, \
                f"Global scope must use sudo, got use_sudo={call_kwargs.get('use_sudo')}"


@pytest.mark.asyncio
@patch('api.routes.pool.execute_command', new_callable=AsyncMock)
@pytest.mark.unit
async def test_pod_action_records_event(mock_exec):
    """Pod actions must record a container event like systemctl actions do."""
    from api.routes import api_pod_action

    mock_exec.return_value = "ok"
    mock_request = MagicMock()

    with patch('api.routes._get_session', new_callable=AsyncMock) as mock_session:
        mock_session.return_value = {"username": "editor_user"}
        with patch('api.routes.record_container_event', new_callable=AsyncMock) as mock_record:
            await api_pod_action(
                request=mock_request,
                server_id=1,
                action='stop',
                pod_name='kestra',
                scope='global',
                role='editor'
            )
            mock_record.assert_called_once_with(1, 'kestra', 'stop', triggered_by='editor_user')


# =============================================================================
# Frontend: editor_pane.html uses pod-action for .pod quadlets
# =============================================================================


@pytest.mark.unit
def test_editor_pane_has_pod_action_endpoint():
    """The editor pane must reference the /api/pod-action endpoint for pod quadlets."""
    html = _read_editor()
    assert '/api/pod-action/' in html, \
        "Editor pane must contain /api/pod-action/ endpoint for pod quadlets"


@pytest.mark.unit
def test_editor_pane_conditional_pod_actions():
    """The editor pane must conditionally render pod actions vs systemctl actions."""
    html = _read_editor()
    assert 'quadlet_type' in html, \
        "Editor pane must reference quadlet_type for conditional rendering"


# =============================================================================
# Frontend: context menu routes .pod files to pod-action
# =============================================================================


@pytest.mark.unit
def test_context_menu_detects_pod_extension():
    """The JS context menu must detect .pod file extension."""
    js = _read_js()
    assert "pod-action" in js, \
        "Context menu must route .pod files to /api/pod-action endpoint"


@pytest.mark.unit
def test_context_menu_preserves_systemctl_for_non_pod():
    """Non-.pod files must still use systemctl endpoint."""
    js = _read_js()
    assert '/api/systemctl/' in js, \
        "Non-pod files must still use /api/systemctl/ endpoint"
