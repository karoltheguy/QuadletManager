"""Tests for SSH key dropdown in Add Server form (issues #64, #86).

The Add Server form should accept an ssh_key_id referencing an existing key
rather than creating a new key inline. The dropdown must also be populated
whenever the Settings > Servers section becomes visible, not just on initial
page load (fixes the HTMX hidden-element timing bug reported in #86).
"""
import sys
import os
import pytest
from fastapi import HTTPException
from unittest.mock import patch, AsyncMock, MagicMock

try:
    from playwright.sync_api import Page, expect
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    import typing
    Page = typing.Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

BASE_URL = "http://localhost:8000"

# ── E2E: SSH key dropdown populated when navigating to Settings > Servers ──


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright not installed")
def test_ssh_key_dropdown_populated_on_settings_visit(page: Page):
    """After adding an SSH key, the dropdown in Settings > Servers must show
    that key when the user navigates to the Servers sub-section (issue #86)."""
    try:
        page.goto(BASE_URL + "/")
    except Exception:
        pytest.skip("Backend is not running — skipping E2E test.")

    # Navigate to Settings > SSH Keys and add a test key
    page.click("button.nav-item:has-text('Settings')")
    page.click(".settings-sidenav-item[data-section='ssh-keys']")
    page.fill("input[name='key_name']", "e2e-test-key")
    page.fill("textarea[name='private_key']", "-----BEGIN OPENSSH PRIVATE KEY-----\nfakekey\n-----END OPENSSH PRIVATE KEY-----")
    page.click("button[type='submit']:has-text('Add Key')")
    page.wait_for_timeout(500)

    # Navigate to the Servers sub-section
    page.click(".settings-sidenav-item[data-section='servers']")
    page.wait_for_timeout(500)

    # The SSH Key dropdown must contain the key we just added
    options = page.locator("select[name='ssh_key_id'] option").all_text_contents()
    assert any("e2e-test-key" in opt for opt in options), (
        f"Expected 'e2e-test-key' in SSH key dropdown options, got: {options}"
    )


class _AioDualMock:
    """Supports both `await db.execute(...)` and `async with db.execute(...) as cur:`."""
    def __init__(self, fetchone_result=None, fetchall_result=None):
        self._fetchone = fetchone_result
        self._fetchall = fetchall_result or []

    def __await__(self):
        async def _noop(): pass
        return _noop().__await__()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def fetchone(self):
        return self._fetchone

    async def fetchall(self):
        return self._fetchall


# =============================================================================
# GET /api/keys/options — returns <option> elements for SSH key dropdown
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_keys_options_returns_option_elements(mock_db):
    """GET /api/keys/options should return HTML <option> tags for each key."""
    from api.routes import api_keys_options

    _select = _AioDualMock(fetchall_result=[(1, "deploy-key"), (2, "prod-key")])

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_select)
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await api_keys_options(request=MagicMock())
    body = response.body.decode()
    assert '<option value="1">' in body
    assert "deploy-key" in body
    assert '<option value="2">' in body
    assert "prod-key" in body


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_keys_options_empty_when_no_keys(mock_db):
    """GET /api/keys/options with no keys returns only the placeholder option."""
    from api.routes import api_keys_options

    _select = _AioDualMock(fetchall_result=[])

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_select)
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await api_keys_options(request=MagicMock())
    body = response.body.decode()
    assert "No keys available" in body


# =============================================================================
# POST /api/settings/servers — now accepts ssh_key_id
# =============================================================================


@pytest.mark.asyncio
@patch('api.routes.settings_list_servers', new_callable=AsyncMock)
@patch('api.routes.get_db_connection')
async def test_add_server_with_ssh_key_id(mock_db, mock_list):
    """Adding a server with a valid ssh_key_id should succeed."""
    from fastapi.responses import HTMLResponse
    from api.routes import settings_add_server

    mock_list.return_value = HTMLResponse("<table></table>")

    _key_check = _AioDualMock(fetchone_result=(1,))  # key exists
    _insert = _AioDualMock()

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(side_effect=[_key_check, _insert])
    conn_mock.commit = AsyncMock()
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    response = await settings_add_server(
        request=MagicMock(),
        name="test-server",
        ip_address="10.0.0.1",
        ssh_user="root",
        ssh_key_id=1,
        scope_filter="both",
        role="editor",
        is_admin=True,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_add_server_with_invalid_key_id_returns_400(mock_db):
    """Adding a server with a non-existent ssh_key_id should return 400."""
    from api.routes import settings_add_server

    _key_check = _AioDualMock(fetchone_result=None)  # key does NOT exist

    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=_key_check)
    mock_db.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    mock_db.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(HTTPException) as exc_info:
        await settings_add_server(
            request=MagicMock(),
            name="bad-server",
            ip_address="10.0.0.2",
            ssh_user="root",
            ssh_key_id=999,
            scope_filter="both",
            role="editor",
            is_admin=True,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@patch('api.routes.get_db_connection')
async def test_add_server_non_admin_rejected(mock_db):
    """Non-admin users cannot add servers."""
    from api.routes import settings_add_server

    with pytest.raises(HTTPException) as exc_info:
        await settings_add_server(
            request=MagicMock(),
            name="test-server",
            ip_address="10.0.0.1",
            ssh_user="root",
            ssh_key_id=1,
            scope_filter="both",
            role="viewer",
            is_admin=False,
        )
    assert exc_info.value.status_code == 403
