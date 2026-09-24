"""Promotion refuses unsafe candidates before its first GitHub mutation."""

import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / ".github/scripts/promotion.py"
spec = importlib.util.spec_from_file_location("promotion", SCRIPT)
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)

TAG, OLD, CANDIDATE = "v2.19.2", "a" * 40, "b" * 40
REPO = "example/HA-Irrigation-Strategy"
EVIDENCE = b"# Release rehearsal\nThe owner approved this recorded rehearsal scope.\n"


class FakeGitHub(promotion.GitHub):
    def __init__(self):
        super().__init__(REPO)
        self.calls = []
        self.main_sha = OLD
        self.staging_sha = CANDIDATE
        self.tag_sha = CANDIDATE
        self.version = TAG[1:]
        self.compare_status = "ahead"
        self.fail_flip = False
        self.audit = {
            "schema_version": 1,
            "tag": TAG,
            "candidate_sha": CANDIDATE,
            "verdict": "ready",
            "approval": {
                "approved_by": "Repository owner",
                "approved_at": "2026-09-21T10:00:00Z",
                "basis": "approved-rehearsal",
                "evidence_asset": f"release-audit-{TAG}.md",
                "evidence_sha256": hashlib.sha256(EVIDENCE).hexdigest(),
            },
        }
        self.run = {
            "id": 12,
            "workflow_id": 34,
            "name": "Validate",
            "path": promotion.VALIDATE,
            "head_sha": CANDIDATE,
            "head_branch": "testing",
            "head_repository": {"full_name": REPO},
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_number": 50,
            "run_attempt": 1,
            "updated_at": "2026-09-21T10:00:00Z",
        }
        self.runs = [self.run]
        self.jobs = [
            {
                "id": number,
                "name": name,
                "head_sha": CANDIDATE,
                "status": "completed",
                "conclusion": "success",
            }
            for number, name in enumerate(sorted(promotion.REQUIRED_JOBS), 100)
        ]
        self.release = {"id": 56, "tag_name": TAG, "prerelease": True, "draft": False}
        self.missing_audit = False
        self.on_request = None

    def request(self, path, *, method="GET", payload=None, raw=False):
        self.calls.append((method, path, deepcopy(payload)))
        if self.on_request:
            self.on_request(self, path)
        if method != "GET":
            if path == "git/refs/heads/main":
                assert payload == {"sha": CANDIDATE, "force": False}
                self.main_sha = payload["sha"]
                return {"object": {"sha": self.main_sha}}
            assert path == "releases/56"
            assert self.main_sha == CANDIDATE, "Release must never flip before main"
            if self.fail_flip:
                raise promotion.Rejected("release API failed")
            self.release.update(payload)
            return deepcopy(self.release)
        if path == "":
            return {"full_name": REPO, "default_branch": "main"}
        refs = {
            "git/ref/heads/main": ("heads/main", self.main_sha),
            "git/ref/heads/testing": ("heads/testing", self.staging_sha),
            f"git/ref/tags/{TAG}": (f"tags/{TAG}", self.tag_sha),
        }
        if path in refs:
            name, sha = refs[path]
            return {"ref": f"refs/{name}", "object": {"type": "commit", "sha": sha}}
        if path.startswith("contents/"):
            return {
                "encoding": "base64",
                "content": base64.b64encode(
                    json.dumps({"version": self.version}).encode()
                ).decode(),
            }
        if path.startswith("compare/"):
            return {"status": self.compare_status}
        if path == "actions/workflows/ci-validate.yml":
            return {"id": 34, "name": "Validate", "path": promotion.VALIDATE}
        if path.startswith("actions/workflows/34/runs?"):
            assert f"head_sha={CANDIDATE}" in path
            return {"workflow_runs": deepcopy(self.runs)}
        if path.startswith("actions/runs/") and "/jobs?" in path:
            return {"total_count": len(self.jobs), "jobs": deepcopy(self.jobs)}
        if path == f"releases/tags/{TAG}":
            release = deepcopy(self.release)
            release["assets"] = [
                {
                    "id": 1,
                    "name": f"promotion-audit-{TAG}.json",
                    "state": "uploaded",
                    "size": len(json.dumps(self.audit).encode()),
                },
                {
                    "id": 2,
                    "name": f"release-audit-{TAG}.md",
                    "state": "uploaded",
                    "size": len(EVIDENCE),
                },
            ]
            if self.missing_audit:
                release["assets"].pop(0)
            return release
        if path == "releases/assets/1":
            assert raw
            return json.dumps(self.audit).encode()
        if path == "releases/assets/2":
            assert raw
            return EVIDENCE
        raise AssertionError(f"Unexpected request {method} {path}")

    @property
    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]


def test_default_is_complete_read_only_preflight():
    api = FakeGitHub()
    plan = promotion.promote(api, TAG)
    assert plan["candidate_sha"] == CANDIDATE
    assert plan["validate_run_id"] == 12
    assert plan["approved_by"] == "Repository owner"
    assert not api.writes


@pytest.mark.parametrize(
    "tag",
    ["v2.19.2; echo injected", "2.19.2", "--help", "v2.19.2/other", "v2.19.2-rc1"],
)
def test_invalid_tag_is_rejected_before_any_api_call(tag):
    api = FakeGitHub()
    with pytest.raises(promotion.Rejected, match="plain integration tag"):
        promotion.promote(api, tag, apply=True)
    assert not api.calls


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda api: setattr(api, "version", "2.19.1"), "manifest version"),
        (lambda api: setattr(api, "staging_sha", "c" * 40), "testing must still point"),
        (lambda api: setattr(api, "compare_status", "diverged"), "fast-forward"),
        (lambda api: api.run.update(head_sha=OLD), "exact candidate SHA"),
        (
            lambda api: api.run.update(conclusion="failure"),
            "not completed successfully",
        ),
        (
            lambda api: api.run.update(status="in_progress"),
            "not completed successfully",
        ),
        (lambda api: api.run.update(workflow_id=99), "No Validate workflow"),
        (
            lambda api: api.run.update(path=".github/workflows/other.yml"),
            "No Validate workflow",
        ),
        (lambda api: api.run.update(event="pull_request"), "No Validate workflow"),
        (
            lambda api: api.run.update(head_repository={"full_name": "attacker/fork"}),
            "No Validate workflow",
        ),
        (lambda api: setattr(api, "missing_audit", True), "audit asset"),
        (lambda api: api.audit.update(verdict="not-ready"), "verdict"),
        (lambda api: api.audit.update(candidate_sha=OLD), "Audit tag/SHA"),
        (
            lambda api: api.audit["approval"].update(approved_by=""),
            "approving person's name",
        ),
        (
            lambda api: api.audit["approval"].update(basis="tests-passed"),
            "Approval basis",
        ),
        (lambda api: api.audit["approval"].update(evidence_sha256="0" * 64), "SHA256"),
        (lambda api: api.release.update(prerelease=False), "published pre-release"),
        (lambda api: api.release.update(draft=True), "published pre-release"),
    ],
)
def test_failed_gate_never_writes(mutate, message):
    api = FakeGitHub()
    mutate(api)
    with pytest.raises(promotion.Rejected, match=message):
        promotion.promote(api, TAG, apply=True)
    assert not api.writes


def test_new_failed_attempt_invalidates_old_green_validate():
    api = FakeGitHub()
    api.runs.append({**api.run, "run_attempt": 2, "conclusion": "failure"})
    with pytest.raises(promotion.Rejected, match="not completed successfully"):
        promotion.promote(api, TAG)
    assert not api.writes


@pytest.mark.parametrize(
    "status,conclusion", [("completed", "failure"), ("in_progress", None)]
)
def test_recent_rerun_of_older_run_supersedes_newer_run_number(status, conclusion):
    api = FakeGitHub()
    api.runs.append(
        {
            **api.run,
            "id": 11,
            "run_number": 49,
            "run_attempt": 2,
            "updated_at": "2026-09-21T11:00:00Z",
            "status": status,
            "conclusion": conclusion,
        }
    )
    with pytest.raises(promotion.Rejected, match="not completed successfully"):
        promotion.promote(api, TAG, apply=True)
    assert not api.writes


@pytest.mark.parametrize("conclusion", ["skipped", "failure", "neutral"])
def test_green_workflow_cannot_hide_a_required_job_that_did_not_pass(conclusion):
    api = FakeGitHub()
    api.jobs[0]["conclusion"] = conclusion
    with pytest.raises(promotion.Rejected, match="Required Validate job"):
        promotion.promote(api, TAG, apply=True)
    assert not api.writes


def test_missing_required_job_rejects_green_workflow():
    api = FakeGitHub()
    api.jobs.pop()
    with pytest.raises(promotion.Rejected, match="Required Validate job"):
        promotion.promote(api, TAG, apply=True)
    assert not api.writes


def test_apply_needs_prior_read_only_plan_and_trusted_context(monkeypatch):
    api = FakeGitHub()
    with pytest.raises(promotion.Rejected, match="read-only preflight"):
        promotion.promote(api, TAG, apply=True)
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(promotion.Rejected, match="dispatched from main"):
        promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert not api.writes


def test_changed_main_or_audit_invalidates_preflight(monkeypatch):
    api = FakeGitHub()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    api.main_sha = "d" * 40
    monkeypatch.setattr(promotion, "require_trusted_context", lambda _: None)
    with pytest.raises(promotion.Rejected, match="changed since"):
        promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert not api.writes


def test_final_recheck_blocks_a_moving_candidate(monkeypatch):
    api = FakeGitHub()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))

    def trusted_context(_):
        api.staging_sha = "c" * 40

    monkeypatch.setattr(promotion, "require_trusted_context", trusted_context)
    with pytest.raises(promotion.Rejected, match="testing must still point"):
        promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert not api.writes


def test_promotion_writes_only_after_every_gate_then_publishes(monkeypatch):
    api = FakeGitHub()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    monkeypatch.setattr(promotion, "require_trusted_context", lambda _: None)
    plan = promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert plan["candidate_sha"] == api.main_sha == CANDIDATE
    assert [call[1] for call in api.writes] == ["git/refs/heads/main", "releases/56"]
    assert api.writes[-1][2] == {
        "prerelease": False,
        "name": TAG.removeprefix("v"),
        "make_latest": "true",  # the promoted release is GitHub's current one, in the same write
    }
    first_write = next(i for i, call in enumerate(api.calls) if call[0] != "GET")
    assert sum(call[1] == "releases/assets/2" for call in api.calls[:first_write]) == 3


def test_release_flip_failure_is_visible_and_retry_does_not_rewrite_main(monkeypatch):
    api = FakeGitHub()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    monkeypatch.setattr(promotion, "require_trusted_context", lambda _: None)
    api.fail_flip = True
    with pytest.raises(
        promotion.Rejected, match="main is already promoted.*Do not rewind main"
    ):
        promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert api.main_sha == CANDIDATE and api.release["prerelease"]
    api.fail_flip = False
    api.calls.clear()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert [call[1] for call in api.writes] == ["releases/56"]


def test_ref_update_rejection_never_flips_the_release(monkeypatch):
    api = FakeGitHub()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    monkeypatch.setattr(promotion, "require_trusted_context", lambda _: None)

    def reject_main(_, path):
        if path == "git/refs/heads/main":
            raise promotion.Rejected("GitHub rejected the fast-forward")

    api.on_request = reject_main
    with pytest.raises(promotion.Rejected, match="rejected the fast-forward"):
        promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert api.main_sha == OLD
    assert [call[1] for call in api.writes] == ["git/refs/heads/main"]
    assert api.release["prerelease"]


def test_lost_release_response_and_successful_promotion_can_be_retried(monkeypatch):
    api = FakeGitHub()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    monkeypatch.setattr(promotion, "require_trusted_context", lambda _: None)

    def lose_response(_, path):
        if path == "releases/56":
            api.release["prerelease"] = (
                False  # GitHub performed the requested mutation.
            )
            raise promotion.Rejected("connection lost before PATCH response")

    api.on_request = lose_response
    with pytest.raises(promotion.Rejected, match="main is already promoted"):
        promotion.promote(api, TAG, apply=True, expected_digest=digest)
    api.on_request = None
    api.calls.clear()
    digest = promotion.plan_digest(promotion.preflight(api, TAG))
    plan = promotion.promote(api, TAG, apply=True, expected_digest=digest)
    assert plan["candidate_sha"] == api.main_sha == CANDIDATE
    assert not plan["release_prerelease"]
    assert not api.writes


@pytest.mark.parametrize(
    "ref,head,dirty",
    [
        ("refs/heads/testing", OLD, ""),
        ("refs/heads/main", CANDIDATE, ""),
        ("refs/heads/main", OLD, " M .github/scripts/promotion.py"),
    ],
)
def test_writing_requires_clean_current_main_checkout(monkeypatch, ref, head, dirty):
    plan = promotion.preflight(FakeGitHub(), TAG)
    for name, value in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": ref,
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_SHA": OLD,
        "GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/promote.yml@refs/heads/main",
    }.items():
        monkeypatch.setenv(name, value)

    def git(command, **_):
        return SimpleNamespace(stdout=head if command[1] == "rev-parse" else dirty)

    monkeypatch.setattr(promotion.subprocess, "run", git)
    with pytest.raises(promotion.Rejected):
        promotion.require_trusted_context(plan)


def test_api_transport_uses_get_for_reads_and_exact_repository_endpoint(monkeypatch):
    commands = []

    def gh(command, **_):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(promotion.subprocess, "run", gh)
    promotion.GitHub(REPO).request("")
    assert commands[0][:5] == ["gh", "api", "--method", "GET", f"repos/{REPO}"]


def test_validate_is_triggered_by_staging_push():
    import yaml

    # BaseLoader keeps GitHub's YAML key "on" as a string under YAML 1.1 parsers.
    workflow = yaml.load(
        (ROOT / promotion.VALIDATE).read_text(), Loader=yaml.BaseLoader
    )
    assert "testing" in workflow["on"]["push"]["branches"]


def test_workflow_uses_main_code_and_does_not_execute_candidate():
    workflow = (ROOT / ".github/workflows/promote.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "default: true" in workflow
    assert 'test "$DISPATCH_REF" = refs/heads/main' in workflow
    assert workflow.count("ref: ${{ github.sha }}") == 2
    assert workflow.count("persist-credentials: false") == 2
    assert "needs: preflight" in workflow
    assert "PROMOTION_DIGEST: ${{ needs.preflight.outputs.digest }}" in workflow
    assert "contents: write" not in workflow.split("  promote:")[0]
    for forbidden in (
        "pip ",
        "npm ",
        "pytest ",
        "git checkout",
        "ref: ${{ inputs",
        "run: ${{",
    ):
        assert forbidden not in workflow
