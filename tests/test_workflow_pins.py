"""The workflows run only code that is pinned, and the local CI script is honest about what it covers.

A third-party action named by a branch (`@master`, `@main`) or a moving tag (`@v4`) runs whatever its
author last pushed, so an upstream change can turn the gate red, or run new code on it, with no commit
here. Every `uses:` in .github/workflows is a full commit SHA with the release it stands for in a
trailing comment, which is how container.yml and promote.yml already did it. Dependabot moves them.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _uses():
    for path in WORKFLOWS:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            found = USES.match(line)
            if found and not found.group(1).startswith("./"):
                yield path.name, number, found.group(1), found.group(2)


def test_every_action_is_pinned_to_a_commit_with_its_release_named():
    loose = [
        f"{name}:{number} {action}{rest}"
        for name, number, action, rest in _uses()
        if not PINNED.match(action) or not re.match(r"^\s*#\s*\S", rest)
    ]
    assert (
        not loose
    ), "pin these to a full commit SHA followed by `# <release>`:\n" + "\n".join(loose)


def test_dependabot_keeps_the_pinned_actions_moving():
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: github-actions" in config


def test_the_local_ci_script_runs_the_doctrine_and_node_jobs_and_names_what_it_cannot_run():
    script = (ROOT / "tests" / "run_ci.sh").read_text(encoding="utf-8")
    for ran in (
        "build_doctrine.py --check",
        "vitest",
        "verify-",
        "mcp-server",
        "tests/container",
    ):
        assert ran in script, f"run_ci.sh no longer runs {ran}"
    assert "mirrors" not in script
    for ci_only in ("Hassfest", "HACS", "oldest supported", "aarch64"):
        assert ci_only in script, f"run_ci.sh does not say it skips {ci_only}"
