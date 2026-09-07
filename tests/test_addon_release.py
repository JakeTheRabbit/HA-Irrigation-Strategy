"""Release tooling uses temporary Git fixtures; no production repository or push."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_addon_release.py"
spec = importlib.util.spec_from_file_location("prepare_addon_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def run(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8"
    ).strip()


def write(root, path, data):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(data, encoding="utf-8")


def init(root):
    root.mkdir()
    run(root, "init", "-b", "main")
    run(root, "config", "user.name", "Release fixture")
    run(root, "config", "user.email", "release-fixture@example.invalid")
    run(root, "config", "core.autocrlf", "false")
    run(root, "config", "core.hooksPath", str(root / ".git" / "no-hooks"))


def commit(root):
    run(root, "add", "-A")
    run(root, "commit", "-m", "fixture")


@pytest.fixture
def repos(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "f2-control"
    init(source)
    init(destination)
    for path in release.REQUIRED:
        if path.startswith("www/"):
            continue
        value = "# fixture\n" if path.endswith(".py") else "fixture\n"
        write(source, "addons/f2_control/" + path, value)
    write(
        source, "addons/f2_control/config.yaml", 'version: "0.12.0"\nslug: f2_control\n'
    )
    write(source, "addons/f2_control/web-index.html", "addon overlay\n")
    write(source, "addons/f2_control/www/public/old-page.html", "stale addon copy\n")
    write(source, "addons/f2_control/tests/test_private.py", "# never publish tests\n")
    write(source, "addons/f2_control/__pycache__/old.pyc", "cache\n")
    write(source, "www/dashboard.html", "canonical tracked dashboard\n")
    write(source, "www/index.html", "pages landing\n")
    for name in ("__init__.py", "core.py"):
        write(
            source,
            "crop-steering-engine/src/crop_steering_engine/" + name,
            "# fixture\n",
        )
    write(destination, "README.md", "preserve dedicated repository readme\n")
    write(destination, "repository.yaml", "name: dedicated repository\n")
    write(destination, "f2_control/old.txt", "stale tracked artifact\n")
    write(destination, "f2_control/tests/old-test.py", "# stale tracked test\n")
    commit(source)
    commit(destination)
    run(
        destination,
        "remote",
        "add",
        "origin",
        "https://github.com/JakeTheRabbit/f2-control.git",
    )
    return source, destination


def test_prepare_uses_only_tracked_files_overlay_and_no_destination_mutation(
    repos, tmp_path
):
    source, destination = repos
    before = {
        p.relative_to(destination): p.read_bytes()
        for p in destination.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }
    write(source, "www/aigrow-ops.html", "untracked personal page\n")
    write(source, "addons/f2_control/f2_control/private.py", "# untracked\n")
    write(
        source,
        "addons/f2_control/www/public/aigrow-ops.html",
        "untracked personal page\n",
    )
    write(source, "www/dashboard.html", "reviewed tracked working edit\n")
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    payload = artifact / "f2_control"
    files = {
        p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file()
    }
    assert files == release.REQUIRED
    assert (payload / "www/public/index.html").read_text() == "addon overlay\n"
    assert (
        payload / "www/public/dashboard.html"
    ).read_text() == "reviewed tracked working edit\n"
    manifest = json.loads((artifact / "release.json").read_text())
    assert {"action": "delete", "path": "tests/old-test.py"} in manifest["changes"]
    assert {
        p.relative_to(destination): p.read_bytes()
        for p in destination.rglob("*")
        if p.is_file() and ".git" not in p.parts
    } == before
    assert run(destination, "status", "--porcelain") == ""


def test_apply_only_changes_addon_and_preserves_root_metadata(repos, tmp_path):
    source, destination = repos
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    before = {
        name: (destination / name).read_bytes()
        for name in ("README.md", "repository.yaml")
    }
    head = run(destination, "rev-parse", "HEAD")
    assert release.apply_prepared(artifact, destination)
    assert not (destination / "f2_control/old.txt").exists()
    assert not (destination / "f2_control/tests/old-test.py").exists()
    assert (
        destination / "f2_control/www/public/index.html"
    ).read_text() == "addon overlay\n"
    assert {name: (destination / name).read_bytes() for name in before} == before
    assert run(destination, "rev-parse", "HEAD") == head
    assert run(destination, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize("kind", ["tracked", "untracked", "ignored"])
def test_dirty_destination_rejected_before_output_or_mutation(repos, tmp_path, kind):
    source, destination = repos
    if kind == "tracked":
        write(destination, "README.md", "user edit\n")
    elif kind == "untracked":
        write(destination, "f2_control/user-data.txt", "preserve\n")
    else:
        (destination / ".git/info/exclude").write_text("private-data.txt\n")
        write(destination, "f2_control/private-data.txt", "preserve\n")
    with pytest.raises(release.ReleaseError, match="dirty"):
        release.prepare(source, destination, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_wrong_remote_and_outside_repository_rejected(repos, tmp_path):
    source, destination = repos
    run(
        destination,
        "remote",
        "set-url",
        "origin",
        "https://github.com/other/project.git",
    )
    with pytest.raises(release.ReleaseError, match="origin"):
        release.prepare(source, destination, tmp_path / "prepared")
    with pytest.raises(release.ReleaseError):
        release.prepare(source, destination.parent, tmp_path / "prepared")


def test_output_inside_destination_rejected(repos):
    source, destination = repos
    with pytest.raises(release.ReleaseError, match="output"):
        release.prepare(source, destination, destination / "prepared")
    assert run(destination, "status", "--porcelain") == ""


def test_manifest_cannot_change_target_to_root_or_parent(repos, tmp_path):
    source, destination = repos
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    manifest = json.loads((artifact / "release.json").read_text())
    manifest["target"] = "../"
    (artifact / "release.json").write_text(json.dumps(manifest))
    with pytest.raises(release.ReleaseError, match="target"):
        release.apply_prepared(artifact, destination)
    assert run(destination, "status", "--porcelain") == ""


@pytest.mark.parametrize("change", ["modified", "extra", "deleted"])
def test_altered_artifact_rejected_before_destination_mutation(repos, tmp_path, change):
    source, destination = repos
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    if change == "modified":
        write(
            artifact, "f2_control/www/public/dashboard.html", "modified after review\n"
        )
    elif change == "extra":
        write(artifact, "f2_control/unreviewed.txt", "extra\n")
    else:
        (artifact / "f2_control/run.sh").unlink()
    with pytest.raises(release.ReleaseError, match="changed|Missing"):
        release.apply_prepared(artifact, destination)
    assert run(destination, "status", "--porcelain") == ""


def test_changed_destination_head_requires_new_review(repos, tmp_path):
    source, destination = repos
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    write(destination, "README.md", "new committed readme\n")
    commit(destination)
    with pytest.raises(release.ReleaseError, match="HEAD changed"):
        release.apply_prepared(artifact, destination)
    assert run(destination, "status", "--porcelain") == ""


def test_publish_requires_main_before_any_mutation(repos, tmp_path):
    source, destination = repos
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    run(destination, "checkout", "-b", "test-other")
    with pytest.raises(release.ReleaseError, match="main branch"):
        release.apply_prepared(artifact, destination, publish=True)
    assert run(destination, "status", "--porcelain") == ""


def test_mismatched_vendored_engine_rejected(repos, tmp_path):
    source, destination = repos
    write(
        source,
        "addons/f2_control/f2_control/crop_steering_engine/core.py",
        "# diverged\n",
    )
    with pytest.raises(release.ReleaseError, match="Vendored engine differs"):
        release.prepare(source, destination, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_containment_rejects_path_traversal_and_links(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for path in ("../outside", "/outside", "C:/outside", "folder\\outside"):
        with pytest.raises(release.ReleaseError):
            release.contained(root, path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable on this host")
    with pytest.raises(release.ReleaseError, match="escapes|Symlink"):
        release.contained(root, "link/file")


def test_publish_only_commits_target_and_requests_nonforce_main_push(
    repos, tmp_path, monkeypatch
):
    source, destination = repos
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    original_git = release.git
    pushes = []

    def fake_push(root, *args):
        if args[0] == "push":
            pushes.append(args)
            return ""
        return original_git(root, *args)

    monkeypatch.setattr(release, "git", fake_push)
    assert release.apply_prepared(artifact, destination, publish=True)
    assert pushes == [("push", "origin", "HEAD:refs/heads/main")]
    paths = run(
        destination, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).splitlines()
    assert paths and all(path.startswith("f2_control/") for path in paths)
    assert run(destination, "status", "--porcelain") == ""


def test_publish_refuses_concurrent_staging_outside_target(
    repos, tmp_path, monkeypatch
):
    source, destination = repos
    artifact = release.prepare(source, destination, tmp_path / "prepared")
    original_git = release.git
    head = run(destination, "rev-parse", "HEAD")

    def concurrent_stage(root, *args):
        if args[0] == "add":
            write(destination, "README.md", "concurrent user edit\n")
            original_git(root, "add", "README.md")
        return original_git(root, *args)

    monkeypatch.setattr(release, "git", concurrent_stage)
    with pytest.raises(release.ReleaseError, match="outside f2_control"):
        release.apply_prepared(artifact, destination, publish=True)
    assert run(destination, "rev-parse", "HEAD") == head
    assert (destination / "README.md").read_text() == "concurrent user edit\n"
