import configparser

class QuadletValidationError(Exception):
    pass

def validate_quadlet_syntax(content: str, quadlet_type: str = "container"):
    """Validate a Quadlet systemd unit file.

    Use of configparser here for systemd-flavored INI Quadlets.
    """
    # configparser requires a generic section header if none exists,
    # but Quadlets should always have standard systemd sections.
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    
    try:
        parser.read_string(content)
    except configparser.Error as e:
        raise QuadletValidationError(f"Invalid INI syntax: {e}")

    # Unit section is generally required conceptually
    if 'Unit' not in parser.sections():
        pass # Not strictly fatal, but recommended

    # Ensure the correct Quadlet section exists
    expected_section = quadlet_type.capitalize()
    if expected_section not in parser.sections():
        raise QuadletValidationError(f"Missing [{expected_section}] section for {quadlet_type} type.")

    # Validate specific requirements
    if quadlet_type == 'container' and 'Image' not in parser[expected_section]:
        raise QuadletValidationError("[Container] section must define an 'Image'.")

    return True
