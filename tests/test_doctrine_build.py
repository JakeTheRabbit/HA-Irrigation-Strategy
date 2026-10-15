"""The doctrine pack (doctrine/) is current, and its strip lint stops what it must.

The pack is data nothing reads yet; its build checks it against the code it describes
(doctrine/README.md). These tests run that build: once over the committed pack, and on a
throwaway copy of it with something planted, to prove each lint layer fails the build.
Every planted value is made up at run time, so no committed file holds one.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import string
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path("tools") / "build_doctrine.py"


def _run(pack: Path, *args: str, env: dict | None = None):
    clean = {k: v for k, v in os.environ.items() if k != "DOCTRINE_PRIVATE_DENYLIST"}
    return subprocess.run(
        [sys.executable, str(pack / BUILD), *args],
        capture_output=True,
        text=True,
        env={**clean, **(env or {})},
        cwd=ROOT,
        timeout=300,
    )


def _made_up(n: int = 12) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def _digits(n: int) -> str:
    return "".join(random.choices("123456789", k=n))


@pytest.fixture
def pack(tmp_path):
    """A copy of the pack, built against this repository's code. Its controller copy
    points at a directory that does not exist, so a write run touches nothing here."""
    copy = tmp_path / "doctrine"
    shutil.copytree(
        ROOT / "doctrine", copy, ignore=shutil.ignore_patterns("__pycache__")
    )
    return copy


def _build(pack: Path, *args: str, env: dict | None = None):
    no_copy = str(pack.parent / "no-controller-copy")
    no_board = str(pack.parent / "no-dashboard" / "generated" / "arcs.json")
    return _run(
        pack,
        "--repo",
        str(ROOT),
        "--controller-copy",
        no_copy,
        "--dashboard-arcs",
        no_board,
        *args,
        env=env,
    )


def _plant(pack: Path, words: str) -> None:
    path = pack / "doctrine.rules.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rules"][0]["text"] += " " + words
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _private_list(tmp_path: Path, token: str) -> str:
    path = tmp_path / "private-denylist.json"
    path.write_text(json.dumps([[token, "canary"]]), encoding="utf-8")
    return str(path)


def test_committed_pack_is_current_and_clean():
    # The doctrine CI step always runs the private list from a secret. Here it runs only
    # where one is set, because the general test job and a contributor's machine hold none.
    private = os.environ.get("DOCTRINE_PRIVATE_DENYLIST")
    if private:
        flag = ["--private-denylist", private]
    else:
        flag = ["--private-skip", "no private denylist in this test run"]
    r = _run(ROOT / "doctrine", "--check", *flag)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: rules valid" in r.stdout


def test_private_word_list_fails_the_build_on_a_planted_word(pack, tmp_path):
    token = _made_up()
    denylist = _private_list(tmp_path, token)
    clean = _build(pack, "--private-denylist", denylist)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    _plant(pack, token)
    r = _build(pack, "--private-denylist", denylist)
    assert r.returncode == 1
    assert "doctrine.rules.json:" in r.stdout and "04-doctrine-rules.md:" in r.stdout
    assert r.stdout.count(": a word on the private denylist") >= 2
    # The list is a secret, so the log never shows the word or the entry's reason.
    assert token not in r.stdout + r.stderr and "canary" not in r.stdout + r.stderr


@pytest.mark.parametrize(
    "planted, why",
    [
        (
            lambda: f"+{_digits(2)} {_digits(2)} {_digits(3)} {_digits(4)}",
            "phone number",
        ),
        (lambda: random.choice("FGKR") + random.choice("123456789"), "site room id"),
    ],
    ids=["phone-number", "room-id"],
)
def test_public_patterns_fail_the_build_with_no_secret(pack, planted, why):
    value = planted()
    _plant(pack, f"(see {value})")
    r = _build(pack, "--private-skip", "fork pull request: no secrets")
    assert r.returncode == 1
    assert any(
        line.startswith(f"doctrine.rules.json: {why}") and line.endswith(f"'{value}'")
        for line in r.stdout.splitlines()
    ), r.stdout


def test_missing_private_list_fails_loud(pack):
    r = _build(pack)
    assert r.returncode == 1
    assert "private denylist secret missing" in r.stdout


def test_skipping_the_private_list_is_reported(pack):
    r = _build(pack, "--private-skip", "fork pull request: no secrets")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIPPED private denylist: fork pull request: no secrets" in r.stderr
    assert "(private list skipped)" in r.stdout


def test_an_audit_snapshot_inside_the_pack_fails(pack):
    (pack / "vendor-snapshot").mkdir()
    r = _build(pack, "--private-skip", "test")
    assert r.returncode == 1
    assert "vendor-snapshot/ is inside the pack" in r.stdout


def test_check_fails_when_a_generated_file_is_stale(pack):
    _plant(pack, "An extra sentence.")
    r = _build(pack, "--check", "--private-skip", "test")
    assert r.returncode == 1
    assert "stale generated file: 04-doctrine-rules.md" in r.stdout


def _one_byte_off(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[-2] = ord("x") if data[-2] != ord("x") else ord("y")
    path.write_bytes(bytes(data))


def test_check_fails_when_the_controllers_arc_copy_is_one_byte_off(pack, tmp_path):
    copy = tmp_path / "controller-copy"
    shutil.copytree(ROOT / "addons/f2_control/f2_control/doctrine", copy)
    args = ("--check", "--private-skip", "test", "--controller-copy", str(copy))
    assert _run(pack, "--repo", str(ROOT), *args).returncode == 0
    _one_byte_off(copy / "arcs" / "slab_default.md")
    r = _run(pack, "--repo", str(ROOT), *args)
    assert r.returncode == 1
    assert "controller doctrine copy differs: arcs/slab_default.md" in r.stdout


def test_check_fails_when_the_dashboards_arc_copy_is_one_byte_off(pack, tmp_path):
    board = tmp_path / "frontend" / "generated" / "arcs.json"
    board.parent.mkdir(parents=True)
    shutil.copy(ROOT / "frontend/src/lib/generated/arcs.json", board)
    args = ("--check", "--private-skip", "test", "--dashboard-arcs", str(board))
    assert _run(pack, "--repo", str(ROOT), *args).returncode == 0
    _one_byte_off(board)
    r = _run(pack, "--repo", str(ROOT), *args)
    assert r.returncode == 1
    assert "dashboard arcs differ" in r.stdout
