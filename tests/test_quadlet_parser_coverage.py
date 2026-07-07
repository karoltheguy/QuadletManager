"""Covers the invalid-INI-syntax branch in services/quadlet_parser.py."""
import pytest

from services.quadlet_parser import validate_quadlet_syntax, QuadletValidationError


@pytest.mark.unit
def test_invalid_ini_syntax_raises():
    """Content that is not valid INI (no section header) is rejected."""
    content = "key = value without any section header\n"
    with pytest.raises(QuadletValidationError) as excinfo:
        validate_quadlet_syntax(content, "container")
    assert "Invalid INI syntax" in str(excinfo.value)
