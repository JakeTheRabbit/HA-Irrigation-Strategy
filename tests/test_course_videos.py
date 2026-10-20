"""Production regressions: stale narration, frame boundaries, PCM and source captions."""

import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "course_videos", ROOT / "scripts" / "build_course_videos.py"
)
video = importlib.util.module_from_spec(spec)
spec.loader.exec_module(video)


class CourseVideoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.lesson = {
            "id": "A3",
            "title": "Sponge",
            "slides": [
                {
                    "id": "A3-05",
                    "title": "Recall",
                    "narration": "What changed?\n\nOnly the note changed.",
                }
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def make_inputs(self, lesson=None, frames=37):
        units = video.source_units(lesson or self.lesson, self.root)
        for index, unit in enumerate(units):
            receipt, audio, picture = (
                Path(unit[k]) for k in ("receipt", "audio", "picture")
            )
            audio.parent.mkdir(parents=True, exist_ok=True)
            picture.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(audio), "wb") as output:
                output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                output.writeframes(struct.pack("<h", index + 1) * (frames * 1000))
            record = {
                "id": unit["id"],
                "paragraph": unit["paragraph"],
                "lesson": unit["lesson"],
                "slide": unit["slide"],
                "source": unit["text"],
                "frames": frames,
                "duration": frames / 24,
                "speech_duration": (frames - 2) / 24,
            }
            receipt.write_text(json.dumps(record), encoding="utf-8")
            picture.write_bytes(
                b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 854, 480)
            )
        return units

    def test_source_hash_uses_exact_raw_slide_narration_and_blank_lines(self):
        self.assertEqual(
            video.source_hash(self.lesson),
            video.digest("What changed?\n\nOnly the note changed."),
        )
        copy = {
            **self.lesson,
            "slides": [
                dict(
                    self.lesson["slides"][0],
                    narration="What changed? Only the note changed.",
                )
            ],
        }
        self.assertNotEqual(video.source_hash(copy), video.source_hash(self.lesson))

    def test_five_pilots_are_paragraph_units_and_nonpilots_are_whole_slides(self):
        self.assertEqual(len(video.source_units(self.lesson, self.root)), 2)
        regular = {**self.lesson, "id": "D1"}
        self.assertEqual(len(video.source_units(regular, self.root)), 1)

    def test_repeated_setup_slide_ids_have_separate_paths_and_unit_keys(self):
        lessons = [
            {
                "id": lid,
                "slides": [{"id": "1", "title": "Start", "narration": "Start."}],
            }
            for lid in ("C3", "C4")
        ]
        first, second = [video.source_units(lesson, self.root)[0] for lesson in lessons]
        for key in ("id", "audio", "receipt", "picture"):
            self.assertNotEqual(first[key], second[key])
        self.assertEqual(
            Path(first["picture"]).relative_to(self.root).as_posix(), "slides/C3/1.png"
        )

    def test_stale_voice_text_is_rejected_even_with_a_valid_generation_hash(self):
        unit = self.make_inputs()[0]
        receipt = video.read_json(unit["receipt"])
        receipt["source"] = "Old source."
        receipt["source_sha256"] = "valid-but-unrelated-generation-hash"
        Path(unit["receipt"]).write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Stale narration"):
            video.validate_unit(unit)

    def test_pcm_sample_count_must_match_receipt_frame_count(self):
        unit = self.make_inputs()[0]
        receipt = video.read_json(unit["receipt"])
        receipt["frames"] += 1
        Path(unit["receipt"]).write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "PCM/frame"):
            video.validate_unit(unit)

    def test_receipt_duration_cannot_drift_from_frame_count(self):
        unit = self.make_inputs()[0]
        receipt = video.read_json(unit["receipt"])
        receipt["duration"] += 0.1
        Path(unit["receipt"]).write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duration/frame"):
            video.validate_unit(unit)

    def test_retrieval_hold_stays_on_question_and_answer_boundary_is_frame_exact(self):
        rows = video.make_timeline([video.validate_unit(u) for u in self.make_inputs()])
        self.assertEqual(rows[0]["frames"], 37 + 8 * 24)
        self.assertEqual(rows[1]["start_frame"], 37 + 8 * 24)
        self.assertEqual(rows[-1]["end_frame"], 37 * 2 + 8 * 24)
        self.assertEqual(rows[1]["hold_seconds"], 0)
        self.assertEqual(
            set(video.HOLDS), {"A1-04-p02", "A2-01-p02", "A3-05-p01", "B1-06-p01"}
        )

    def test_concatenated_pcm_has_original_samples_then_silence_then_answer(self):
        rows = video.make_timeline([video.validate_unit(u) for u in self.make_inputs()])
        out = self.root / "whole.wav"
        samples = video.concatenate_pcm(rows, out)
        self.assertEqual(samples, rows[-1]["end_frame"] * 1000)
        with wave.open(str(out), "rb") as audio:
            self.assertEqual(audio.getnframes(), samples)
            raw = audio.readframes(samples)
        boundary = 37000 * 2
        self.assertEqual(raw[:boundary], b"\x01\x00" * 37000)
        self.assertEqual(
            raw[boundary : boundary + 8 * 24000 * 2], b"\0" * (8 * 24000 * 2)
        )
        self.assertEqual(raw[boundary + 8 * 24000 * 2 :], b"\x02\x00" * 37000)

    def test_picture_dimensions_must_match_native_video(self):
        unit = self.make_inputs()[0]
        Path(unit["picture"]).write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1920, 1080)
        )
        with self.assertRaisesRegex(ValueError, "854x480"):
            video.validate_unit(unit)

    def test_caption_source_words_retained_when_asr_misses_words(self):
        row = video.make_timeline([video.validate_unit(self.make_inputs()[1])])[0]
        words = [
            {"word": "Only", "start": 0.1, "end": 0.3},
            {"word": "changed.", "start": 1.0, "end": 1.2},
        ]
        captions, audit = video.caption_unit(row, words)
        self.assertEqual(
            " ".join(c[2].replace("\n", " ") for c in captions), row["text"]
        )
        self.assertEqual(audit["source_words_retained"], 4)
        self.assertIn("measured-asr", audit["timing"])
        self.assertTrue(
            all(0 <= a < b <= row["speech_duration"] for a, b, _ in captions)
        )

    def test_proportional_fallback_does_not_claim_measured_word_anchors(self):
        row = video.make_timeline([video.validate_unit(self.make_inputs()[1])])[0]
        _, audit = video.caption_unit(row)
        self.assertEqual(audit["timing"], "estimated-proportional-source-span")
        self.assertNotIn("exact_script_anchors", audit)

    def test_pause_caption_does_not_reveal_answer_or_overlap_speech(self):
        row = video.make_timeline([video.validate_unit(self.make_inputs()[0])])[0]
        captions, _ = video.caption_unit(row)
        self.assertEqual(captions[-1][2], "[Pause and answer before continuing.]")
        self.assertGreaterEqual(captions[-1][0], row["voice_frames"] / 24)
        self.assertLess(captions[-1][1], row["end"])
        self.assertNotIn("Only", captions[-1][2])

    def test_vtt_offsets_preserved_and_overlaps_rejected(self):
        vtt, srt = self.root / "out.vtt", self.root / "out.srt"
        video.write_captions([(61.125, 62.5, "Text")], vtt, srt)
        self.assertIn("00:01:01.125 --> 00:01:02.500", vtt.read_text())
        self.assertIn("00:01:01,125 --> 00:01:02,500", srt.read_text())
        with self.assertRaisesRegex(ValueError, "overlap"):
            video.write_captions([(0, 2, "a"), (1, 3, "b")], vtt, srt)

    def test_exact_frame_probe_and_required_final_audio_are_enforced(self):
        probe = {
            "video": {"width": 854, "height": 480, "fps": 24, "nb_frames": 101},
            "audio": {"sample_rate": 48000, "channels": 1},
            "duration": 101 / 24,
        }
        video.validate_probe(probe, 101)
        with self.assertRaisesRegex(ValueError, "frame mismatch"):
            video.validate_probe(probe, 102)
        probe["audio"]["sample_rate"] = 24000
        with self.assertRaisesRegex(ValueError, "48000"):
            video.validate_probe(probe, 101)
        with self.assertRaisesRegex(ValueError, "unexpectedly"):
            video.validate_probe(probe, 101, audio=False)

    def test_exact_group_membership_and_real_route_ids(self):
        groups = {g["id"]: g for g in video.GROUPS}
        self.assertEqual(
            groups["foundations"]["lessons"], [f"A{i}" for i in range(1, 7)]
        )
        self.assertEqual(
            groups["watering-equipment"]["lessons"], ["B1", "B2", "B3", "B4", "C1"]
        )
        self.assertEqual(
            groups["setup-pi"]["lessons"], ["C2a", "C3", "C4", "C5", "C6", "C7"]
        )
        self.assertEqual(
            groups["setup-x86"]["lessons"], ["C2b", "C3", "C4", "C5", "C6", "C7"]
        )
        self.assertEqual(
            groups["operations"]["lessons"], [f"D{i}" for i in range(1, 7)]
        )
        self.assertEqual(groups["setup-pi"]["routes"], ["builder-pi"])
        self.assertEqual(groups["setup-x86"]["routes"], ["builder-x86"])
        self.assertEqual(
            set(groups["foundations"]["routes"]),
            {"operator", "builder-pi", "builder-x86"},
        )
        self.assertEqual(video.EDITION, "2026-10-20-r4")
        self.assertEqual(video.CACHE_VERSION, "20261020r4")

    def make_capture(self):
        regular = {
            "id": "C3",
            "slides": [
                {
                    "id": "1",
                    "title": "First",
                    "narration": "Current text.",
                    "visual": {
                        "type": "process",
                        "labels": ["Read → check", "Coco"],
                        "values": [35, 39],
                    },
                }
            ],
        }
        unit = self.make_inputs(regular)[0]
        unit["picture"] = str(Path(unit["picture"]).resolve())
        modules = self.root / "learn" / "course" / "modules"
        modules.mkdir(parents=True)
        video.write_json(modules / "setup.json", [regular])
        renderer = modules.parent.parent / "visuals.mjs"
        renderer.write_text("current renderer", encoding="utf-8")
        binding = {
            "renderer_sha256": video.digest(renderer.read_bytes()),
            "frames": [
                {
                    "lesson": "C3",
                    "slide": "1",
                    "file": str(Path(unit["picture"]).relative_to(self.root)),
                    "narration_sha256": video.digest(unit["text"]),
                    "visual_input_sha256": video.digest(
                        json.dumps(
                            regular["slides"][0]["visual"],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    ),
                    "png_sha256": video.digest(Path(unit["picture"]).read_bytes()),
                    "asset_files": [],
                }
            ],
        }
        video.write_json(
            self.root / "visual-qa" / "academy-slide-bindings.json", binding
        )
        return unit, modules, binding

    def test_capture_receipt_binds_same_id_to_correct_lesson_and_exact_source(self):
        unit, modules, binding = self.make_capture()
        self.assertTrue(video.validate_capture(unit, self.root, modules))
        binding["frames"][0]["lesson"] = "C4"
        video.write_json(
            self.root / "visual-qa" / "academy-slide-bindings.json", binding
        )
        with self.assertRaisesRegex(ValueError, "Stale slide picture binding"):
            video.validate_capture(unit, self.root, modules)

    def test_capture_rejects_visual_changed_without_narration_or_png_changes(self):
        unit, modules, _ = self.make_capture()
        source = video.read_json(modules / "setup.json")
        source[0]["slides"][0]["visual"]["values"] = [35, 42]
        video.write_json(modules / "setup.json", source)
        with self.assertRaisesRegex(ValueError, "Stale slide picture visual input"):
            video.validate_capture(unit, self.root, modules)

    def test_capture_rejects_renderer_changed_without_narration_or_png_changes(self):
        unit, modules, _ = self.make_capture()
        (modules.parent.parent / "visuals.mjs").write_text(
            "changed renderer", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Stale slide picture renderer"):
            video.validate_capture(unit, self.root, modules)

    def test_group_chapters_include_all_slides_and_keep_repeated_ids_lesson_scoped(
        self,
    ):
        from types import SimpleNamespace

        mapping = {}
        for lid in ("C3", "C4"):
            lesson = {
                "id": lid,
                "title": lid,
                "slides": [
                    {"id": "1", "title": "First", "narration": "First."},
                    {"id": "2", "title": "Second", "narration": "Second."},
                ],
            }
            mapping[lid] = lesson
            rows = video.make_timeline(
                [video.validate_unit(u) for u in self.make_inputs(lesson, frames=12)]
            )
            whole = self.root / f"{lid}.wav"
            video.concatenate_pcm(rows, whole)
            entry = {
                "lesson": lid,
                "metadata": {
                    "source_sha256": video.source_hash(lesson),
                    "frames": 24,
                    "chapters": [
                        {"id": "1", "title": "First", "start": 0},
                        {"id": "2", "title": "Second", "start": 0.5},
                    ],
                },
                "source": "First.\n\nSecond.",
                "audio": str(whole),
                "picture": str(self.root / f"{lid}.mp4"),
                "captions": [[0.1, 0.3, "First."], [0.6, 0.8, "Second."]],
            }
            video.write_json(self.root / "reports" / f"{lid}-lesson.json", entry)
        builder = object.__new__(video.Builder)
        builder.root = self.root
        builder.args = SimpleNamespace(
            edition=video.EDITION, cache_version=video.CACHE_VERSION
        )
        builder.tool = SimpleNamespace(probe=lambda *args: None)
        builder.picture_core = lambda *args: self.root / "picture.mp4"
        builder.final = lambda *args: None
        (self.root / "captions").mkdir()
        result = builder.group(
            {"id": "two", "title": "Two", "lessons": ["C3", "C4"]}, mapping
        )
        self.assertEqual(
            [(c["lesson"], c["id"]) for c in result["chapters"]],
            [("C3", "1"), ("C3", "2"), ("C4", "1"), ("C4", "2")],
        )
        self.assertEqual([c["start"] for c in result["chapters"]], [0, 0.5, 1, 1.5])
        self.assertEqual(result["frames"], 48)
        self.assertIn(
            "00:00:01.100 --> 00:00:01.300",
            (self.root / "captions" / "group-two.vtt").read_text(),
        )

    def make_motion(self):
        lesson = {
            "id": "B1",
            "slides": [
                {
                    "id": "B1-05",
                    "title": "Edit",
                    "narration": "First.\n\nSecond.\n\nChanges to percent.",
                }
            ],
        }
        row = video.validate_unit(self.make_inputs(lesson, frames=12)[2])
        modules = self.root / "learn" / "course" / "modules"
        modules.mkdir(parents=True)
        renderer = modules.parent.parent / "pilot-frames.mjs"
        renderer.write_text("renderer")
        folder = self.root / "motion" / row["id"]
        (folder / "frames").mkdir(parents=True)
        words = {
            "words": [
                {"word": "Changes", "start": 0.05, "end": 0.1},
                {"word": "to", "start": 0.15, "end": 0.2},
                {"word": "percent.", "start": 0.25, "end": 0.3},
            ],
            "measured": True,
        }
        video.write_json(folder / "word-anchors.json", words)
        hashes = []
        for index in range(12):
            name = f"frame_{index:04}.png"
            data = Path(row["picture"]).read_bytes() + bytes([0 if index < 6 else 1])
            (folder / "frames" / name).write_bytes(data)
            hashes.append({"file": name, "sha256": video.digest(data)})
        video.write_json(folder / "frame-hashes.json", hashes)
        ready = {
            "id": row["id"],
            "status": "ready",
            "fps": 24,
            "frames": 12,
            "frame_count": 12,
            "width": 854,
            "height": 480,
            "first_frame": 0,
            "last_frame": 11,
            "duration": 0.5,
            "audio_sha256": video.digest(Path(row["audio"]).read_bytes()),
            "audio_receipt_sha256": video.digest(Path(row["receipt"]).read_bytes()),
            "source_sha256": video.digest(row["text"]),
            "renderer_sha256": video.digest(renderer.read_bytes()),
            "movement_start_frame": 1,
            "movement_end_frame": 7,
            "word_clause_start": 0.05,
            "word_clause_end": 0.3,
            "saved_value": 35,
            "initial_value": 35,
            "final_value": 39,
            "word_anchors": "word-anchors.json",
            "frame_hashes": "frame-hashes.json",
            "frames_manifest_sha256": video.digest(
                json.dumps(hashes, separators=(",", ":"))
            ),
        }
        video.write_json(folder / "ready.json", ready)
        return row, modules, folder, ready

    def test_motion_is_required_instead_of_silently_falling_back_to_still(self):
        row = {"id": "B1-05-p03"}
        with self.assertRaisesRegex(FileNotFoundError, "Required voice-aligned"):
            video.validate_motion(row, self.root, self.root)
        self.assertIsNone(
            video.validate_motion({"id": "A3-01-p01"}, self.root, self.root)
        )

    def test_motion_binds_exact_audio_source_renderer_and_all_frames(self):
        row, modules, folder, ready = self.make_motion()
        motion = video.validate_motion(row, self.root, modules)
        self.assertEqual(Path(motion["directory"]), folder / "frames")
        ready["audio_sha256"] = "stale"
        video.write_json(folder / "ready.json", ready)
        with self.assertRaisesRegex(ValueError, "Stale motion"):
            video.validate_motion(row, self.root, modules)

    def test_motion_rejects_extra_trailing_frames_and_changed_png(self):
        row, modules, folder, ready = self.make_motion()
        extra = folder / "frames" / "frame_0012.png"
        extra.write_bytes(b"stale")
        with self.assertRaisesRegex(ValueError, "trailing"):
            video.validate_motion(row, self.root, modules)
        extra.unlink()
        (folder / "frames" / "frame_0005.png").write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "frame hash|native|PNG"):
            video.validate_motion(row, self.root, modules)

    def test_motion_picture_uses_sequence_and_only_trims_a_single_extra_frame(self):
        from types import SimpleNamespace

        builder = object.__new__(video.Builder)
        builder.root = self.root
        builder.args = SimpleNamespace(modules=self.root)
        builder.cached = lambda *args: False
        builder.complete = lambda *args, **kwargs: None
        row = {
            "id": "B1-05-p03",
            "frames": 12,
            "motion": {"signature": "current", "directory": str(self.root)},
        }
        calls = []

        def call(name, argv, key):
            calls.append(name)
            output = Path(argv[argv.index("-o") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"movie")
            count = 13 if name == "sequence.py" else 12
            return {
                "probe": {
                    "video": {
                        "width": 854,
                        "height": 480,
                        "fps": 24,
                        "nb_frames": count,
                    }
                }
            }

        builder.tool = SimpleNamespace(call=call)
        result = builder.still(row)
        self.assertEqual(calls, ["sequence.py", "cut.py"])
        self.assertTrue(result.exists())

    def test_skill_always_records_dry_run_then_actual_and_preserves_error(self):
        skill = video.Skill(self.root, self.root)
        ok = type(
            "Result", (), {"stdout": '{"status":"ok"}', "stderr": "", "returncode": 0}
        )()
        with patch.object(video.subprocess, "run", return_value=ok) as run:
            skill.call("insert.py", ["image.png"], "one")
        self.assertIn("--dry-run", run.call_args_list[0].args[0])
        self.assertNotIn("--dry-run", run.call_args_list[1].args[0])
        self.assertTrue((self.root / "reports" / "one-plan.json").exists())
        bad = type(
            "Result",
            (),
            {
                "stdout": '{"error":{"message":"exact diagnostic"}}',
                "stderr": "",
                "returncode": 1,
            },
        )()
        with patch.object(video.subprocess, "run", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "exact diagnostic"):
                skill.call("insert.py", [], "bad")


if __name__ == "__main__":
    unittest.main()
