"""Every Rebuild of the controller installs the same library code.

The image's Python dependencies come from requirements.txt: `requests` and its whole closure, each
pinned to one exact version with the hashes of the files pip may take for it. An unpinned line
would let two boxes rebuilt on different days run different library code under one version
number, and pinning `requests` alone would leave its own dependencies floating. These tests fail if
a line loses its pin or its hashes, or if the Dockerfile stops installing the file in hash mode.
"""
import pathlib
import re

import pytest

ADDON = pathlib.Path(__file__).parents[1]


def _requirements(name="requirements.txt"):
    """The file's requirement entries, continuation lines joined and comments dropped."""
    text = (ADDON / name).read_text()
    lines = (raw.split("#", 1)[0].strip() for raw in re.sub(r"\\\n", " ", text).splitlines())
    return [line.split() for line in lines if line]


@pytest.mark.parametrize("name", ["requirements.txt", "requirements-brain.txt"])
def test_every_line_pins_one_exact_version_with_hashes(name):
    entries = _requirements(name)
    assert entries
    for spec, *options in entries:
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!-]+", spec), spec
        assert options, f"{spec} has no --hash"
        for option in options:
            assert re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", option), f"{spec}: {option}"


def test_it_names_requests_once():
    names = [spec.split("==")[0].lower() for spec, *_ in _requirements()]
    assert names.count("requests") == 1
    assert len(names) == len(set(names))


def test_the_dockerfile_installs_it_in_hash_mode_and_nothing_else():
    dockerfile = (ADDON / "Dockerfile").read_text()
    assert "COPY requirements.txt /tmp/requirements.txt" in dockerfile
    installs = [line for line in dockerfile.splitlines() if re.search(r"\bpip3? install\b", line)]
    assert installs[0] == (
        "RUN PIP_CONFIG_FILE=/dev/null pip3 install --no-cache-dir --require-hashes"
        " -r /tmp/requirements.txt && rm /tmp/requirements.txt"
    )
    # the one other install is the AI assistant's SDK, from requirements-brain.txt
    assert len(installs) == 2 and "-r /tmp/requirements-brain.txt;" in installs[1]
    assert dockerfile.index("COPY requirements.txt") < dockerfile.index("--require-hashes")
    assert "requirements" not in (ADDON / ".dockerignore").read_text()  # or the COPY has nothing to copy


# The Anthropic SDK for the optional AI assistant, and its whole closure, live in a second file
# (requirements-brain.txt) installed by a second RUN that armv7 skips by name.
BRAIN_RUN = (
    'RUN if [ "$BUILD_ARCH" = "armv7" ]; then'
    ' echo "anthropic SDK skipped on armv7: the brain runs rules on this device";'
    " else PIP_CONFIG_FILE=/dev/null pip3 install --no-cache-dir --require-hashes"
    " -r /tmp/requirements-brain.txt; fi && rm /tmp/requirements-brain.txt"
)


def _pins(name):
    """{normalised package name: (pin, sorted hashes)} for one requirements file."""
    pins = {}
    for spec, *options in _requirements(name):
        package, version = spec.split("==")
        pins[re.sub(r"[-_.]+", "-", package.lower())] = (version, sorted(options))
    return pins


def test_the_brain_file_names_anthropic_once():
    names = [spec.split("==")[0].lower() for spec, *_ in _requirements("requirements-brain.txt")]
    assert names.count("anthropic") == 1
    assert len(names) == len(set(names))
    assert "requests" not in names  # requests comes from requirements.txt alone


def test_a_package_in_both_files_has_one_pin_and_one_hash_set():
    """The second install never changes what the first installed."""
    base, brain = _pins("requirements.txt"), _pins("requirements-brain.txt")
    shared = base.keys() & brain.keys()
    for package in shared:
        assert brain[package] == base[package], package


def test_the_dockerfile_installs_the_brain_file_in_hash_mode_except_on_armv7():
    dockerfile = (ADDON / "Dockerfile").read_text()
    lines = dockerfile.splitlines()
    assert lines.count(BRAIN_RUN) == 1
    order = [
        lines.index("FROM ${BUILD_FROM}"),  # an ARG declared before FROM is not visible after it
        lines.index("RUN PIP_CONFIG_FILE=/dev/null pip3 install --no-cache-dir --require-hashes"
                    " -r /tmp/requirements.txt && rm /tmp/requirements.txt"),
        lines.index("ARG BUILD_ARCH"),
        lines.index("COPY requirements-brain.txt /tmp/requirements-brain.txt"),
        lines.index(BRAIN_RUN),
    ]
    assert order == sorted(order)
    # the install sits in the branch that runs when the arch is not armv7
    skip, install = BRAIN_RUN.split("; else ", 1)
    assert "pip3" not in skip and "--require-hashes -r /tmp/requirements-brain.txt" in install
