import unittest
from fastapi import HTTPException
import sys
import os
from unittest.mock import patch, AsyncMock, MagicMock

# Add parent directory to path to import routes
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestRBAC(unittest.IsolatedAsyncioTestCase):
    
    async def test_viewer_cannot_save(self):
        from api.routes import save_file
        
        role = "viewer"
        
        with self.assertRaises(HTTPException) as context:
            await save_file(
                request=MagicMock(),
                server_id=1,
                file_path="/fake/path",
                scope="user",
                unit_name="fake.service",
                content="data",
                role=role
            )
            
        self.assertEqual(context.exception.status_code, 403)
        msg = context.exception.detail
        self.assertTrue("cannot create files" in msg or "cannot save" in msg)

    @patch('api.routes.pool.execute_command', new_callable=AsyncMock)
    @patch('api.routes.reload_and_restart', new_callable=AsyncMock)
    @patch('api.routes.systemctl_action', new_callable=AsyncMock)
    async def test_editor_can_save(self, mock_systemctl, mock_reload, mock_execute):
        from api.routes import save_file
        
        role = "editor"
        mock_systemctl.return_value = "Active: active (running)"
        
        try:
            response = await save_file(
                request=MagicMock(),
                server_id=1,
                file_path="/fake/path",
                scope="user",
                unit_name="fake.service",
                content="data",
                role=role
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("Saved", response.body.decode())
        except HTTPException:
            self.fail("Editor role raised HTTPException unexpectedly")

    async def test_viewer_cannot_create(self):
        from api.routes import create_new_quadlet
        
        role = "viewer"
        
        with self.assertRaises(HTTPException) as context:
            await create_new_quadlet(
                request=MagicMock(),
                server_id=1,
                scope="user",
                type="container",
                name="test",
                role=role
            )
            
        self.assertEqual(context.exception.status_code, 403)
        self.assertIn("cannot create files", context.exception.detail)

    @patch('api.routes.get_db_connection', new_callable=AsyncMock)
    @patch('api.routes.pool.execute_command', new_callable=AsyncMock)
    async def test_editor_can_create(self, mock_execute, mock_db):
        from api.routes import create_new_quadlet
        from unittest.mock import MagicMock
        
        role = "editor"
        mock_cursor = AsyncMock()
        mock_cursor.fetchone.return_value = ("[Container]\n",)
        
        cursor_context_mock = AsyncMock()
        cursor_context_mock.__aenter__.return_value = mock_cursor
        
        conn_mock = AsyncMock()
        conn_mock.execute = MagicMock(return_value=cursor_context_mock)
        mock_db.return_value.__aenter__.return_value = conn_mock
        
        try:
            response = await create_new_quadlet(
                request=MagicMock(),
                server_id=1,
                scope="user",
                type="container",
                name="test",
                role=role
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("Created", response.body.decode())
        except HTTPException:
            self.fail("Editor role raised HTTPException unexpectedly")

    async def test_viewer_cannot_systemctl_post(self):
        from api.routes import api_systemctl_post
        
        role = "viewer"
        
        # viewer can check status (action="status")
        try:
            from fastapi.responses import HTMLResponse
            with patch('api.routes.systemctl_action', new_callable=AsyncMock) as mock_action:
                mock_action.return_value = "fake status"
                response = await api_systemctl_post(
                    server_id=1,
                    action="status",
                    unit="fake.service",
                    scope="user",
                    role=role
                )
                self.assertEqual(response.status_code, 200)
        except Exception as e:
            self.fail(f"Viewer role raised Exception unexpectedly on status: {e}")
            
        # viewer cannot start
        response_forbid = await api_systemctl_post(
            server_id=1,
            action="start",
            unit="fake.service",
            scope="user",
            role=role
        )
        self.assertEqual(response_forbid.status_code, 403)
        self.assertEqual(response_forbid.body.decode(), "Permission denied")

    @patch('api.routes.systemctl_action', new_callable=AsyncMock)
    async def test_editor_can_systemctl_post(self, mock_action):
        from api.routes import api_systemctl_post
        
        role = "editor"
        mock_action.return_value = "fake result"
        
        response = await api_systemctl_post(
            server_id=1,
            action="start",
            unit="fake.service",
            scope="user",
            role=role
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("fake result", response.body.decode())

if __name__ == "__main__":
    unittest.main()
