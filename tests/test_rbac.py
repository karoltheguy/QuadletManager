import unittest
from fastapi import HTTPException
import sys
import os
from unittest.mock import patch, AsyncMock

# Add parent directory to path to import routes
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestRBAC(unittest.IsolatedAsyncioTestCase):
    
    async def test_viewer_cannot_save(self):
        from routes import save_file
        
        role = "viewer"
        
        with self.assertRaises(HTTPException) as context:
            await save_file(
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

    @patch('routes.pool.execute_command', new_callable=AsyncMock)
    @patch('routes.reload_and_restart', new_callable=AsyncMock)
    @patch('routes.systemctl_action', new_callable=AsyncMock)
    async def test_editor_can_save(self, mock_systemctl, mock_reload, mock_execute):
        from routes import save_file
        
        role = "editor"
        mock_systemctl.return_value = "Active: active (running)"
        
        try:
            response = await save_file(
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

if __name__ == "__main__":
    unittest.main()
