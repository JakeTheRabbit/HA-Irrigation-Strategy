"""The controller image builds the same with or without the Supervisor, and stays the app's image.

The Supervisor builds the app from this directory with build.yaml's base for each architecture. A
plain `docker build` (or the root docker-compose.yml) has no Supervisor to pass that base, so the
Dockerfile carries build.yaml's amd64 base as its default; these tests keep the two equal, so the
container and the app never drift onto different bases. The image also carries the licence (a copy
of the root LICENSE, since the build context is this directory), and run.sh starts the dashboard's
listener, which has no login of its own, everywhere except a standalone container that has not asked
for it, so an app whose Supervisor has not yet applied F2_RUNTIME keeps its dashboard.
"""
import os
import pathlib
import re
import subprocess

import pytest
import yaml

ADDON = pathlib.Path(__file__).parents[1]
ROOT = ADDON.parents[1]


def test_the_default_base_is_build_yamls_amd64_base():
    dockerfile = (ADDON / "Dockerfile").read_text()
    build = yaml.safe_load((ADDON / "build.yaml").read_text())
    default = re.search(r"^ARG BUILD_FROM=(\S+)$", dockerfile, re.M)
    assert default, "the Dockerfile has no default BUILD_FROM"
    assert default.group(1) == build["build_from"]["amd64"]
    assert re.search(r"^FROM \$\{BUILD_FROM\}$", dockerfile, re.M)


def test_the_licence_copy_is_the_root_licence_and_ships_in_the_image():
    assert (ADDON / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert re.search(r"^COPY LICENSE /app/LICENSE$", (ADDON / "Dockerfile").read_text(), re.M)
    assert "LICENSE" not in (ADDON / ".dockerignore").read_text()  # or the COPY has nothing to copy


def test_the_app_tells_the_process_it_is_the_app_and_nothing_else():
    config = yaml.safe_load((ADDON / "config.yaml").read_text())
    assert config["environment"] == {"F2_RUNTIME": "addon"}


def test_the_compose_file_builds_this_image_and_stops_inside_its_grace():
    service = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"][
        "crop-steering-controller"
    ]
    assert service["build"]["context"] == "addons/f2_control"
    env = service["environment"]
    assert env["F2_RUNTIME"] == "container"
    grace = int(re.fullmatch(r"(\d+)s", service["stop_grace_period"]).group(1))
    assert grace == 90
    assert grace >= float(env["F2_STOP_BUDGET_S"]) + 5
    assert service["stop_signal"] == "SIGTERM"
    # the image's own init must be PID 1, and the dashboard's port stays off the network
    assert "init" not in service and "network_mode" not in service and "ports" not in service


GATE_CASES = [
    # (environment, nginx started)
    ({"F2_RUNTIME": "addon", "SUPERVISOR_TOKEN": "t"}, True),  # what the Supervisor gives the app
    ({"SUPERVISOR_TOKEN": "t"}, True),  # an app whose Supervisor has not applied `environment:`
    ({"F2_RUNTIME": "addon"}, True),
    ({}, True),
    ({"F2_RUNTIME": "container", "HA_URL": "http://ha:8123"}, False),  # what compose gives it
    ({"F2_RUNTIME": "container", "SUPERVISOR_TOKEN": "t"}, False),
    ({"F2_RUNTIME": "container", "F2_SERVE_UI": "1"}, True),
]


@pytest.mark.skipif(os.name == "nt", reason="runs run.sh with stub executables (POSIX only)")
@pytest.mark.parametrize("env,started", GATE_CASES)
def test_run_sh_keeps_the_dashboard_listener_off_only_in_a_container(tmp_path, env, started):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("nginx", f"touch {tmp_path}/nginx-started"), ("python3", "exit 0")):
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    script = (ADDON / "run.sh").read_text().replace("\r\n", "\n")
    run_env = {"PATH": f"{bin_dir}:/usr/bin:/bin", **env}
    result = subprocess.run(
        ["bash", "-c", script], env=run_env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "nginx-started").exists() is started
