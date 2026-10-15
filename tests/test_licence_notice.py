"""The licence keeps the notice of the MIT code this project carries over from elsewhere.

MIT lets that code be used here only while its copyright line travels with it, so the line
sits in `LICENSE`, under the same grant, before any of that code lands. This catches an edit
that drops it again.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWN = "Copyright (c) 2026 JakeTheRabbit"
GRANT = "Permission is hereby granted, free of charge, to any person obtaining a copy"


def _lines():
    return (ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()


def test_the_licence_is_mit_with_a_single_grant():
    lines = _lines()
    assert lines[0] == "MIT License"
    assert lines.count(GRANT) == 1


def test_the_licence_keeps_the_carried_over_copyright_line():
    lines = _lines()
    holders = [line for line in lines if line.startswith("Copyright (c) ")]
    assert OWN in holders
    others = [line for line in holders if line != OWN]
    assert others, "the copyright line of the carried-over MIT code is missing"
    # Every holder sits above the one grant, so the grant covers them all.
    assert all(lines.index(line) < lines.index(GRANT) for line in holders)
