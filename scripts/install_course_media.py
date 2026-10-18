#!/usr/bin/env python3
"""Install one checksum-pinned Academy ZIP without exposing a partial bundle.

Only this repository's www/learn/media directory may be replaced. The release
manifest binds every media file to its path, byte count and SHA-256. No archive
member is extracted with ZipFile.extract or a shell command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_EXPANDED_BYTES = 1_000_000_000
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_MANIFEST_BYTES = 2_000_000
MAX_MEMBERS = 10_000
CHUNK_BYTES = 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mp3", ".vtt", ".json", ".txt"}
SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class MediaInstallError(ValueError):
    """A release is invalid or its installation cannot be completed safely."""


class RecoveryRequired(MediaInstallError):
    """Keep the work directory because it contains the previous installation."""


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MediaInstallError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(data, context):
    try:
        value = json.loads(data, object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MediaInstallError(f"Invalid {context} JSON") from error
    if not isinstance(value, dict):
        raise MediaInstallError(f"{context} must be a JSON object")
    return value


def _digest(value, context):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise MediaInstallError(f"{context} needs a 64-character SHA-256")
    return value.lower()


def _safe_name(name, *, directory=False):
    if not isinstance(name, str) or not name or "\\" in name:
        raise MediaInstallError(f"Unsafe ZIP path: {name!r}")
    if directory:
        name = name.removesuffix("/")
    if not name or name.startswith("/") or any(ord(char) < 32 for char in name):
        raise MediaInstallError(f"Unsafe ZIP path: {name!r}")
    parts = name.split("/")
    if any(
        part in ("", ".", "..") or ":" in part or part[-1:] in (" ", ".")
        for part in parts
    ):
        raise MediaInstallError(f"Unsafe ZIP path: {name!r}")
    if any(part.split(".", 1)[0].upper() in RESERVED_NAMES for part in parts):
        raise MediaInstallError(f"Reserved ZIP path: {name!r}")
    if not directory and PurePosixPath(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise MediaInstallError(f"Unsupported media extension: {name!r}")
    return name


def _destination(path=None):
    root = REPO_ROOT.resolve()
    expected = root / "www" / "learn" / "media"
    requested = Path(path) if path is not None else expected
    # Compare against the lexical known repository destination, not its possibly
    # symlink-redirected resolve(). A custom CLI path cannot widen this boundary.
    if requested.resolve() != expected:
        raise MediaInstallError(
            "Destination must be this repository's www/learn/media directory"
        )
    for component in (root / "www", root / "www" / "learn", expected):
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise MediaInstallError(
                "Destination and its repository ancestors must not be links"
            )
    if expected.exists() and not expected.is_dir():
        raise MediaInstallError("Media destination exists and is not a directory")
    return expected


def _config(path):
    config = _json(Path(path).read_bytes(), "release config")
    url = config.get("url")
    if not isinstance(url, str):
        raise MediaInstallError("Release URL must be HTTPS")
    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise MediaInstallError("Release URL must be a valid HTTPS URL") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise MediaInstallError(
            "Release URL must be HTTPS without credentials or a fragment"
        )
    return url, _digest(config.get("sha256"), "Release config")


def _copy_archive(source, target, expected_sha):
    checksum = hashlib.sha256()
    size = 0
    with target.open("xb") as output:
        while chunk := source.read(CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise MediaInstallError("Archive exceeds the download size limit")
            checksum.update(chunk)
            output.write(chunk)
    if checksum.hexdigest() != expected_sha:
        raise MediaInstallError("Archive SHA-256 mismatch; nothing was extracted")


def _members(archive):
    members = archive.infolist()
    if len(members) > MAX_MEMBERS:
        raise MediaInstallError("Archive has too many members")
    files, names = {}, set()
    expanded = 0
    for info in members:
        original = info.orig_filename
        if original != info.filename:
            raise MediaInstallError("ZIP member name was truncated")
        name = _safe_name(original, directory=info.is_dir())
        folded = name.casefold()
        if folded in names:
            raise MediaInstallError(f"Duplicate ZIP path: {name}")
        names.add(folded)
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if stat.S_ISLNK(mode) or file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise MediaInstallError(
                f"ZIP links and special files are not allowed: {name}"
            )
        if file_type == stat.S_IFDIR and not info.is_dir():
            raise MediaInstallError(
                f"ZIP directory metadata disagrees with its path: {name}"
            )
        if info.flag_bits & 1:
            raise MediaInstallError("Encrypted ZIP members are not supported")
        if info.is_dir():
            if info.file_size:
                raise MediaInstallError("ZIP directory contains data")
            continue
        expanded += info.file_size
        if info.file_size < 0 or expanded > MAX_EXPANDED_BYTES:
            raise MediaInstallError("Archive exceeds the expanded size limit")
        files[name] = info
    folded_files = {name.casefold() for name in files}
    for name in names:
        if any(
            parent.as_posix().casefold() in folded_files
            for parent in PurePosixPath(name).parents
            if str(parent) != "."
        ):
            raise MediaInstallError("ZIP file path is also used as a parent directory")
    return files


def _manifest(archive, files):
    if "manifest.json" not in files:
        raise MediaInstallError("Archive requires root manifest.json")
    if files["manifest.json"].file_size > MAX_MANIFEST_BYTES:
        raise MediaInstallError("Media manifest is too large")
    manifest = _json(archive.read(files["manifest.json"]), "media manifest")
    if type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise MediaInstallError("Media manifest schema must be 1")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_MEMBERS:
        raise MediaInstallError("Media manifest requires a nonempty files list")
    expected, folded = {}, set()
    total = 0
    for item in entries:
        if not isinstance(item, dict):
            raise MediaInstallError("Media manifest file entry must be an object")
        name = _safe_name(item.get("path"))
        if name.casefold() == "manifest.json" or name.casefold() in folded:
            raise MediaInstallError("Manifest has duplicate or self-referencing paths")
        folded.add(name.casefold())
        size = item.get("bytes")
        if type(size) is not int or size < 0:
            raise MediaInstallError(f"Manifest byte count is invalid: {name}")
        total += size
        if total > MAX_EXPANDED_BYTES:
            raise MediaInstallError("Manifest exceeds the expanded size limit")
        expected[name] = (_digest(item.get("sha256"), f"Manifest file {name}"), size)
    if set(files) != set(expected) | {"manifest.json"}:
        raise MediaInstallError(
            "Manifest paths do not exactly match archive files (missing or undeclared file)"
        )
    for name, (_, size) in expected.items():
        if files[name].file_size != size:
            raise MediaInstallError(
                f"Manifest byte count does not match ZIP member: {name}"
            )
    return expected


def _extract_verified(archive, files, expected, stage):
    stage.mkdir()
    expanded = 0
    # The manifest is pinned by the whole-archive digest; it cannot contain its
    # own hash. Every other file is additionally bound by its manifest entry.
    for name, info in files.items():
        target = stage.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        checksum = hashlib.sha256()
        size = 0
        with archive.open(info) as source, target.open("xb") as output:
            while chunk := source.read(CHUNK_BYTES):
                size += len(chunk)
                expanded += len(chunk)
                if size > info.file_size or expanded > MAX_EXPANDED_BYTES:
                    raise MediaInstallError(
                        "Extracted data exceeds declared size or expanded size limit"
                    )
                checksum.update(chunk)
                output.write(chunk)
        if size != info.file_size:
            raise MediaInstallError(f"Incomplete ZIP member: {name}")
        if name in expected and (checksum.hexdigest(), size) != expected[name]:
            raise MediaInstallError(f"Manifest SHA-256 or size mismatch: {name}")


def _remove_work(work, parent):
    # This is the only recursive removal. Its target must be the exact sibling
    # directory created by mkdtemp, with no redirect through a link/junction.
    if work.parent != parent or not work.name.startswith(".media-install-"):
        raise MediaInstallError("Refusing cleanup outside the media staging boundary")
    if (
        work.is_symlink()
        or getattr(work, "is_junction", lambda: False)()
        or work.resolve().parent != parent
    ):
        raise MediaInstallError("Refusing cleanup through a linked staging directory")
    if work.exists():
        shutil.rmtree(work)


def _replace(stage, destination, work):
    previous = work / "previous"
    had_previous = destination.exists()
    if had_previous:
        os.replace(destination, previous)
    try:
        os.replace(stage, destination)
    except OSError as error:
        if had_previous:
            try:
                os.replace(previous, destination)
            except OSError as recovery_error:
                raise RecoveryRequired(
                    f"Replacement and rollback failed; previous media preserved at {previous}"
                ) from recovery_error
        raise MediaInstallError(
            "Replacement failed; previous media was restored"
        ) from error


def install_media(*, config=None, destination=None, archive=None):
    """Return installed file count; keep old destination intact on validation errors."""
    destination = _destination(destination)
    config = (
        Path(config)
        if config is not None
        else REPO_ROOT / "www" / "learn" / "course" / "media-release.json"
    )
    url, expected_sha = _config(config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination = _destination(destination)
    work = Path(tempfile.mkdtemp(prefix=".media-install-", dir=destination.parent))
    cleanup = True
    try:
        pinned_archive = work / "release.zip"
        if archive is not None:
            with Path(archive).open("rb") as source:
                _copy_archive(source, pinned_archive, expected_sha)
        else:
            request = Request(
                url, headers={"User-Agent": "Crop-Steering-Academy-Pages/1"}
            )
            with urlopen(request, timeout=60) as response:
                if urlsplit(response.geturl()).scheme != "https":
                    raise MediaInstallError(
                        "Release download redirected away from HTTPS"
                    )
                _copy_archive(response, pinned_archive, expected_sha)
        with ZipFile(pinned_archive) as bundle:
            files = _members(bundle)
            expected = _manifest(bundle, files)
            stage = work / "payload"
            _extract_verified(bundle, files, expected, stage)
        # Recheck the destination boundary immediately before moving directories.
        _destination(destination)
        _replace(stage, destination, work)
        return len(expected)
    except RecoveryRequired:
        cleanup = False
        raise
    except (BadZipFile, NotImplementedError, RuntimeError) as error:
        raise MediaInstallError(f"Invalid or unsupported media ZIP: {error}") from error
    finally:
        if cleanup:
            _remove_work(work, destination.parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Pinned release config JSON")
    parser.add_argument(
        "--destination",
        type=Path,
        help="Must resolve to this repository's www/learn/media",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use a local ZIP; configured SHA-256 is still mandatory",
    )
    args = parser.parse_args(argv)
    try:
        count = install_media(
            config=args.config, destination=args.destination, archive=args.archive
        )
    except (MediaInstallError, OSError) as error:
        print(f"Course media installation failed: {error}", file=sys.stderr)
        return 1
    print(f"Installed and verified {count} course media files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
