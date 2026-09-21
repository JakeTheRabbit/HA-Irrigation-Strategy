"""The dashboard shows which integration and which controller are actually running.

Nothing in the dashboard carries a version number of its own, so there is no third place for a
release to forget. The integration publishes what Home Assistant loaded; the controller publishes
what it was built from (addons/f2_control/tests/test_versions.py). These pin the integration half;
tests_ha/test_versions.py checks the real descriptor entity against the manifest.
"""

from custom_components.crop_steering.room import build_engine_config

ARGS = ("", "default", 1, {"1": {"zone_switch": "switch.v1"}}, {}, {})


def test_the_descriptor_carries_the_version_it_is_given():
    assert (
        build_engine_config(*ARGS, integration_version="2.19.1")["integration_version"]
        == "2.19.1"
    )


def test_without_one_the_descriptor_is_exactly_what_it_was():
    assert "integration_version" not in build_engine_config(*ARGS)
    assert "integration_version" not in build_engine_config(
        *ARGS, integration_version=""
    )
