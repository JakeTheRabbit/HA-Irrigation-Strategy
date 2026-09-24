"""Read-only candidate preflight; the main-only workflow may then promote that exact plan.

Candidate files and release assets are data only. No candidate checkout, imports, build,
dependency installation or shell execution occurs, including with the write-capable token.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlencode

PRODUCTION, STAGING = "main", "testing"
MANIFEST = "custom_components/crop_steering/manifest.json"
VALIDATE = ".github/workflows/ci-validate.yml"
REQUIRED_JOBS = {
    "Lint (ruff/black/yamllint) and HA validations (3.11)",
    "Lint (ruff/black/yamllint) and HA validations (3.12)",
    "Build f2-control add-on image (amd64)",
    "Real Home Assistant (setup wizard and entity ids)",
    "Dashboard build and browser workflows",
    "MCP protocol and reviewed configuration workflows",
}
SHA = re.compile(r"[0-9a-f]{40}")


class Rejected(RuntimeError):
    """No promotion is permitted, or a partial promotion needs attention."""


def require(condition, message):
    if not condition:
        raise Rejected(message)


class GitHub:
    def __init__(self, repository):
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository),
            "Repository must be owner/name.",
        )
        self.repository = repository

    def request(self, path, *, method="GET", payload=None, raw=False):
        command = [
            "gh",
            "api",
            "--method",
            method,
            f"repos/{self.repository}/{path}".rstrip("/"),
            "-H",
            (
                "Accept: application/octet-stream"
                if raw
                else "Accept: application/vnd.github+json"
            ),
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
        ]
        if payload is not None:
            command.extend(["--input", "-"])
        result = subprocess.run(
            command,
            input=json.dumps(payload).encode() if payload is not None else None,
            capture_output=True,
            check=False,
        )
        require(
            result.returncode == 0,
            f"GitHub {method} {path} failed: {result.stderr.decode().strip()}",
        )
        return result.stdout if raw else json.loads(result.stdout)

    def ref(self, name):
        ref = self.request(f"git/ref/{name}")
        require(
            ref.get("ref") == f"refs/{name}",
            f"Ref lookup did not return exactly {name}.",
        )
        return ref["object"]

    def candidate(self, tag):
        obj = self.ref(f"tags/{tag}")
        tag_object = obj["sha"]
        for _ in range(5):
            if obj["type"] == "commit":
                require(
                    SHA.fullmatch(obj["sha"]), "Candidate is not a full commit SHA."
                )
                return obj["sha"], tag_object
            require(obj["type"] == "tag", "Candidate tag does not resolve to a commit.")
            obj = self.request(f"git/tags/{obj['sha']}")["object"]
        raise Rejected("Candidate tag is nested too deeply.")

    def asset(self, release, name):
        matches = [
            asset for asset in release.get("assets", []) if asset["name"] == name
        ]
        require(len(matches) == 1, f"Release needs exactly one {name} audit asset.")
        asset = matches[0]
        require(
            asset.get("state") == "uploaded" and 0 < asset["size"] <= 1_000_000,
            f"Audit asset {name} is incomplete, empty or too large.",
        )
        body = self.request(f"releases/assets/{asset['id']}", raw=True)
        require(
            len(body) == asset["size"], f"Audit asset {name} changed while being read."
        )
        return body


def validate_run(runs, *, workflow_id, candidate, repository):
    """A green unrelated workflow, PR merge SHA or stale attempt cannot satisfy Validate."""
    matching = [
        run
        for run in runs
        if (
            run.get("workflow_id") == workflow_id
            and run.get("name") == "Validate"
            and run.get("path", "").split("@")[0] == VALIDATE
            and run.get("head_sha") == candidate
            and run.get("head_branch") == STAGING
            and run.get("head_repository", {}).get("full_name") == repository
            and run.get("event") in {"push", "workflow_dispatch"}
        )
    ]
    require(
        matching,
        "No Validate workflow run exists for the exact candidate SHA on testing.",
    )
    require(
        all(run.get("status") == "completed" for run in matching),
        "An exact-candidate Validate run is not completed successfully; wait for every active run.",
    )
    # A rerun retains its run_number. A recently rerun older run must supersede an older
    # success with a larger run_number; GitHub timestamps each run's latest update.
    require(
        all(run.get("updated_at") for run in matching),
        "Validate run is missing its update timestamp.",
    )
    latest = max(
        matching,
        key=lambda run: (
            run["updated_at"],
            run["run_number"],
            run.get("run_attempt", 1),
        ),
    )
    require(
        latest.get("status") == "completed" and latest.get("conclusion") == "success",
        "The latest exact-candidate Validate run is not completed successfully.",
    )
    return latest


def validate_jobs(result, *, candidate):
    jobs = result.get("jobs", [])
    require(result.get("total_count") == len(jobs), "Validate job list is incomplete.")
    for name in REQUIRED_JOBS:
        matches = [job for job in jobs if job.get("name") == name]
        require(
            len(matches) == 1
            and matches[0].get("head_sha") == candidate
            and matches[0].get("status") == "completed"
            and matches[0].get("conclusion") == "success",
            f"Required Validate job did not pass for the candidate: {name}",
        )
    return {job["name"]: job["id"] for job in jobs if job["name"] in REQUIRED_JOBS}


def validate_audit(audit, *, tag, candidate, evidence):
    require(
        isinstance(audit, dict) and audit.get("schema_version") == 1,
        "Audit schema_version must be 1.",
    )
    require(
        audit.get("tag") == tag and audit.get("candidate_sha") == candidate,
        "Audit tag/SHA does not match the exact candidate.",
    )
    require(audit.get("verdict") == "ready", "Audit verdict must explicitly be ready.")
    approval = audit.get("approval")
    require(
        isinstance(approval, dict),
        "Audit needs explicit approval and rehearsal/soak evidence.",
    )
    require(
        isinstance(approval.get("approved_by"), str)
        and approval["approved_by"].strip(),
        "Audit needs the approving person's name.",
    )
    require(
        isinstance(approval.get("approved_at"), str),
        "Audit needs an approved_at timestamp.",
    )
    try:
        approved_at = datetime.fromisoformat(
            approval.get("approved_at", "").replace("Z", "+00:00")
        )
        require(approved_at.utcoffset() is not None, "Approval time needs a timezone.")
    except (TypeError, ValueError):
        raise Rejected(
            "Audit needs an ISO 8601 approved_at timestamp with timezone."
        ) from None
    require(
        approval.get("basis") in {"staging-soak", "approved-rehearsal"},
        "Approval basis must be staging-soak or explicitly approved-rehearsal.",
    )
    require(
        approval.get("evidence_asset") == f"release-audit-{tag}.md",
        "Audit must name this version's release-audit markdown asset.",
    )
    require(
        evidence.strip()
        and approval.get("evidence_sha256") == hashlib.sha256(evidence).hexdigest(),
        "Rehearsal/soak evidence is empty or its SHA256 does not match the approval.",
    )
    return approval


def preflight(api, tag):
    """GET requests only. Return an immutable plan binding every promotion gate."""
    require(
        re.fullmatch(r"v\d+\.\d+\.\d+", tag),
        "Candidate must be a plain integration tag vX.Y.Z.",
    )
    repository = api.request("")
    require(
        repository.get("full_name") == api.repository
        and repository.get("default_branch") == PRODUCTION
        and not repository.get("archived")
        and not repository.get("disabled"),
        "Repository must be active and use main as its production/default branch.",
    )
    main = api.ref(f"heads/{PRODUCTION}")["sha"]
    staging = api.ref(f"heads/{STAGING}")["sha"]
    candidate, tag_object = api.candidate(tag)
    content = api.request(f"contents/{MANIFEST}?{urlencode({'ref': candidate})}")
    require(
        content.get("encoding") == "base64", "Candidate manifest could not be read."
    )
    manifest = json.loads(base64.b64decode(content["content"]))
    require(
        isinstance(manifest, dict) and tag == f"v{manifest.get('version')}",
        "Candidate tag does not match the integration manifest version.",
    )
    comparison = api.request(f"compare/{main}...{candidate}")
    require(
        comparison.get("status") in {"ahead", "identical"},
        "Candidate is not a fast-forward from current main.",
    )
    # Equality proves reachability too and enforces the freeze: Supervisor builds the tip.
    require(
        staging == candidate,
        "testing must still point at the candidate; its soak is stale if testing advanced.",
    )
    workflow = api.request("actions/workflows/ci-validate.yml")
    require(
        workflow.get("name") == "Validate" and workflow.get("path") == VALIDATE,
        "Expected the repository's exact Validate workflow.",
    )
    query = urlencode({"head_sha": candidate, "branch": STAGING, "per_page": 100})
    runs = api.request(f"actions/workflows/{workflow['id']}/runs?{query}")
    run = validate_run(
        runs.get("workflow_runs", []),
        workflow_id=workflow["id"],
        candidate=candidate,
        repository=api.repository,
    )
    job_query = f"actions/runs/{run['id']}/attempts/{run.get('run_attempt', 1)}/jobs?per_page=100"
    jobs = validate_jobs(api.request(job_query), candidate=candidate)
    release = api.request(f"releases/tags/{tag}")
    require(
        release.get("tag_name") == tag
        and (
            release.get("prerelease") is True
            or (release.get("prerelease") is False and main == candidate)
        )
        and release.get("draft") is False,
        "Candidate must have a published pre-release for the same tag.",
    )
    audit_bytes = api.asset(release, f"promotion-audit-{tag}.json")
    evidence = api.asset(release, f"release-audit-{tag}.md")
    approval = validate_audit(
        json.loads(audit_bytes), tag=tag, candidate=candidate, evidence=evidence
    )
    return {
        "repository": api.repository,
        "tag": tag,
        "candidate_sha": candidate,
        "main_sha": main,
        "staging_sha": staging,
        "tag_object_sha": tag_object,
        "release_id": release["id"],
        "release_prerelease": release["prerelease"],
        "validate_run_id": run["id"],
        "validate_run_attempt": run.get("run_attempt", 1),
        "validate_jobs": jobs,
        "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
        "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "approved_by": approval["approved_by"],
        "approval_basis": approval["basis"],
    }


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def require_trusted_context(plan):
    """Write access is available only to an explicit dispatch executing reviewed main code."""
    require(
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_REPOSITORY") == plan["repository"]
        and os.environ.get("GITHUB_WORKFLOW_REF")
        == f"{plan['repository']}/.github/workflows/promote.yml@refs/heads/main",
        "Apply is restricted to the Promote workflow dispatched from main in this repository.",
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    require(
        not dirty and head == os.environ.get("GITHUB_SHA") == plan["main_sha"],
        "Trusted checkout must be clean and match both dispatched SHA and current main; dispatch again.",
    )


def promote(api, tag, *, apply=False, expected_digest=None):
    plan = preflight(api, tag)
    if not apply:
        return plan
    require(
        expected_digest and plan_digest(plan) == expected_digest,
        "Candidate, CI, audit or branch refs changed since the read-only preflight; run it again.",
    )
    require_trusted_context(plan)
    # Read all gates again immediately before the first mutation, including mutable assets/CI.
    require(
        preflight(api, tag) == plan,
        "Promotion inputs changed during final preflight; nothing was written.",
    )
    candidate = plan["candidate_sha"]
    if plan["main_sha"] != candidate:
        # GitHub enforces FF server-side too. Never force, merge, retag or rebuild a candidate.
        updated = api.request(
            "git/refs/heads/main",
            method="PATCH",
            payload={"sha": candidate, "force": False},
        )
        require(
            updated.get("object", {}).get("sha") == candidate,
            "main promotion was not confirmed; pre-release was not changed.",
        )
    require(
        api.ref("heads/main")["sha"] == candidate,
        "main does not equal the promoted candidate; pre-release was not changed.",
    )
    require(
        api.candidate(tag) == (candidate, plan["tag_object_sha"])
        and api.ref("heads/testing")["sha"] == candidate,
        "A candidate ref changed after main moved; inspect immediately. Pre-release was not changed.",
    )
    if not plan["release_prerelease"]:
        return plan  # Safe retry after a successful PATCH whose response was lost.
    try:
        release = api.request(
            f"releases/{plan['release_id']}",
            method="PATCH",
            # A release born as a pre-release is not made Latest when it is flipped: GitHub keeps
            # showing the previous one as the current release unless asked in the same request.
            payload={
                "prerelease": False,
                "name": tag.removeprefix("v"),
                "make_latest": "true",
            },
        )
        require(
            release.get("tag_name") == tag and release.get("prerelease") is False,
            "GitHub did not confirm the matching release became stable.",
        )
    except Rejected as error:
        raise Rejected(
            f"main is already promoted to {candidate}, but release promotion failed. "
            f"Do not rewind main. Fix the cause and dispatch again: {error}"
        ) from error
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="main-only workflow; default is a read-only dry run",
    )
    parser.add_argument("--expect-digest", default=os.environ.get("PROMOTION_DIGEST"))
    args = parser.parse_args()
    try:
        require(args.repo, "Supply --repo owner/name or GITHUB_REPOSITORY.")
        plan = promote(
            GitHub(args.repo),
            args.tag,
            apply=args.apply,
            expected_digest=args.expect_digest,
        )
    except (
        Rejected,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"::error title=Promotion refused::{error}", file=sys.stderr)
        return 1
    print(json.dumps(plan, indent=2, sort_keys=True))
    print(
        "Promotion completed."
        if args.apply
        else "Read-only preflight passed. No remote writes performed."
    )
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"digest={plan_digest(plan)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
