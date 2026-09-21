"""The release rules from docs/RELEASING.md and CONTRIBUTING.md that a machine can check.

Boxes build the controller straight from a git branch, and are offered an update the moment a
version number changes on it. So a version change is a release, and these guards exist to make
sure one never happens by accident, or tucked inside something else:

  pull-request   a pull request may change a version only from a branch named for that version,
                 a release pull request may change nothing but versions and documents (in a
                 version file: the version field, not the rest of the file), a version only
                 ever goes up and is never reused, and `main` takes no pull requests at all.
  promotion      every push to `main` must be a fast-forward to a tagged commit that is already
                 on `testing`. This one cannot prevent the push; it fails loudly, at once.

The decisions are pure functions (tests/test_release_guards.py); the git and GitHub plumbing is
at the bottom. IMPORTANT: the pull-request guard runs on `pull_request_target`, which GitHub
takes from the repository's DEFAULT branch (`main`): a pull request cannot edit the guard that
judges it, and a change to this file takes effect only once it has been promoted to `main`.
That trigger carries the repository's token, so the guard must never check out, import or
execute anything from the pull request: it reads the head commit's files as text through
`git show`, and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

MANIFEST = "custom_components/crop_steering/manifest.json"
ADDON_CONFIG = "addons/f2_control/config.yaml"
CONST = "custom_components/crop_steering/const.py"
VERSION_FILES = (MANIFEST, ADDON_CONFIG, CONST)

PRODUCTION, STAGING = "main", "testing"


# --------------------------------------------------------------------------- pure rules
def manifest_version(text: str | None) -> str | None:
    try:
        value = json.loads(text or "").get("version")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def addon_version(text: str | None) -> str | None:
    match = re.search(r"""^version:\s*["']?([^"'\s#]+)""", text or "", re.M)
    return match.group(1) if match else None


def as_tuple(version: str | None) -> tuple[int, ...] | None:
    if not version or not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        return None
    return tuple(int(part) for part in version.split("."))


def is_document(path: str) -> bool:
    return path.endswith(".md") or path.startswith("docs/")


def without_version(path: str, text: str | None) -> str | None:
    """A version-bearing file with its ONE version field blanked, so two copies can be compared
    for everything else. None when the file is absent, or cannot be read as what it is.

    The manifest is compared as parsed JSON (reformatting it is not a change); the other two as
    text, where only the top-level `version:` line and the `SOFTWARE_VERSION = ` line count.
    """
    if text is None:
        return None
    if path == MANIFEST:
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        data.pop("version", None)
        return json.dumps(data, sort_keys=True)
    field = r"^version:.*$" if path == ADDON_CONFIG else r"^SOFTWARE_VERSION\s*=.*$"
    masked, found = re.subn(field, "<version>", text, count=1, flags=re.M)
    return masked if found else None


def check_pull_request(
    *, base_ref, head_ref, base_versions, head_versions, changed_paths, tags, version_files
):
    """Every rule the pull request breaks, in words that say what to do. Empty = fine.

    `*_versions` are {"integration": "2.18.1", "controller": "0.15.2"} (None where unreadable).
    `version_files` is {path: (text at the fork point, text at the head)} for VERSION_FILES, None
    where a file does not exist. Required, so that no caller can leave the content rule unfed.
    """
    problems = []
    if base_ref == PRODUCTION:
        problems.append(
            f"`{PRODUCTION}` takes no pull requests. It is what production rooms install from, and "
            f"it moves only by promotion: a fast-forward to a tagged commit that has soaked on "
            f"`{STAGING}` (docs/RELEASING.md). Point this pull request at `{STAGING}`."
        )

    changed = {
        part: (base_versions.get(part), head_versions.get(part))
        for part in ("integration", "controller")
        if base_versions.get(part) != head_versions.get(part)
    }
    is_release = head_ref.startswith("release/")
    named_for = head_ref.removeprefix("release/")

    if changed:
        summary = ", ".join(f"{part} {old} -> {new}" for part, (old, new) in changed.items())
        new_versions = {new for _old, new in changed.values()}
        if head_ref.startswith("intake/"):
            pass  # upstream's own release arriving in a fork, carrying upstream's number
        elif not is_release or named_for not in new_versions:
            problems.append(
                f"This pull request changes a version number ({summary}) from the branch "
                f"`{head_ref}`. On a branch boxes install from, that one line IS a release. Only a "
                f"branch named `release/<the new version>` may do it. If this is a feature or a "
                f"fix, take the version change out: it belongs in the release pull request."
            )
        for part, (old, new) in changed.items():
            was, now = as_tuple(old), as_tuple(new)
            if now is None:
                problems.append(f"The new {part} version {new!r} is not a plain x.y.z number.")
            elif was is not None and now <= was:
                problems.append(
                    f"The {part} version goes from {old} to {new}. A version only ever goes up: "
                    f"boxes are offered an update when it changes, never a downgrade."
                )
        new_integration = head_versions.get("integration")
        if "integration" in changed and f"v{new_integration}" in tags:
            problems.append(
                f"The tag v{new_integration} already exists. A version number is never reused "
                f"for different code: a candidate that failed its soak is fixed under the next one."
            )

    if is_release:
        strays = sorted(
            path for path in changed_paths if path not in VERSION_FILES and not is_document(path)
        )
        if strays:
            problems.append(
                "A release pull request holds version numbers, changelogs and documents, and "
                "nothing else, so that what soaked is exactly what was reviewed. These belong in "
                "their own pull request: " + ", ".join(strays)
            )
        # The PATH of a version file being allowed is not the FILE being allowed: these three
        # also hold executable defaults, dependencies, and the add-on's permissions and options.
        rewritten = sorted(
            path
            for path, (before, after) in version_files.items()
            if before != after
            and (
                (masked := without_version(path, after)) is None
                or masked != without_version(path, before)
            )
        )
        if rewritten:
            problems.append(
                "A release pull request changes the version number in a version file and nothing "
                "else in it. Something other than the version differs (a default, a dependency, "
                "an add-on permission or option, or the file was added, removed or cannot be "
                "read) in: " + ", ".join(rewritten) + ". That would reach production reviewed as "
                "a version bump. Put it in its own pull request."
            )
        if not changed:
            problems.append(
                f"`{head_ref}` is named as a release but changes no version number."
            )
    return problems


def check_promotion(*, forced, fast_forward, on_staging, tags_at_tip, integration_version):
    """Every way a push to `main` was not a promotion. Empty = it was one."""
    problems = []
    if forced or not fast_forward:
        problems.append(
            f"`{PRODUCTION}` was rewritten or moved backwards. It only ever fast-forwards: boxes "
            f"that already updated cannot be taken back by moving the branch, and a box that "
            f"rebuilds now gets code nobody chose for it. Roll back boxes from their backups."
        )
    if not on_staging:
        problems.append(
            f"The new tip of `{PRODUCTION}` is not a commit on `{STAGING}`: it reached production "
            f"without going through staging at all. Turn add-on auto-update off on production "
            f"boxes NOW, then find out how it got here (docs/RELEASING.md, Hotfixes)."
        )
    wanted = f"v{integration_version}"
    if wanted not in tags_at_tip:
        problems.append(
            f"The new tip of `{PRODUCTION}` is not the commit tagged {wanted}. Promotion is a "
            f"fast-forward to the exact tagged commit that soaked, not to wherever `{STAGING}` "
            f"happens to be. What production will now build is not what was soaked."
        )
    return problems


# --------------------------------------------------------------------------- plumbing
def _git(*args: str, check: bool = True) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if check and done.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip() if done.returncode == 0 else ""


def _show(commit: str, path: str) -> str | None:
    """A file's text at a commit. Read as data: never checked out, imported or executed."""
    return _git("show", f"{commit}:{path}", check=False) or None


def _versions(commit: str) -> dict:
    return {
        "integration": manifest_version(_show(commit, MANIFEST)),
        "controller": addon_version(_show(commit, ADDON_CONFIG)),
    }


def _is_ancestor(older: str, newer: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", older, newer], check=False
        ).returncode
        == 0
    )


def _report(title: str, problems: list[str]) -> int:
    if not problems:
        print(f"{title}: ok")
        return 0
    for problem in problems:
        print(f"::error title={title}::{problem}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## {title}\n\n" + "\n".join(f"- {p}" for p in problems) + "\n")
    return 1


def main(mode: str) -> int:
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
        event = json.load(fh)
    tags = set(_git("tag", "--list").split())
    if mode == "pull-request":
        pull = event["pull_request"]
        base, head = pull["base"]["sha"], pull["head"]["sha"]
        _git("fetch", "--quiet", "origin", f"refs/pull/{pull['number']}/head")
        fork_point = _git("merge-base", base, head)
        return _report(
            "Release guard",
            check_pull_request(
                base_ref=pull["base"]["ref"],
                head_ref=pull["head"]["ref"],
                base_versions=_versions(fork_point),
                head_versions=_versions(head),
                changed_paths=_git("diff", "--name-only", fork_point, head).split("\n"),
                tags=tags,
                version_files={
                    path: (_show(fork_point, path), _show(head, path))
                    for path in VERSION_FILES
                },
            ),
        )
    if mode == "promotion":
        before, after = event["before"], event["after"]
        return _report(
            "Promotion guard",
            check_promotion(
                forced=bool(event.get("forced")),
                fast_forward=set(before) == {"0"} or _is_ancestor(before, after),
                on_staging=_is_ancestor(after, f"origin/{STAGING}"),
                tags_at_tip=set(_git("tag", "--points-at", after).split()),
                integration_version=manifest_version(_show(after, MANIFEST)),
            ),
        )
    raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
