"""Regression checks for narration/visual mismatches and accumulating edit drift."""

import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pilot_timing", ROOT / "scripts/pilot_timing.py")
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


class PilotTimingTests(unittest.TestCase):
    def setUp(self):
        self.lessons = [{"id": "A1", "slides": [
            {"id": "A1-01", "narration": "Water arrives.\n\nSome water drains."}]}]
        self.cues = [
            {"id": "A1-01-p01", "lesson": "A1", "scene": "A1-01", "paragraph": 0, "text": "Water arrives."},
            {"id": "A1-01-p02", "lesson": "A1", "scene": "A1-01", "paragraph": 1, "text": "Some water drains."}]
        self.records = [{**c, "frames": 101, "duration": 101/24} for c in self.cues]

    def test_picture_cannot_bind_to_another_paragraph(self):
        self.cues[0]["text"] = "Some water drains."
        with self.assertRaisesRegex(ValueError, "source"):
            timing.plan(self.lessons, self.cues, self.records)

    def test_missing_or_repeated_visual_is_rejected(self):
        for cues in (self.cues[:1], self.cues + self.cues[:1]):
            with self.assertRaisesRegex(ValueError, "coverage|duplicate"):
                timing.plan(self.lessons, cues, self.records)

    def test_stale_voice_take_is_rejected(self):
        self.records[1]["text"] = "Old narration."
        with self.assertRaisesRegex(ValueError, "source"):
            timing.plan(self.lessons, self.cues, self.records)

    def test_shared_frame_boundaries_do_not_round_away_time(self):
        result = timing.plan(self.lessons, list(reversed(self.cues)), self.records)
        self.assertEqual([x["start_frame"] for x in result], [0, 101])
        self.assertEqual([x["end_frame"] for x in result], [101, 202])
        self.assertEqual(result[-1]["end"], 202/24)

    def test_bad_frame_duration_is_rejected(self):
        self.records[1]["duration"] += .2
        with self.assertRaisesRegex(ValueError, "frame"):
            timing.plan(self.lessons, self.cues, self.records)


if __name__ == "__main__":
    unittest.main()
