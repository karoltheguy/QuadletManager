"""Helpers for deriving names and unit types from Quadlet file names."""

# Quadlet types whose generated unit name is suffixed with the type, e.g.
# "web.pod" -> "web-pod.service". Verified against podman 5.8.4's generator.
SUFFIXED_QUADLET_TYPES = frozenset({"pod", "volume", "network", "image", "build"})


def base_name_of(name: str) -> str:
    """Return the base name of a Quadlet file name with its extension stripped.

    :param name: The Quadlet file name (or path), e.g. "web.container".
    :return: The name without its final extension, e.g. "web".
    """
    return name.rsplit('.', 1)[0] if '.' in name else name


def unit_name_for(name: str) -> str:
    """Return the systemd unit name corresponding to a Quadlet file name.

    Only container and kube units are unsuffixed; pod, volume, network,
    image, and build units have their type appended to the base name.

    :param name: The Quadlet file name (or path), e.g. "web.container".
    :return: The systemd service unit name, e.g. "web.service".
    """
    base_name = base_name_of(name)
    quadlet_type = quadlet_type_of(name)
    if quadlet_type in SUFFIXED_QUADLET_TYPES:
        return f"{base_name}-{quadlet_type}.service"
    return f"{base_name}.service"


def quadlet_type_of(name: str) -> str:
    """Return the lowercase Quadlet type derived from a file name's extension.

    :param name: The Quadlet file name (or path), e.g. "web.Container".
    :return: The lowercase extension, e.g. "container", or "" if there is no extension.
    """
    return name.rsplit('.', 1)[-1].lower() if '.' in name else ""
