"""Every Rebuild of the controller installs the same library code.

The image's Python dependencies come from requirements.txt: `requests` and its whole closure, each
pinned to one exact version with the hashes of the files pip may take for it. An unpinned line
would let two boxes rebuilt on different days run different library code under one version
number, and pinning `requests` alone would leave its own dependencies floating. These tests fail if
a line loses its pin or its hashes, or if the Dockerfile stops installing the file in hash mode.
"""
import pathlib
import re

ADDON = pathlib.Path(__file__).parents[1]


def _requirements():
    """The file's requirement entries, continuation lines joined and comments dropped."""
    text = (ADDON / "requirements.txt").read_text()
    lines = (raw.split("#", 1)[0].strip() for raw in re.sub(r"\\\n", " ", text).splitlines())
    return [line.split() for line in lines if line]


def test_every_line_pins_one_exact_version_with_hashes():
    entries = _requirements()
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
