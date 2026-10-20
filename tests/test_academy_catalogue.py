"""Publication-gate regressions with isolated metadata/media integrity fixtures.

Fixture media are small byte strings: these tests verify catalogue/hash contracts,
not codecs. Production decoding and frame review are separate media checks.
"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "academy_compiler", ROOT / "scripts/build_course.py"
)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def fixture(root):
    course_dir = root / "learn/course"
    (course_dir / "modules").mkdir(parents=True)
    for source in (ROOT / "www/learn/course/modules").glob("*.json"):
        (course_dir / "modules" / source.name).write_bytes(source.read_bytes())
    (course_dir / "glossary.json").write_text("[]", encoding="utf-8")
    course = compiler.compile_course(course_dir)
    indexed = {lesson["id"]: lesson for lesson in course["lessons"]}
    index = {"edition": compiler.EDITION, "lessons": {}}
    groups = {"edition": compiler.EDITION, "groups": []}
    media = course_dir.parent / "media"
    files = []

    def media_pair(folder, identity):
        for suffix in ("mp4", "vtt"):
            relative = f"{folder}/{identity}.{suffix}"
            content = (
                f"video integrity fixture {identity}"
                if suffix == "mp4"
                else "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nFixture narration\n"
            ).encode()
            destination = media / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            files.append(
                {
                    "path": relative,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        return {
            "src": f"media/{folder}/{identity}.mp4?v={compiler.CACHE_VERSION}",
            "captions": f"media/{folder}/{identity}.vtt?v={compiler.CACHE_VERSION}",
        }

    bindings = []
    for lesson in course["lessons"]:
        lid = lesson["id"]
        index["lessons"][lid] = {
            **media_pair("lessons", lid),
            "voice": "Fixture voice disclosure",
            "source_sha256": compiler.source_hash(lesson),
            "chapters": [
                {"id": slide["id"], "title": slide["title"], "start": i * 10}
                for i, slide in enumerate(lesson["slides"])
            ],
        }
        for slide in lesson["slides"]:
            bindings.append(
                {
                    "lesson": lid,
                    "slide": slide["id"],
                    "source_sha256": hashlib.sha256(
                        slide["narration"].encode()
                    ).hexdigest(),
                    "audio": f"lessons/{lid}.mp4",
                    "captions": f"lessons/{lid}.vtt",
                }
            )
    for gid, (lesson_ids, routes) in compiler.GROUPS.items():
        chapters = [
            {"id": slide["id"], "lesson": lid, "title": lid + " · " + slide["title"]}
            for lid in lesson_ids
            for slide in indexed[lid]["slides"]
        ]
        for i, chapter in enumerate(chapters):
            chapter["start"] = i * 10
        groups["groups"].append(
            {
                "id": gid,
                "title": gid,
                "description": "An integrity-fixture video group.",
                **media_pair("groups", gid),
                "duration": len(chapters) * 10,
                "routes": list(routes),
                "lessons": lesson_ids,
                "chapters": chapters,
            }
        )
    write_json(course_dir / "video-index.json", index)
    write_json(course_dir / "video-groups.json", groups)
    manifest = {"edition": compiler.EDITION, "files": files, "bindings": bindings}
    write_json(media / "manifest.json", manifest)
    return course_dir, index, groups, manifest


class CatalogueMediaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="academy-catalogue-")
        self.addCleanup(self.temporary.cleanup)
        self.course_dir, self.index, self.groups, self.manifest = fixture(
            Path(self.temporary.name)
        )

    def compile(self):
        return compiler.compile_course(self.course_dir)

    def manifest_write(self):
        write_json(self.course_dir.parent / "media/manifest.json", self.manifest)

    def test_video_source_hash_uses_exact_ordered_narration_with_blank_line_separator(
        self,
    ):
        lesson = {"slides": [{"narration": "First."}, {"narration": "Second."}]}
        self.assertEqual(
            compiler.source_hash(lesson),
            hashlib.sha256(b"First.\n\nSecond.").hexdigest(),
        )
        source = self.course_dir / "modules/foundations.json"
        lessons = json.loads(source.read_text(encoding="utf-8-sig"))
        lessons[0]["slides"][0]["narration"] += " A changed sentence."
        write_json(source, lessons)
        with self.assertRaisesRegex(ValueError, "Stale lesson video source"):
            self.compile()

    def test_complete_index_replaces_legacy_videos_and_exact_routes_verify(self):
        course = self.compile()
        self.assertEqual(course["edition"], "2026-10-21-r5")
        self.assertEqual(
            len([lesson for lesson in course["lessons"] if lesson.get("video")]), 24
        )
        self.assertEqual(
            [
                len(compiler.route_lessons(course["lessons"], route))
                for route in compiler.ROUTES
            ],
            [17, 23, 23],
        )
        result = compiler.verify_media(course, self.course_dir)
        self.assertEqual(
            result, {"lessons": 24, "groups": 5, "bindings": 153, "verified_files": 58}
        )
        self.assertIn("All 24 lessons", course["disclosures"]["narration"])
        self.assertEqual(course["lessons"][0]["video"], self.index["lessons"]["A1"])

    def test_preassembly_compile_allowed_but_publication_requires_index_and_groups(
        self,
    ):
        (self.course_dir / "video-index.json").unlink()
        course = self.compile()
        self.assertEqual(
            len([lesson for lesson in course["lessons"] if lesson.get("video")]), 5
        )
        with self.assertRaisesRegex(ValueError, "24 lesson videos"):
            compiler.verify_media(course, self.course_dir)
        write_json(self.course_dir / "video-index.json", self.index)
        (self.course_dir / "video-groups.json").unlink()
        with self.assertRaisesRegex(ValueError, "Five grouped videos"):
            compiler.verify_media(self.compile(), self.course_dir)

    def test_present_index_must_have_all_lessons_and_current_source(self):
        for mutation in (
            lambda data: data["lessons"].pop("D6"),
            lambda data: data["lessons"]["A1"].update(source_sha256="0" * 64),
            lambda data: data.update(edition="old"),
        ):
            data = copy.deepcopy(self.index)
            mutation(data)
            write_json(self.course_dir / "video-index.json", data)
            with self.assertRaises(ValueError):
                self.compile()

    def test_chapter_identity_order_zero_and_monotonicity_are_required(self):
        mutations = [
            lambda chapters: chapters[0].update(start=1),
            lambda chapters: chapters[1].update(start=0),
            lambda chapters: chapters[1].update(id="wrong-slide"),
            lambda chapters: chapters.reverse(),
            lambda chapters: chapters[1].update(start=float("inf")),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data = copy.deepcopy(self.index)
                mutation(data["lessons"]["A1"]["chapters"])
                write_json(self.course_dir / "video-index.json", data)
                with self.assertRaisesRegex(ValueError, "chapter"):
                    self.compile()

    def test_remote_traversal_and_stale_cache_urls_are_rejected(self):
        for source in (
            "https://example.com/A1.mp4",
            "media/lessons/../A1.mp4?v=20261021r5",
            "media/lessons/A1.mp4?v=20261019r2",
            "media\\lessons\\A1.mp4?v=20261021r5",
        ):
            data = copy.deepcopy(self.index)
            data["lessons"]["A1"]["src"] = source
            write_json(self.course_dir / "video-index.json", data)
            with self.assertRaisesRegex(ValueError, "media URL"):
                self.compile()

    def test_wrong_host_group_coverage_and_chapters_are_rejected(self):
        for mutation in (
            lambda data: data["groups"][2]["routes"].append("operator"),
            lambda data: data["groups"][2]["lessons"].__setitem__(0, "C2b"),
            lambda data: data["groups"][0]["chapters"][0].update(lesson="D1"),
            lambda data: data["groups"][0].update(duration=1),
        ):
            data = copy.deepcopy(self.groups)
            mutation(data)
            write_json(self.course_dir / "video-groups.json", data)
            with self.assertRaises(ValueError):
                self.compile()

    def test_tampered_file_fails_even_if_size_is_unchanged(self):
        course = self.compile()
        path = self.course_dir.parent / "media/lessons/A1.mp4"
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            compiler.verify_media(course, self.course_dir)

    def test_missing_file_or_inventory_entry_cannot_pass(self):
        course = self.compile()
        removed = self.manifest["files"].pop()
        self.manifest_write()
        with self.assertRaisesRegex(ValueError, "omits referenced"):
            compiler.verify_media(course, self.course_dir)
        self.manifest["files"].append(removed)
        self.manifest_write()
        (self.course_dir.parent / "media/lessons/A1.mp4").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or invalid"):
            compiler.verify_media(course, self.course_dir)

    def test_all_153_narration_bindings_must_match_and_be_unique(self):
        for mutation in (
            lambda records: records.pop(),
            lambda records: records.append(records[0]),
            lambda records: records[0].update(source_sha256="f" * 64),
        ):
            original = copy.deepcopy(self.manifest)
            mutation(self.manifest["bindings"])
            self.manifest_write()
            with self.assertRaises(ValueError):
                compiler.verify_media(self.compile(), self.course_dir)
            self.manifest = original

    def test_inventory_paths_cannot_escape_media_root(self):
        self.manifest["files"][0]["path"] = "../outside.mp4"
        self.manifest_write()
        with self.assertRaisesRegex(ValueError, "Invalid bound media path"):
            compiler.verify_media(self.compile(), self.course_dir)

    def test_failed_publication_does_not_write_generated_catalogue_or_transcript(self):
        (self.course_dir / "video-index.json").unlink()
        for filename in ("course.json", "all-lesson-transcripts.txt"):
            (self.course_dir / filename).write_text(
                "existing publication", encoding="utf-8"
            )
        with patch.object(compiler, "COURSE", self.course_dir), patch.object(
            sys, "argv", ["build_course.py", "--verify-media"]
        ):
            with self.assertRaises(ValueError):
                compiler.main()
        for filename in ("course.json", "all-lesson-transcripts.txt"):
            self.assertEqual(
                (self.course_dir / filename).read_text(encoding="utf-8"),
                "existing publication",
            )


if __name__ == "__main__":
    unittest.main()
