"""A release pull request may change the version FIELD of a version-bearing file, not the file.

Review finding on JakeTheRabbit/HA-Irrigation-Strategy#47. The release-only rule let
`const.py`, `manifest.json` and the add-on `config.yaml` through whole, because their PATHS
are on the list of files a release may touch. So a correctly named release pull request could also
change an executable default, a dependency, or an add-on permission, and still pass the gate that
advertises "versions and documents, nothing else": reviewed as a version bump, soaked as one, and
built on every production box.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "release_guards", ROOT / ".github" / "scripts" / "release_guards.py"
)
guards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guards)

MANIFEST, ADDON, CONST = guards.MANIFEST, guards.ADDON_CONFIG, guards.CONST
REAL = {
    path: (ROOT / path).read_text(encoding="utf-8") for path in (MANIFEST, ADDON, CONST)
}
OLD = {
    "integration": guards.manifest_version(REAL[MANIFEST]),
    "controller": guards.addon_version(REAL[ADDON]),
}
NEW = {"integration": "9.0.0", "controller": "9.0.0"}  # one number for both halves (2.21.0 on)


def _bumped(path):
    """The real file as a release pull request leaves it: its version changed, nothing else."""
    text = REAL[path]
    old = OLD["controller" if path == ADDON else "integration"]
    new = NEW["controller" if path == ADDON else "integration"]
    assert (
        text.count(f'"{old}"') == 1
    ), path  # so the replace below is the version and only it
    return text.replace(f'"{old}"', f'"{new}"')


def _release(**heads):
    """A release pull request named for its version, whose version files are `heads` (default:
    the honest bump)."""
    files = {path: (REAL[path], heads.get(path, _bumped(path))) for path in REAL}
    return guards.check_pull_request(
        base_ref="testing",
        head_ref="release/9.0.0",
        base_versions=OLD,
        head_versions=NEW,
        changed_paths=[*REAL, "CHANGELOG.md"],
        tags=set(),
        version_files=files,
    )


def test_the_honest_bump_of_the_real_files_passes():
    assert _release() == []


def test_a_default_changed_beside_the_version_in_const_py_is_caught():
    head = _bumped(CONST).replace(
        "DEFAULT_NUM_ZONES = ", "DEFAULT_NUM_ZONES = 9 or ", 1
    )
    assert head != _bumped(CONST)  # the premise: that constant really is in this file
    (problem,) = _release(**{CONST: head})
    assert CONST in problem and "version" in problem


def test_a_dependency_added_beside_the_version_in_the_manifest_is_caught():
    manifest = json.loads(_bumped(MANIFEST))
    manifest["requirements"] = [*manifest.get("requirements", []), "requests==2.0.0"]
    (problem,) = _release(**{MANIFEST: json.dumps(manifest, indent=2)})
    assert MANIFEST in problem


@pytest.mark.parametrize(
    "line, becomes",
    [
        ("hassio_api: false", "hassio_api: true"),  # a permission
        ("host_network: false", "host_network: true"),
        ("  num_zones: 3", "  num_zones: 4"),  # a shipped option default
        ("boot: manual", "boot: auto"),
    ],
)
def test_a_permission_or_an_option_changed_beside_the_version_in_the_addon_config_is_caught(
    line, becomes
):
    assert REAL[ADDON].count(line + "\n") == 1, line
    (problem,) = _release(**{ADDON: _bumped(ADDON).replace(line, becomes)})
    assert ADDON in problem


def test_every_offending_file_is_named_not_only_the_first():
    (problem,) = _release(
        **{
            ADDON: _bumped(ADDON).replace("hassio_api: false", "hassio_api: true"),
            CONST: _bumped(CONST) + "\nEXTRA = 1\n",
        }
    )
    assert ADDON in problem and CONST in problem and MANIFEST not in problem


def test_reformatting_the_manifest_is_not_a_change_but_a_second_version_key_elsewhere_is():
    assert (
        _release(**{MANIFEST: json.dumps(json.loads(_bumped(MANIFEST)), indent=4)})
        == []
    )
    # Only the manifest's own top-level "version" is a version field.
    nested = json.loads(_bumped(MANIFEST))
    nested["extra"] = {"version": "1"}
    assert len(_release(**{MANIFEST: json.dumps(nested)})) == 1


def test_only_the_top_level_version_line_of_the_addon_config_is_a_version_field():
    indented = _bumped(ADDON).replace(
        "  num_zones: 3\n", "  num_zones: 3\n  version: 2\n"
    )
    assert len(_release(**{ADDON: indented})) == 1
    # RECIPE_STORAGE_VERSION in const.py is not the software version either.
    storage = _bumped(CONST).replace(
        "RECIPE_STORAGE_VERSION = 1", "RECIPE_STORAGE_VERSION = 2"
    )
    assert storage != _bumped(CONST) and len(_release(**{CONST: storage})) == 1


def test_a_version_file_that_appears_vanishes_or_cannot_be_read_is_a_problem():
    for path in REAL:
        files = {p: (REAL[p], _bumped(p)) for p in REAL}
        for pair in ((None, _bumped(path)), (REAL[path], None)):
            files[path] = pair
            problems = guards.check_pull_request(
                base_ref="testing",
                head_ref="release/9.0.0",
                base_versions=OLD,
                head_versions=NEW,
                changed_paths=list(REAL),
                tags=set(),
                version_files=files,
            )
            assert any(path in problem for problem in problems), (path, pair)
    assert any(MANIFEST in problem for problem in _release(**{MANIFEST: "{not json"}))


def test_a_feature_pull_request_is_not_held_to_it():
    """Only a release pull request promises to change nothing but versions. A feature may change
    these files freely (a new constant, a new add-on option) as long as the version stays put.
    """
    assert (
        guards.check_pull_request(
            base_ref="testing",
            head_ref="feat/new-option",
            base_versions=OLD,
            head_versions=OLD,
            changed_paths=[ADDON, CONST],
            tags=set(),
            version_files={
                ADDON: (
                    REAL[ADDON],
                    REAL[ADDON].replace("  num_zones: 3", "  num_zones: 4"),
                ),
                CONST: (REAL[CONST], REAL[CONST] + "\nNEW_CONSTANT = 1\n"),
                MANIFEST: (REAL[MANIFEST], REAL[MANIFEST]),
            },
        )
        == []
    )


def test_the_workflow_hands_the_guard_the_files_it_needs_to_compare():
    """main() must pass the texts, or the rule silently checks nothing."""
    source = (ROOT / ".github" / "scripts" / "release_guards.py").read_text(
        encoding="utf-8"
    )
    assert "version_files=" in source.split("def main(")[1]
