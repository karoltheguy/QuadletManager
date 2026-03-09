import unittest
from quadlet_parser import validate_quadlet_syntax, QuadletValidationError

class TestQuadletParser(unittest.TestCase):
    def test_valid_container(self):
        content = "[Container]\\nImage=nginx:latest\\nNetwork=host\\n"
        self.assertTrue(validate_quadlet_syntax(content, "container"))

    def test_missing_image(self):
        content = "[Container]\\nNetwork=host\\n"
        with self.assertRaises(QuadletValidationError) as context:
            validate_quadlet_syntax(content, "container")
        self.assertIn("must define an 'Image'", str(context.exception))

    def test_invalid_type(self):
        content = "[Container]\\nImage=nginx:latest\\n"
        # Type is network, but file only has [Container]
        with self.assertRaises(QuadletValidationError):
            validate_quadlet_syntax(content, "network")

if __name__ == "__main__":
    unittest.main()
