#!/usr/bin/env python3
"""Prepare a tracked-only f2-control release; applying/publishing is explicit.

Examples (from the monorepo):
  python scripts/prepare_addon_release.py
  python scripts/prepare_addon_release.py --apply output/addon-release/<release>
  python scripts/prepare_addon_release.py --publish output/addon-release/<release>

Preparation includes tracked working-tree edits and staged additions, never untracked
files. Review the artifact, manifest and REVIEW.md before applying it. Only the
verified dedicated clone's f2_control/ subtree can change; its root metadata stays.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile

TARGET = "f2_control"
EXPECTED_REMOTE = "github.com/jaketherabbit/f2-control"
EXCLUDED_DIRS = {
    "tests",
    "test",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".git",
    ".github",
    "node_modules",
    ".venv",
    "venv",
    ".cache",
}
REQUIRED = {
    "config.yaml",
    "Dockerfile",
    "build.yaml",
    "run.sh",
    "nginx.conf",
    "f2_control/controller.py",
    "f2_control/crop_steering_engine/__init__.py",
    "f2_control/crop_steering_engine/core.py",
    "www/public/index.html",
    "www/public/dashboard.html",
}


class ReleaseError(RuntimeError):
    """A release invariant failed before publication."""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise ReleaseError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def repository(path: Path) -> Path:
    root = path.resolve()
    if (
        not root.is_dir()
        or Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root
    ):
        raise ReleaseError("Use the repository root, not a directory outside/below it")
    return root


def linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def contained(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or not rel.parts or any(p in {"..", "."} for p in rel.parts):
        raise ReleaseError(f"Unsafe relative artifact path: {relative}")
    if "\\" in relative or ":" in relative:
        raise ReleaseError(f"Unsafe relative artifact path: {relative}")
    path = root.joinpath(*rel.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ReleaseError(f"Artifact path escapes its root: {relative}")
    cursor = root
    for part in rel.parts:
        cursor /= part
        if linked(cursor):
            raise ReleaseError(f"Symlink/junction cannot be released: {relative}")
    return path


def normalized_remote(url: str) -> str:
    value = url.strip().rstrip("/").removesuffix(".git").lower()
    for prefix in ("https://", "ssh://git@", "git@"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return value.replace("github.com:", "github.com/")


def verify_destination(destination: Path, *, publish: bool = False) -> Path:
    root = repository(destination)
    for args in (
        ("remote", "get-url", "--all", "origin"),
        ("remote", "get-url", "--push", "--all", "origin"),
    ):
        if any(
            normalized_remote(url) != EXPECTED_REMOTE
            for url in git(root, *args).splitlines()
        ):
            raise ReleaseError(
                "Destination origin must be JakeTheRabbit/f2-control on GitHub"
            )
    if git(root, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
        raise ReleaseError(
            "Destination is dirty (including untracked/ignored files); preserve it first"
        )
    contained(root, TARGET)
    if publish and git(root, "branch", "--show-current") != "main":
        raise ReleaseError("Publishing requires the dedicated clone's main branch")
    return root


def excluded(relative: str) -> bool:
    path = PurePosixPath(relative)
    return bool(set(path.parts) & EXCLUDED_DIRS) or path.suffix in {".pyc", ".pyo"}


def tracked(
    root: Path, *prefixes: str, include_excluded: bool = False
) -> dict[str, str]:
    result = {}
    for record in git(root, "ls-files", "--stage", "-z", "--", *prefixes).split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, _, stage = metadata.split()
        if stage != "0":
            raise ReleaseError(f"Unmerged source path: {path}")
        if mode not in {"100644", "100755"}:
            raise ReleaseError(f"Unsupported tracked file type: {path}")
        if include_excluded or not excluded(path):
            file = contained(root, path)
            # Deliberately removed tracked files are omitted from the prepared release.
            if file.is_file():
                result[path] = mode
    return result


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_from(data: bytes) -> str:
    text = data.decode("utf-8-sig")
    version = re.search(
        r"^version:\s*[\"\']?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)[\"\']?\s*$",
        text,
        re.M,
    )
    if not version or not re.search(
        r"^slug:\s*[\"\']?f2_control[\"\']?\s*$", text, re.M
    ):
        raise ReleaseError(
            "config.yaml must have a release version and slug f2_control"
        )
    return version[1]


def validate_payload(payload: Path) -> dict[str, bytes]:
    files = {}
    for file in payload.rglob("*"):
        relative = file.relative_to(payload).as_posix()
        contained(payload, relative)
        if file.is_file():
            if excluded(relative):
                raise ReleaseError(f"Forbidden file in prepared payload: {relative}")
            data = file.read_bytes()
            if file.suffix == ".py":
                ast.parse(data, filename=relative)
            files[relative] = data
    missing = REQUIRED - files.keys()
    if missing:
        raise ReleaseError(
            f"Missing required release files: {', '.join(sorted(missing))}"
        )
    version_from(files["config.yaml"])
    return files


def prepare(source: Path, destination: Path, output: Path | None = None) -> Path:
    source = repository(source)
    destination = verify_destination(destination)
    if (
        source == destination
        or source.is_relative_to(destination)
        or destination.is_relative_to(source)
    ):
        raise ReleaseError("Source and destination repositories must be separate")
    selected = tracked(
        source,
        "addons/f2_control",
        "www",
        "crop-steering-engine/src/crop_steering_engine",
    )
    contents = {path: contained(source, path).read_bytes() for path in selected}
    mappings = {}
    for path, mode in selected.items():
        if path.startswith("addons/f2_control/"):
            relative = path.removeprefix("addons/f2_control/")
            if relative.startswith("www/") or relative == "web-index.html":
                continue
            mappings[relative] = (path, mode)
        elif path.startswith("www/"):
            mappings["www/public/" + path.removeprefix("www/")] = (path, mode)
    overlay = "addons/f2_control/web-index.html"
    if overlay not in selected:
        raise ReleaseError(
            "The add-on web-index.html overlay must be tracked and present"
        )
    mappings["www/public/index.html"] = (overlay, selected[overlay])
    package_prefix = "crop-steering-engine/src/crop_steering_engine/"
    engine_sources = {
        p.removeprefix(package_prefix): p
        for p in selected
        if p.startswith(package_prefix)
    }
    vendored = {
        p.removeprefix("f2_control/crop_steering_engine/"): spec[0]
        for p, spec in mappings.items()
        if p.startswith("f2_control/crop_steering_engine/")
    }
    if not engine_sources or engine_sources.keys() != vendored.keys():
        raise ReleaseError("The tracked source and vendored engine file lists differ")
    for relative, path in engine_sources.items():
        if contents[path] != contents[vendored[relative]]:
            raise ReleaseError(
                f"Vendored engine differs from tested source: {relative}"
            )
    blobs = {rel: contents[path] for rel, (path, _) in mappings.items()}
    version = version_from(blobs.get("config.yaml", b""))
    if output is None:
        parent = contained(source, "output/addon-release")
        if parent.resolve().is_relative_to(destination):
            raise ReleaseError("Preparation output cannot be inside the destination")
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix=f"{version}-", dir=parent))
    else:
        output = output.resolve()
        if (
            output == source
            or output.is_relative_to(destination)
            or source.is_relative_to(output)
        ):
            raise ReleaseError(
                "Preparation output must be new and outside the destination"
            )
        output.mkdir(parents=True, exist_ok=False)
    payload = output / TARGET
    payload.mkdir()
    manifest_files = {}
    for relative, data in blobs.items():
        file = contained(payload, relative)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        path, mode = mappings[relative]
        os.chmod(file, 0o755 if mode == "100755" else 0o644)
        manifest_files[relative] = {
            "source": path,
            "sha256": digest(data),
            "mode": mode,
            "bytes": len(data),
        }
    validate_payload(payload)
    old_files = tracked(destination, TARGET, include_excluded=True)
    changes = []
    for relative, data in sorted(blobs.items()):
        old = contained(destination, f"{TARGET}/{relative}")
        if not old.exists() or old.read_bytes() != data:
            changes.append(
                {"action": "modify" if old.exists() else "add", "path": relative}
            )
    for path in old_files:
        relative = path.removeprefix(TARGET + "/")
        if relative not in blobs:
            changes.append({"action": "delete", "path": relative})
    manifest = {
        "schema": 1,
        "target": TARGET,
        "version": version,
        "source_head": git(source, "rev-parse", "HEAD"),
        "destination": str(destination),
        "destination_head": git(destination, "rev-parse", "HEAD"),
        "source_status": git(
            source, "status", "--porcelain=v1", "--untracked-files=no"
        ),
        "files": manifest_files,
        "changes": changes,
    }
    (output / "release.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    review = [
        f"# f2-control {version} release review",
        "",
        "Preparation only: the dedicated repository is unchanged.",
        "",
        f"Source commit: `{manifest['source_head']}`",
        f"Destination commit: `{manifest['destination_head']}`",
        "",
        "Only f2_control/ can change. Root README.md and repository.yaml are preserved.",
        "Tracked working-tree edits are included; untracked files, tests and caches are excluded.",
        "",
        "| Action | Path |",
        "| --- | --- |",
    ]
    review.extend(
        f"| {item['action']} | `{TARGET}/{item['path']}` |" for item in changes
    )
    review.extend(
        [
            "",
            "Inspect the payload and release.json hashes before applying. Publication does not rebuild or enable any installed HA controller.",
            "",
        ]
    )
    (output / "REVIEW.md").write_text("\n".join(review), encoding="utf-8")
    return output


def apply_prepared(prepared: Path, destination: Path, *, publish: bool = False) -> bool:
    prepared = prepared.resolve()
    destination = verify_destination(destination, publish=publish)
    if prepared.is_relative_to(destination):
        raise ReleaseError("Prepared artifact cannot live inside the destination")
    manifest = json.loads((prepared / "release.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("target") != TARGET:
        raise ReleaseError("Unsupported manifest or target outside f2_control")
    if Path(manifest["destination"]).resolve() != destination:
        raise ReleaseError("Prepared artifact belongs to another destination")
    if manifest["destination_head"] != git(destination, "rev-parse", "HEAD"):
        raise ReleaseError("Destination HEAD changed since preparation; prepare again")
    files = validate_payload(contained(prepared, TARGET))
    records = manifest["files"]
    if files.keys() != records.keys() or any(
        digest(data) != records[rel]["sha256"] for rel, data in files.items()
    ):
        raise ReleaseError("Prepared payload changed after review; prepare again")
    if version_from(files["config.yaml"]) != manifest["version"]:
        raise ReleaseError("Prepared version differs from manifest")
    if any(record["mode"] not in {"100644", "100755"} for record in records.values()):
        raise ReleaseError("Invalid payload file mode")
    previous = tracked(destination, TARGET, include_excluded=True)
    # Resolve EVERY target before the first mutation; no recursive deletion/move.
    destinations = {rel: contained(destination, f"{TARGET}/{rel}") for rel in files}
    removals = [
        contained(destination, path)
        for path in previous
        if path.removeprefix(TARGET + "/") not in files
    ]
    for file in destinations.values():
        if file.exists() and not file.is_file():
            raise ReleaseError(
                "Destination has a file/directory type conflict; preserve and resolve it first"
            )
        if any(
            parent.exists() and not parent.is_dir()
            for parent in file.parents
            if parent != destination
        ):
            raise ReleaseError(
                "Destination has a parent-path type conflict; preserve and resolve it first"
            )
    for file in removals:
        file.unlink()
    for relative, data in files.items():
        file = destinations[relative]
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        os.chmod(file, 0o755 if records[relative]["mode"] == "100755" else 0o644)
    # No root metadata is copied and no broad `git add -A` is permitted.
    if not publish:
        return bool(git(destination, "status", "--porcelain=v1", "--", TARGET))
    git(destination, "add", "-A", "--", TARGET)
    staged = git(destination, "diff", "--cached", "--name-only", "-z")
    if not staged:
        return False
    if any(not path.startswith(TARGET + "/") for path in staged.split("\0") if path):
        raise ReleaseError(
            "Concurrent staged changes outside f2_control; refusing to commit"
        )
    git(
        destination,
        "commit",
        "-m",
        f"release: f2-control v{manifest['version']} (tracked monorepo artifact)",
    )
    git(destination, "push", "origin", "HEAD:refs/heads/main")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "f2-control",
    )
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="New preparation directory (default: output/addon-release/version-random)",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--apply",
        type=Path,
        metavar="PREPARED",
        help="Apply a reviewed artifact to f2_control only; no commit/push",
    )
    actions.add_argument(
        "--publish",
        type=Path,
        metavar="PREPARED",
        help="Apply a reviewed artifact, commit and push main",
    )
    args = parser.parse_args(argv)
    try:
        if args.apply or args.publish:
            if args.output:
                raise ReleaseError("--output is only valid for preparation")
            changed = apply_prepared(
                args.apply or args.publish, args.destination, publish=bool(args.publish)
            )
            print(
                ("Published" if args.publish else "Applied for review")
                if changed
                else "No release changes"
            )
        else:
            output = prepare(args.source, args.destination, args.output)
            print(
                f"Prepared only: {output}\nReview: {output / 'REVIEW.md'}\nDedicated repository unchanged."
            )
    except (ReleaseError, OSError, ValueError, SyntaxError, KeyError) as error:
        parser.exit(1, f"Release stopped: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
