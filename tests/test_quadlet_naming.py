import pytest

from services.quadlet_naming import base_name_of, unit_name_for, quadlet_type_of


@pytest.mark.unit
def test_base_name_of_strips_extension():
    assert base_name_of("web.container") == "web"


@pytest.mark.unit
def test_base_name_of_no_dot_unchanged():
    assert base_name_of("web") == "web"


@pytest.mark.unit
def test_base_name_of_only_splits_on_last_dot():
    assert base_name_of("my.app.container") == "my.app"


@pytest.mark.unit
def test_base_name_of_service_extension():
    assert base_name_of("web.service") == "web"


@pytest.mark.unit
def test_unit_name_for_container():
    assert unit_name_for("web.container") == "web.service"


@pytest.mark.unit
def test_unit_name_for_no_dot():
    assert unit_name_for("web") == "web.service"


@pytest.mark.unit
@pytest.mark.parametrize(
    "file_name,expected_unit",
    [
        ("probe.container", "probe.service"),
        ("probe.kube", "probe.service"),
        ("probe.pod", "probe-pod.service"),
        ("probe.volume", "probe-volume.service"),
        ("probe.network", "probe-network.service"),
        ("probe.image", "probe-image.service"),
        ("probe.build", "probe-build.service"),
        ("probe.conf", "probe.service"),
    ],
)
def test_unit_name_for_suffixes_by_quadlet_type(file_name, expected_unit):
    assert unit_name_for(file_name) == expected_unit


@pytest.mark.unit
def test_quadlet_type_of_lowercases_extension():
    assert quadlet_type_of("web.Container") == "container"


@pytest.mark.unit
def test_quadlet_type_of_lowercase_input():
    assert quadlet_type_of("web.container") == "container"


@pytest.mark.unit
def test_quadlet_type_of_no_extension_returns_empty_string():
    assert quadlet_type_of("noext") == ""


@pytest.mark.unit
def test_quadlet_type_of_accepts_full_path():
    assert quadlet_type_of("/etc/containers/systemd/web.container") == "container"
