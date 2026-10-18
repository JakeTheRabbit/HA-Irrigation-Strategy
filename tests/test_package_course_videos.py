"""Packaging contracts with temporary metadata and tiny format/integrity fixtures.

These checks exercise packaging and installer compatibility, not MP4 decoding.
No real production bundle is created by the test suite.
"""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

from scripts import build_course as compiler
from scripts import install_course_media as installer
from scripts import package_course_videos as package

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class PackageCourseVideosTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="academy-package-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.production = self.root / "production"
        self.course = self.root / "repository/www/learn/course"
        self.modules = self.course / "modules"
        shutil.copytree(ROOT / "www/learn/course/modules", self.modules)
        (self.course / "glossary.json").write_text("[]", encoding="utf-8")
        self.lessons = compiler.compile_course(self.course)["lessons"]
        self.media = self.production / "public-media"
        self.archive = self.root / "output/course-r3.zip"
        self.index = {"edition": compiler.EDITION, "lessons": {}}
        self.groups = {"edition": compiler.EDITION, "groups": []}
        lesson_map = {lesson["id"]: lesson for lesson in self.lessons}

        def pair(folder, identity):
            for suffix in ("mp4", "vtt"):
                target = self.media / folder / f"{identity}.{suffix}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(
                    b"\x00\x00\x00\x18ftypisomfixture"
                    if suffix == "mp4"
                    else b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nFixture.\n"
                )
            return {
                "src": f"media/{folder}/{identity}.mp4?v={compiler.CACHE_VERSION}",
                "captions": f"media/{folder}/{identity}.vtt?v={compiler.CACHE_VERSION}",
            }

        for lesson in self.lessons:
            lid = lesson["id"]
            chapters = [
                {"id": slide["id"], "title": slide["title"], "start": i}
                for i, slide in enumerate(lesson["slides"])
            ]
            self.index["lessons"][lid] = {
                **pair("lessons", lid),
                "voice": "Fixture voice",
                "source_sha256": compiler.source_hash(lesson),
                "chapters": chapters,
                "duration": len(chapters),
                "frames": len(chapters) * 24,
            }
        for gid, (lesson_ids, routes) in compiler.GROUPS.items():
            chapters, offset = [], 0
            for lid in lesson_ids:
                chapters.extend(
                    {
                        "id": chapter["id"],
                        "lesson": lid,
                        "title": chapter["title"],
                        "start": offset + chapter["start"],
                    }
                    for chapter in self.index["lessons"][lid]["chapters"]
                )
                offset += self.index["lessons"][lid]["duration"]
            source = "\n\n".join(
                slide["narration"]
                for lid in lesson_ids
                for slide in lesson_map[lid]["slides"]
            )
            self.groups["groups"].append(
                {
                    "id": gid,
                    "title": gid,
                    "description": "Fixture group.",
                    "lessons": lesson_ids,
                    "routes": list(routes),
                    "chapters": chapters,
                    **pair("groups", gid),
                    "duration": offset,
                    "frames": offset * 24,
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                }
            )
        self.save_metadata()

    def save_metadata(self):
        write_json(self.production / "video-index.json", self.index)
        write_json(self.production / "video-groups.json", self.groups)

    def build(self, **kwargs):
        return package.package_videos(
            self.production, self.modules, self.archive, **kwargs
        )

    def test_bundle_has_exact_inventory_bindings_and_installs_with_strict_verification(
        self,
    ):
        result = self.build()
        self.assertEqual(
            (
                result["lessons"],
                result["groups"],
                result["bindings"],
                result["archive_files"],
            ),
            (24, 5, 153, 60),
        )
        self.assertEqual(result["sha256"], compiler.file_hash(self.archive))
        with ZipFile(self.archive) as bundle:
            self.assertEqual(len(bundle.namelist()), 60)
            self.assertTrue(
                all(info.compress_type == ZIP_STORED for info in bundle.infolist())
            )
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertEqual(manifest["schema"], 1)
            self.assertEqual(len(manifest["files"]), 59)
            self.assertEqual(len(manifest["bindings"]), 153)
            self.assertEqual(
                set(bundle.namelist()),
                {entry["path"] for entry in manifest["files"]} | {"manifest.json"},
            )
            for entry in manifest["files"]:
                content = bundle.read(entry["path"])
                self.assertEqual(entry["bytes"], len(content))
                self.assertEqual(entry["sha256"], hashlib.sha256(content).hexdigest())
            for binding in manifest["bindings"]:
                self.assertEqual(binding["audio"], f'lessons/{binding["lesson"]}.mp4')
                self.assertEqual(
                    binding["captions"], f'lessons/{binding["lesson"]}.vtt'
                )
            production = json.loads(bundle.read("production.json"))
            self.assertNotIn(str(self.root), json.dumps(production))
            self.assertEqual(production["lesson_duration"], 153)
        config = self.root / "release.json"
        write_json(
            config,
            {"url": "https://example.com/course-r3.zip", "sha256": result["sha256"]},
        )
        with patch.object(installer, "REPO_ROOT", self.root / "repository"):
            self.assertEqual(
                installer.install_media(config=config, archive=self.archive), 59
            )
        for name in ("video-index.json", "video-groups.json"):
            shutil.copy2(self.production / name, self.course / name)
        verified = compiler.verify_media(
            compiler.compile_course(self.course), self.course
        )
        self.assertEqual(verified["bindings"], 153)

    def test_installer_size_limits_are_enforced_before_publication(self):
        for name in ("MAX_EXPANDED_BYTES", "MAX_ARCHIVE_BYTES"):
            with self.subTest(limit=name), patch.object(package.installer, name, 1):
                with self.assertRaisesRegex(ValueError, "installer.*size limit"):
                    self.build()
                self.assertFalse(self.archive.exists())
                self.assertFalse((self.media / "manifest.json").exists())

    def test_archive_overwrite_requires_explicit_flag(self):
        self.archive.parent.mkdir()
        self.archive.write_bytes(b"existing archive")
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.archive.read_bytes(), b"existing archive")
        self.assertFalse((self.media / "manifest.json").exists())
        self.build(overwrite=True)
        with ZipFile(self.archive) as bundle:
            self.assertTrue(bundle.namelist())

    def test_missing_media_refuses_incomplete_production_without_metadata_writes(self):
        (self.media / "groups/operations.mp4").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or invalid"):
            self.build()
        self.assertFalse(self.archive.exists())
        self.assertFalse((self.media / "manifest.json").exists())

    def test_stale_lesson_or_group_and_incomplete_index_are_rejected(self):
        original_index, original_groups = copy.deepcopy(self.index), copy.deepcopy(
            self.groups
        )
        for kind in ("lesson", "group", "incomplete"):
            with self.subTest(kind=kind):
                self.index, self.groups = copy.deepcopy(original_index), copy.deepcopy(
                    original_groups
                )
                if kind == "lesson":
                    self.index["lessons"]["A1"]["source_sha256"] = "0" * 64
                elif kind == "group":
                    self.groups["groups"][0]["source_sha256"] = "0" * 64
                else:
                    self.index["lessons"].pop("D6")
                self.save_metadata()
                with self.assertRaises(ValueError):
                    self.build()
                self.assertFalse(self.archive.exists())

    def test_source_wav_or_unexpected_file_cannot_enter_bundle(self):
        (self.media / "source-master.wav").write_bytes(b"private source master")
        with self.assertRaisesRegex(ValueError, "Unexpected public file"):
            self.build()
        self.assertFalse(self.archive.exists())

    def test_invalid_headers_or_missing_caption_cues_are_rejected(self):
        path = self.media / "lessons/A1.mp4"
        original = path.read_bytes()
        path.write_bytes(b"unfinished or incorrect video")
        with self.assertRaisesRegex(ValueError, "MP4 header"):
            self.build()
        path.write_bytes(original)
        (self.media / "lessons/A1.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "caption cues"):
            self.build()

    def test_inconsistent_frame_counts_or_group_chapter_offsets_are_rejected(self):
        original = copy.deepcopy(self.groups)
        self.groups["groups"][0]["frames"] += 1
        self.save_metadata()
        with self.assertRaisesRegex(ValueError, "duration/frame"):
            self.build()
        self.groups = original
        self.groups["groups"][0]["chapters"][1]["start"] += 0.1
        self.save_metadata()
        with self.assertRaisesRegex(ValueError, "chapter times"):
            self.build()

    def test_file_changing_during_packaging_never_publishes_partial_archive(self):
        target = self.media / "lessons/A1.mp4"
        real_hash = compiler.file_hash

        def change_after_hash(path):
            result = real_hash(path)
            if path.resolve() == target.resolve():
                path.write_bytes(path.read_bytes() + b"changed during package")
            return result

        with patch.object(package.compiler, "file_hash", side_effect=change_after_hash):
            with self.assertRaisesRegex(ValueError, "changed during packaging"):
                self.build()
        self.assertFalse(self.archive.exists())
        self.assertFalse((self.media / "manifest.json").exists())
        self.assertEqual(list(self.archive.parent.glob(".academy-package-*")), [])


if __name__ == "__main__":
    unittest.main()
