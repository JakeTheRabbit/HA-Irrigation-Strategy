"""Every text file in the repository ends its lines with LF, and .gitattributes keeps it that way.

A file whose line endings flip, CRLF to LF or back, turns every one of its lines into a diff and
hides the change that was meant.

A few files a box installs (or the release workflow) were stored with CRLF before this rule. Their
bytes are left alone until a change that ships them anyway converts them, so converting them never
rides in a change that ships nothing. That list only shrinks: no other file may end a line with CRLF.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = {
    ".cfg",
    ".conf",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
# Not the repository's own files: dependencies, builds, caches and local output.
SKIP = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "venv",
}
# Stored with CRLF before the rule; converted by the next change that ships them.
NOT_YET_CONVERTED = {
    ".github/workflows/release.yml",
    "addons/f2_control/f2_control/auto_setpoints.py",
    "addons/f2_control/f2_control/controller.py",
    "addons/f2_control/f2_control/crop_steering_engine/core.py",
    "addons/f2_control/f2_control/engine_twin.py",
    "crop-steering-engine/src/crop_steering_engine/core.py",
    "custom_components/crop_steering/const.py",
    "custom_components/crop_steering/env_parser.py",
    "custom_components/crop_steering/number.py",
    "custom_components/crop_steering/select.py",
    "custom_components/crop_steering/services.py",
    "custom_components/crop_steering/switch.py",
}


def _text_files():
    for path in ROOT.rglob("*"):
        parts = set(path.relative_to(ROOT).parts)
        if path.is_file() and path.suffix in TEXT and not parts & SKIP:
            yield path


def test_every_text_file_ends_its_lines_with_lf():
    crlf = {
        path.relative_to(ROOT).as_posix()
        for path in _text_files()
        if b"\r\n" in path.read_bytes()
    }
    assert sorted(crlf - NOT_YET_CONVERTED) == []


def test_git_stores_and_checks_out_text_as_lf():
    rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "* text=auto eol=lf" in rules
