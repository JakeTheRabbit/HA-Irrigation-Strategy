"""Package completed R3 lesson/group videos without including source masters.

Run only after the assembler has finished all 29 videos. This checks source and
metadata bindings, public file formats and archive integrity; decoder/frame and
human listening checks remain separate production tasks.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from zipfile import ZIP_STORED, ZipFile

if __package__:
    from . import build_course as compiler
    from . import install_course_media as installer
else:
    import build_course as compiler
    import install_course_media as installer

FPS = 30
CHUNK_BYTES = 1024 * 1024


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path, content):
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".package-", delete=False
    ) as stream:
        staged = Path(stream.name)
        stream.write(content)
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def timing(metadata, label):
    duration, frames = metadata.get("duration"), metadata.get("frames")
    if (
        type(frames) is not int
        or frames <= 0
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
        or abs(duration - frames / FPS) > 0.0001
    ):
        raise ValueError(
            f"{label}: missing or inconsistent completed duration/frame count"
        )
    if metadata["chapters"][-1]["start"] >= duration:
        raise ValueError(f"{label}: final chapter lies outside the completed video")
    return duration, frames


def production_record(compiled, index, groups):
    lessons = {lesson["id"]: lesson for lesson in compiled["lessons"]}
    lesson_rows, group_rows = [], []
    for lid in compiler.ORDER:
        video = index["lessons"][lid]
        duration, frames = timing(video, lid)
        lesson_rows.append(
            {
                "id": lid,
                "duration": duration,
                "frames": frames,
                "chapters": len(video["chapters"]),
                "source_sha256": video["source_sha256"],
            }
        )
    for group in groups["groups"]:
        gid = group["id"]
        duration, frames = timing(group, gid)
        source = "\n\n".join(
            slide["narration"]
            for lid in group["lessons"]
            for slide in lessons[lid]["slides"]
        )
        source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if group.get("source_sha256") != source_sha:
            raise ValueError(f"{gid}: stale grouped video source")
        expected_frames = sum(
            index["lessons"][lid]["frames"] for lid in group["lessons"]
        )
        if frames != expected_frames:
            raise ValueError(
                f"{gid}: group frame count does not equal its completed lessons"
            )
        offset, expected_starts = 0, []
        for lid in group["lessons"]:
            video = index["lessons"][lid]
            expected_starts.extend(
                offset / FPS + chapter["start"] for chapter in video["chapters"]
            )
            offset += video["frames"]
        if any(
            abs(chapter["start"] - expected) > 0.0001
            for chapter, expected in zip(group["chapters"], expected_starts)
        ):
            raise ValueError(
                f"{gid}: group chapter times do not match completed lesson offsets"
            )
        group_rows.append(
            {
                "id": gid,
                "duration": duration,
                "frames": frames,
                "chapters": len(group["chapters"]),
                "lessons": group["lessons"],
                "routes": group["routes"],
                "source_sha256": source_sha,
            }
        )
    return {
        "schema": 1,
        "edition": compiler.EDITION,
        "voice": sorted({video["voice"] for video in index["lessons"].values()}),
        "images_note": "AI-generated physical teaching illustrations, native diagrams and captures of the isolated application demo explain the lessons. They are not evidence of a physical installation.",
        "review_note": "Packaging verifies source/file consistency. Decoder, frame, caption alignment and human listening review require their separate production records.",
        "fps": FPS,
        "lesson_count": 24,
        "group_count": 5,
        "slide_bindings": 153,
        "lesson_duration": sum(row["duration"] for row in lesson_rows),
        "group_duration": sum(row["duration"] for row in group_rows),
        "lessons": lesson_rows,
        "groups": group_rows,
    }


def validate_public_files(media_root, expected):
    if (
        not media_root.is_dir()
        or media_root.is_symlink()
        or getattr(media_root, "is_junction", lambda: False)()
    ):
        raise ValueError("Completed public-media must be a regular directory")
    allowed = expected | {"manifest.json", "production.json"}
    found = set()
    for path in media_root.rglob("*"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Public media must not contain links or junctions")
        if path.is_file():
            found.add(path.relative_to(media_root).as_posix())
    if found - allowed:
        raise ValueError(
            "Unexpected public file(s); source masters must stay outside the bundle: "
            + ", ".join(sorted(found - allowed))
        )
    for relative in sorted(expected):
        path = compiler.local_file(media_root, relative)
        if path.suffix == ".mp4":
            with path.open("rb") as stream:
                if stream.read(12)[4:8] != b"ftyp":
                    raise ValueError(f"Invalid completed MP4 header: {relative}")
        elif path.suffix == ".vtt":
            text = path.read_text(encoding="utf-8-sig")
            if not text.startswith("WEBVTT") or "-->" not in text:
                raise ValueError(f"Missing caption cues: {relative}")
        else:
            raise ValueError(f"Unsupported public file extension: {relative}")


def package_videos(production, modules, archive, overwrite=False):
    production, modules, archive = (
        Path(production).resolve(),
        Path(modules).resolve(),
        Path(archive).resolve(),
    )
    media_root = production / "public-media"
    if archive.suffix.lower() != ".zip" or archive.is_relative_to(media_root):
        raise ValueError("Archive must be a .zip outside public-media")
    if archive.exists() and (not overwrite or not archive.is_file()):
        raise FileExistsError(
            "Archive already exists; choose another path or explicitly use --overwrite"
        )
    # Copy only small source/metadata files. Large videos remain at their production paths.
    with tempfile.TemporaryDirectory(prefix="academy-package-source-") as temporary:
        course_dir = Path(temporary) / "course"
        shutil.copytree(modules, course_dir / "modules")
        (course_dir / "glossary.json").write_text("[]\n", encoding="utf-8")
        for name in ("video-index.json", "video-groups.json"):
            shutil.copy2(production / name, course_dir / name)
        compiled = compiler.compile_course(course_dir)
        index = compiler.load_video_index(
            course_dir, compiled["lessons"], required=True
        )
        groups = compiler.load_video_groups(
            course_dir, compiled["lessons"], required=True
        )
    if sum(len(lesson["slides"]) for lesson in compiled["lessons"]) != 153:
        raise ValueError("Packaging requires exactly 153 source slides")
    record = production_record(compiled, index, groups)
    expected = set()
    for lid, video in index["lessons"].items():
        expected.update(
            [
                compiler.media_url(video["src"], f"media/lessons/{lid}.mp4"),
                compiler.media_url(video["captions"], f"media/lessons/{lid}.vtt"),
            ]
        )
    for group in groups["groups"]:
        gid = group["id"]
        expected.update(
            [
                compiler.media_url(group["src"], f"media/groups/{gid}.mp4"),
                compiler.media_url(group["captions"], f"media/groups/{gid}.vtt"),
            ]
        )
    if len(expected) != 58:
        raise ValueError(
            "Publication requires exactly 58 lesson/group MP4 and VTT files"
        )
    validate_public_files(media_root, expected)
    production_data = json_bytes(record)
    inventory = [
        {
            "path": relative,
            "bytes": (media_root / relative).stat().st_size,
            "sha256": compiler.file_hash(media_root / relative),
        }
        for relative in sorted(expected)
    ]
    inventory.append(
        {
            "path": "production.json",
            "bytes": len(production_data),
            "sha256": hashlib.sha256(production_data).hexdigest(),
        }
    )
    bindings = [
        {
            "lesson": lesson["id"],
            "slide": slide["id"],
            "audio": f'lessons/{lesson["id"]}.mp4',
            "captions": f'lessons/{lesson["id"]}.vtt',
            "source_sha256": hashlib.sha256(
                slide["narration"].encode("utf-8")
            ).hexdigest(),
        }
        for lesson in compiled["lessons"]
        for slide in lesson["slides"]
    ]
    manifest = {
        "schema": 1,
        "edition": compiler.EDITION,
        "files": inventory,
        "bindings": bindings,
        "notice": "Synthetic teaching narration and illustrations; online knowledge practice is not hardware commissioning.",
    }
    manifest_data = json_bytes(manifest)
    if (
        sum(entry["bytes"] for entry in inventory) + len(manifest_data)
        > installer.MAX_EXPANDED_BYTES
    ):
        raise ValueError(
            "Public bundle exceeds the pinned installer expanded-size limit"
        )
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=archive.parent, prefix=".academy-package-", suffix=".zip", delete=False
    ) as stream:
        staged = Path(stream.name)
    try:
        # Store already compressed video. Stream and rehash to catch changes during packaging.
        with ZipFile(staged, "w", compression=ZIP_STORED, allowZip64=True) as bundle:
            bundle.writestr("manifest.json", manifest_data)
            bundle.writestr("production.json", production_data)
            for entry in inventory:
                if entry["path"] == "production.json":
                    continue
                checksum, size = hashlib.sha256(), 0
                with (media_root / entry["path"]).open("rb") as source, bundle.open(
                    entry["path"], "w", force_zip64=True
                ) as target:
                    while chunk := source.read(CHUNK_BYTES):
                        size += len(chunk)
                        checksum.update(chunk)
                        target.write(chunk)
                if size != entry["bytes"] or checksum.hexdigest() != entry["sha256"]:
                    raise ValueError(f'Media changed during packaging: {entry["path"]}')
        archive_sha, archive_size = compiler.file_hash(staged), staged.stat().st_size
        if archive_size > installer.MAX_ARCHIVE_BYTES:
            raise ValueError(
                "Public archive exceeds the pinned installer download-size limit"
            )
        if overwrite:
            os.replace(staged, archive)
        else:
            # Atomic no-clobber publication on the same filesystem as the staged ZIP.
            os.link(staged, archive)
        atomic_write(media_root / "production.json", production_data)
        atomic_write(media_root / "manifest.json", manifest_data)
    finally:
        staged.unlink(missing_ok=True)
    return {
        "edition": compiler.EDITION,
        "archive": str(archive),
        "sha256": archive_sha,
        "bytes": archive_size,
        "archive_files": len(inventory) + 1,
        "bindings": len(bindings),
        "lessons": 24,
        "groups": 5,
        "lesson_duration": record["lesson_duration"],
        "group_duration": record["group_duration"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", type=Path, required=True)
    parser.add_argument("--modules", type=Path, default=compiler.COURSE / "modules")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace an existing archive",
    )
    args = parser.parse_args(argv)
    result = package_videos(args.production, args.modules, args.archive, args.overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
