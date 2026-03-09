import unittest
from fastapi import HTTPException
import sys
import os

# Add parent directory to path to import routes
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockRequest:
    pass

class TestRBAC(unittest.IsolatedAsyncioTestCase):
    
    async def test_viewer_cannot_save(self):
        from routes import save_file
        
        request = MockRequest()
        role = "viewer"
        
        with self.assertRaises(HTTPException) as context:
            await save_file(request, role=role)
            
        self.assertEqual(context.exception.status_code, 403)
        self.assertIn("Viewer role cannot save", context.exception.detail)

    async def test_editor_can_save(self):
        from routes import save_file
        
        request = MockRequest()
        role = "editor"
        
        try:
            response = await save_file(request, role=role)
            self.assertEqual(response.status_code, 200)
        except HTTPException:
            self.fail("Editor role raised HTTPException unexpectedly")

if __name__ == "__main__":
    unittest.main()
