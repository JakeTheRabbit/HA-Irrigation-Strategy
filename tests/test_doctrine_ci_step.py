"""The Validate workflow's doctrine step does what doctrine/README.md says it does.

The step's own shell is read from .github/workflows/ci-validate.yml and run here against
this repository, with the environment GitHub would give it on each kind of run: a pull
request from this repository with the secret missing fails loud, a fork or Dependabot pull
request passes on the public patterns and reports the skip, and a run with the secret hands
it to the word-list matcher. Every private list here is made up at run time.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import string
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="the step is a bash script")


def _step() -> dict:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci-validate.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["lint-and-validate"]["steps"]
    return next(s for s in steps if s.get("name", "").startswith("Doctrine pack"))


def _run(tmp_path: Path, denylist: str, no_secrets: str):
    summary = tmp_path / "summary.md"
    env = {k: v for k, v in os.environ.items() if k != "DOCTRINE_PRIVATE_DENYLIST"}
    env |= {
        "DENYLIST": denylist,
        "NO_SECRETS": no_secrets,
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    r = subprocess.run(
        [BASH, "-e", "-c", _step()["run"]],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=300,
    )
    return r, summary.read_text(encoding="utf-8") if summary.exists() else ""


def test_the_step_reads_the_secret_and_knows_which_runs_have_none():
    env = _step()["env"]
    assert env["DENYLIST"] == "${{ secrets.DOCTRINE_DENYLIST }}"
    no_secrets = env["NO_SECRETS"]
    assert "github.event_name == 'pull_request'" in no_secrets
    assert (
        "github.event.pull_request.head.repo.full_name != github.repository"
        in no_secrets
    )
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in no_secrets


def test_the_step_checks_against_the_engine_and_the_old_doctrine_explicitly():
    run = _step()["run"]
    assert "--check" in run
    assert "--core crop-steering-engine/src/crop_steering_engine/core.py" in run
    assert "--jev addons/f2_control/f2_control/brain/doctrine.py" in run
    assert "--controller-copy" not in run  # derived, and checked whenever it exists


def test_a_same_repository_run_with_no_secret_fails_loud(tmp_path):
    r, _ = _run(tmp_path, denylist="", no_secrets="false")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "private denylist secret missing" in r.stdout


def test_a_fork_or_dependabot_run_passes_on_the_public_patterns_and_says_so(tmp_path):
    r, summary = _run(tmp_path, denylist="", no_secrets="true")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "(private list skipped)" in r.stdout
    assert "SKIPPED private denylist: pull request with no secrets" in summary


def test_a_run_with_the_secret_runs_the_private_list(tmp_path):
    token = "".join(random.choices(string.ascii_lowercase, k=16))
    r, summary = _run(tmp_path, json.dumps([[token, "canary"]]), no_secrets="false")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIPPED" not in r.stderr + summary
    assert "OK: rules valid" in r.stdout
    assert "(private list skipped)" not in r.stdout

    # A list entry that matches the pack proves the secret reaches the matcher.
    r, _ = _run(tmp_path, json.dumps([["dryback", "canary"]]), no_secrets="false")
    assert r.returncode == 1
    assert ": a word on the private denylist" in r.stdout
    # The secret's entries never reach the log.
    assert "canary" not in r.stdout + r.stderr
