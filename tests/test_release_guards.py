"""The release rules a machine can check (.github/scripts/release_guards.py).

Boxes build the controller from a git branch and are offered an update when a version number
changes on it, so a version change IS a release. These pin the rules that stop one happening by
accident or inside something else, and the properties that keep the guard itself trustworthy.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "release_guards.py"
WORKFLOW = ROOT / ".github" / "workflows" / "release-guards.yml"

spec = importlib.util.spec_from_file_location("release_guards", SCRIPT)
guards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guards)

OLD = {"integration": "2.18.1", "controller": "0.15.2"}
NEW = {"integration": "2.19.0", "controller": "0.16.0"}
RELEASE_PATHS = [
    "custom_components/crop_steering/manifest.json",
    "custom_components/crop_steering/const.py",
    "addons/f2_control/config.yaml",
    "CHANGELOG.md",
    "addons/f2_control/CHANGELOG.md",
    "README.md",
    "docs/audits/2026-10-01-release-2.19.0.md",
]


def _pr(**changes):
    case = {
        "base_ref": "testing",
        "head_ref": "feat/something",
        "base_versions": OLD,
        "head_versions": OLD,
        "changed_paths": ["custom_components/crop_steering/sensor.py"],
        "tags": {"v2.18.0", "v2.18.1"},
        "version_files": {},  # their content rule: tests/test_release_guard_content.py
    }
    case.update(changes)
    return guards.check_pull_request(**case)


# --------------------------------------------------------------------------- pull requests
def test_a_feature_that_leaves_versions_alone_is_fine_whatever_it_touches():
    assert _pr() == []
    assert _pr(changed_paths=["addons/f2_control/f2_control/controller.py"]) == []


def test_a_feature_branch_may_not_change_a_version():
    """The accident this exists for: one changed line in a feature pull request, merged, and
    every box following the branch is offered a release nobody decided to make."""
    (problem,) = _pr(head_versions=NEW)
    assert "IS a release" in problem and "release/<the new version>" in problem
    assert (
        "integration 2.18.1 -> 2.19.0" in problem
        and "controller 0.15.2 -> 0.16.0" in problem
    )
    assert (
        len(_pr(head_versions={**OLD, "controller": "0.15.3"})) == 1
    )  # the pump's half alone


def test_a_release_pull_request_named_for_its_version_passes():
    assert (
        _pr(head_ref="release/2.19.0", head_versions=NEW, changed_paths=RELEASE_PATHS)
        == []
    )
    # the integration alone (nothing the controller runs changed) is a release too
    assert (
        _pr(
            head_ref="release/2.18.2",
            head_versions={**OLD, "integration": "2.18.2"},
            changed_paths=RELEASE_PATHS,
        )
        == []
    )


CONTROLLER_ONLY = {
    "head_ref": "release/0.15.3",
    "head_versions": {**OLD, "controller": "0.15.3"},
    "changed_paths": [
        "addons/f2_control/config.yaml",
        "addons/f2_control/CHANGELOG.md",
    ],
}


def test_every_release_is_named_by_the_integration_version():
    """One number names a release: the tag, the HACS release, the changelog entry and the
    promotion check are all keyed by the integration version. This guard used to accept a
    controller-only release named for the controller version, which promotion can never accept:
    the integration version has not changed, so the tag promotion demands already names the
    PREVIOUS commit, and a tag is never moved. It failed only after `main` had advanced.
    (Review finding on JakeTheRabbit/HA-Irrigation-Strategy#47.)
    """
    (problem,) = _pr(**CONTROLLER_ONLY)
    assert "controller 0.15.2 -> 0.15.3" in problem
    assert "integration version" in problem and "v2.18.1" in problem
    # ...and a pair is not named for its controller half either
    (problem,) = _pr(
        head_ref="release/0.16.0", head_versions=NEW, changed_paths=RELEASE_PATHS
    )
    assert "release/<the new version>" in problem and "2.19.0" in problem


def test_whatever_the_pull_request_guard_accepts_the_promotion_guard_can_accept():
    """The whole accepted sequence, release pull request to promotion, for every shape of
    release. The tag the process creates on the merged release is v<integration version>; a
    promotion is a fast-forward of `main` to that commit."""
    tags = {"v2.18.0", "v2.18.1"}
    for head_versions in (
        NEW,  # the pair
        {**OLD, "integration": "2.18.2"},  # the integration alone
        {
            "integration": "2.18.2",
            "controller": "0.15.3",
        },  # a controller fix, released properly
    ):
        named = f"release/{head_versions['integration']}"
        accepted = _pr(
            head_ref=named,
            head_versions=head_versions,
            changed_paths=RELEASE_PATHS,
            tags=tags,
        )
        assert accepted == [], head_versions
        tag = f"v{head_versions['integration']}"
        assert (
            tag not in tags
        )  # so it can be created on the merged commit, and only there
        assert (
            guards.check_promotion(
                forced=False,
                fast_forward=True,
                on_staging=True,
                tags_at_tip={tag},
                integration_version=head_versions["integration"],
            )
            == []
        )

    # The sequence the reviewer walked: the pull request guard now stops it at the start...
    assert _pr(**CONTROLLER_ONLY, tags=tags) != []
    # ...because this is where it would otherwise end: promotion wants v2.18.1, which already
    # names the previous commit, whatever the candidate itself was tagged.
    (problem,) = guards.check_promotion(
        forced=False,
        fast_forward=True,
        on_staging=True,
        tags_at_tip={"v0.15.3"},
        integration_version=OLD["integration"],
    )
    assert "v2.18.1" in problem


def test_a_release_branch_named_for_some_other_version_does_not():
    (problem,) = _pr(
        head_ref="release/2.20.0", head_versions=NEW, changed_paths=RELEASE_PATHS
    )
    assert "release/<the new version>" in problem


def test_a_release_pull_request_carries_no_code():
    """What soaks has to be exactly what was reviewed as features. A fix slipped into the
    release pull request would reach production having been reviewed as a version bump.
    """
    (problem,) = _pr(
        head_ref="release/2.19.0",
        head_versions=NEW,
        changed_paths=[*RELEASE_PATHS, "addons/f2_control/f2_control/controller.py"],
    )
    assert "nothing else" in problem and "controller.py" in problem
    assert (
        "CHANGELOG.md" not in problem
    )  # documents are what a release pull request is for


def test_a_release_branch_that_releases_nothing_is_questioned():
    (problem,) = _pr(head_ref="release/2.19.0", changed_paths=["CHANGELOG.md"])
    assert "changes no version number" in problem


def test_a_version_only_goes_up_and_is_a_plain_number():
    down = _pr(
        head_ref="release/2.18.0",
        head_versions={**OLD, "integration": "2.18.0"},
        changed_paths=RELEASE_PATHS,
        tags=set(),
    )
    assert any("only ever goes up" in p for p in down)
    odd = _pr(
        head_ref="release/2.19.0-rc1",
        head_versions={**OLD, "integration": "2.19.0-rc1"},
        changed_paths=RELEASE_PATHS,
    )
    assert any("not a plain x.y.z" in p for p in odd)
    # numeric, not alphabetical: 2.9.0 -> 2.10.0 goes UP
    assert (
        _pr(
            head_ref="release/2.10.0",
            base_versions={**OLD, "integration": "2.9.0"},
            head_versions={**OLD, "integration": "2.10.0"},
            changed_paths=RELEASE_PATHS,
        )
        == []
    )


def test_a_version_number_is_never_reused():
    (problem,) = _pr(
        head_ref="release/2.19.0",
        head_versions=NEW,
        changed_paths=RELEASE_PATHS,
        tags={"v2.18.1", "v2.19.0"},  # a candidate that failed its soak
    )
    assert "never reused" in problem


def test_main_takes_no_pull_requests_not_even_from_testing():
    (problem,) = _pr(base_ref="main", head_ref="testing")
    assert "takes no pull requests" in problem and "promotion" in problem


def test_upstreams_own_release_may_arrive_through_an_intake_branch():
    """A fork cannot split someone else's release, and it arrives with their version number.
    It is still a candidate that soaks alone (docs/RELEASING.md); it is not refused here.
    """
    assert (
        _pr(
            head_ref="intake/upstream-2026-10-01",
            head_versions=NEW,
            changed_paths=[
                *RELEASE_PATHS,
                "addons/f2_control/f2_control/controller.py",
            ],
        )
        == []
    )


def test_no_branch_is_exempt_by_name():
    """2.18.1 was opened before these rules and was let through by name until it merged. That
    exception is gone; a fix branch that carries a version in its name is still not a release.
    """
    assert not hasattr(guards, "GRANDFATHERED_HEADS")
    before = {"integration": "2.18.0", "controller": "0.15.1"}
    for head in ("fix/2.18.1-post-44-follow-up", "fix/2.18.2-something"):
        (problem,) = _pr(
            head_ref=head, base_versions=before, head_versions=OLD, tags={"v2.18.0"}
        )
        assert "release/<the new version>" in problem


# --------------------------------------------------------------------------- reading versions
def test_versions_are_read_as_text_and_junk_reads_as_none():
    assert guards.manifest_version('{"domain": "x", "version": "2.18.1"}') == "2.18.1"
    assert guards.manifest_version("not json") is None
    assert guards.manifest_version('{"version": 2}') is None
    assert guards.manifest_version(None) is None
    assert (
        guards.addon_version('name: x\nversion: "0.15.2"\nslug: f2_control\n')
        == "0.15.2"
    )
    assert guards.addon_version("version: 0.15.2  # bumped\n") == "0.15.2"
    assert guards.addon_version("name: x\n") is None


def test_the_guard_reads_the_real_files_in_this_repository():
    assert guards.as_tuple(
        guards.manifest_version((ROOT / guards.MANIFEST).read_text())
    )
    assert guards.as_tuple(
        guards.addon_version((ROOT / guards.ADDON_CONFIG).read_text())
    )
    for path in guards.VERSION_FILES:
        assert (ROOT / path).is_file(), path


# --------------------------------------------------------------------------- promotion
def _promotion(**changes):
    case = {
        "forced": False,
        "fast_forward": True,
        "on_staging": True,
        "tags_at_tip": {"v2.19.0"},
        "integration_version": "2.19.0",
    }
    case.update(changes)
    return guards.check_promotion(**case)


def test_a_fast_forward_to_the_tagged_commit_on_testing_is_a_promotion():
    assert _promotion() == []


@pytest.mark.parametrize(
    "change, says",
    [
        ({"forced": True}, "rewritten or moved backwards"),
        ({"fast_forward": False}, "rewritten or moved backwards"),
        ({"on_staging": False}, "without going through staging"),
        ({"tags_at_tip": set()}, "not the commit tagged v2.19.0"),
        ({"tags_at_tip": {"v2.18.1"}}, "not the commit tagged v2.19.0"),
    ],
)
def test_anything_else_that_reaches_main_fails_loudly(change, says):
    (problem,) = _promotion(**change)
    assert says in problem


# --------------------------------------------------------------------------- the guard itself
def test_the_guard_runs_from_the_default_branch_and_never_touches_pull_request_code():
    """pull_request_target runs with the repository's own token. It is safe only while this
    workflow never checks out or runs the pull request. If someone adds a build or test step
    here, or points the checkout at the head, that is a remote-code-execution hole: fail.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "permissions:\n  contents: read" in workflow
    steps = workflow[workflow.index("jobs:") :]
    for forbidden in (
        "head.sha",
        "head.ref",
        "head_ref",
        "npm ",
        "pip ",
        "pytest",
        "ref:",
    ):
        assert (
            forbidden not in steps
        ), f"the guard workflow must not contain {forbidden!r}"
    assert steps.count("run:") == 2  # the two guard invocations and nothing else
    assert "persist-credentials: false" in steps
    script = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("checkout", "exec(", "eval(", "import_module", "shell=True"):
        assert forbidden not in script.split('"""', 2)[2], forbidden
