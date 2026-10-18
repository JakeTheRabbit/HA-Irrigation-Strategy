"""Assemble the 24-lesson course with frame-bound pictures and continuous PCM.

All media operations go through ffmpeg-skill scripts (dry-run JSON then actual).
Never joins individually encoded narration AAC streams. Source files are read-only.
Example:
  python scripts/build_course_videos.py --production "C:/Content/..." --plan-only
  python scripts/build_course_videos.py --production "C:/Content/..." --lessons A3 --skip-groups
  python scripts/build_course_videos.py --production "C:/Content/..."
"""

import argparse
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
import wave

FPS, RATE, WIDTH, HEIGHT = 24, 24000, 854, 480
SAMPLES_PER_FRAME = RATE // FPS
PILOTS = {"A1", "A2", "A3", "B1", "C1"}
HOLDS = {"A1-04-p02": 8, "A2-01-p02": 8, "A3-05-p01": 8, "B1-06-p01": 8}
EDITION = "2026-10-19-r3"
CACHE_VERSION = "20261019r3"
VOICE = "Kokoro af_heart · source-matched local narration"
GROUPS = [
    {
        "id": "foundations",
        "title": "Foundations: water, roots and readings",
        "description": "Understand water content, drainage, EC and the limits of a sensor.",
        "routes": ["operator", "builder-pi", "builder-x86"],
        "lessons": [f"A{i}" for i in range(1, 7)],
    },
    {
        "id": "watering-equipment",
        "title": "Watering strategy and equipment",
        "description": "Read the graph, understand phases and delivery, then plan one working zone.",
        "routes": ["operator", "builder-pi", "builder-x86"],
        "lessons": ["B1", "B2", "B3", "B4", "C1"],
    },
    {
        "id": "setup-pi",
        "title": "Setup: Raspberry Pi route",
        "description": "Follow the Raspberry Pi host route, then the shared setup and verification lessons.",
        "routes": ["builder-pi"],
        "lessons": ["C2a", "C3", "C4", "C5", "C6", "C7"],
    },
    {
        "id": "setup-x86",
        "title": "Setup: x86 route",
        "description": "Follow the dedicated x86 host route, then the shared setup and verification lessons.",
        "routes": ["builder-x86"],
        "lessons": ["C2b", "C3", "C4", "C5", "C6", "C7"],
    },
    {
        "id": "operations",
        "title": "Operate, investigate and maintain",
        "description": "Use evidence to operate the system, investigate problems and make bounded changes.",
        "routes": ["operator", "builder-pi", "builder-x86"],
        "lessons": [f"D{i}" for i in range(1, 7)],
    },
]


def digest(data):
    return hashlib.sha256(
        data.encode("utf-8") if isinstance(data, str) else data
    ).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def source_hash(lesson):
    return digest("\n\n".join(s["narration"] for s in lesson["slides"]))


def source_units(lesson, production):
    """The five pilots use paragraph takes; all other lessons use slide takes."""
    root = Path(production)
    result = []
    for slide in lesson["slides"]:
        sid = str(slide["id"])
        texts = (
            slide["narration"].split("\n\n")
            if lesson["id"] in PILOTS
            else [slide["narration"]]
        )
        for number, text in enumerate(texts, 1):
            pilot = lesson["id"] in PILOTS
            uid = f"{sid}-p{number:02}" if pilot else f"{lesson['id']}--{sid}"
            stem = root / "narration" / (uid if pilot else f"{lesson['id']}/{sid}")
            result.append(
                {
                    "id": uid,
                    "lesson": lesson["id"],
                    "slide": sid,
                    "title": slide["title"],
                    "text": text,
                    "paragraph": number - 1 if pilot else None,
                    "audio": str(stem.with_suffix(".wav")),
                    "receipt": str(stem.with_suffix(".json")),
                    "picture": (
                        str(root / "frames" / f"{uid}.png")
                        if pilot
                        else str(root / "slides" / lesson["id"] / f"{sid}.png")
                    ),
                    "hold_seconds": HOLDS.get(uid, 0),
                }
            )
    return result


def load_lessons(modules):
    normal, pilots = {}, {}
    for path in sorted(Path(modules).glob("*.json")):
        target = pilots if path.stem == "pilots" else normal
        for lesson in read_json(path):
            if lesson["id"] in target:
                raise ValueError(f"Duplicate lesson: {lesson['id']}")
            target[lesson["id"]] = lesson
    # Pilot objects deliberately replace their older foundation/setup versions.
    normal.update(pilots)
    order = (
        [f"A{i}" for i in range(1, 7)]
        + [f"B{i}" for i in range(1, 5)]
        + ["C1", "C2a", "C2b", "C3", "C4", "C5", "C6", "C7"]
        + [f"D{i}" for i in range(1, 7)]
    )
    missing = set(order) - set(normal)
    if missing:
        raise ValueError("Missing course lessons: " + ", ".join(sorted(missing)))
    return [normal[key] for key in order]


def validate_unit(unit):
    record = read_json(unit["receipt"])
    expected = unit["text"]
    if record.get("text", record.get("source")) != expected:
        raise ValueError(f"Stale narration source: {unit['id']}")
    if unit["lesson"] in PILOTS and (
        record.get("id") != unit["id"] or record.get("paragraph") != unit["paragraph"]
    ):
        raise ValueError(f"Wrong narration paragraph: {unit['id']}")
    if record.get("lesson") != unit["lesson"]:
        raise ValueError(f"Wrong narration lesson: {unit['id']}")
    actual_scene = record.get("scene", record.get("slide"))
    if str(actual_scene) != unit["slide"]:
        raise ValueError(f"Wrong narration slide: {unit['id']}")
    with wave.open(unit["audio"], "rb") as audio:
        if (
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getframerate(),
            audio.getcomptype(),
        ) != (1, 2, RATE, "NONE"):
            raise ValueError(f"Expected mono PCM16 at {RATE} Hz: {unit['id']}")
        samples = audio.getnframes()
    frames = record.get("frames")
    if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
        raise ValueError(f"Invalid frame count: {unit['id']}")
    if samples != frames * SAMPLES_PER_FRAME:
        raise ValueError(
            f"PCM/frame mismatch: {unit['id']}: {samples} samples, {frames} frames"
        )
    if (
        not math.isfinite(record.get("duration", -1))
        or abs(record.get("duration", -1) - frames / FPS) > 0.00001
    ):
        raise ValueError(f"Receipt duration/frame mismatch: {unit['id']}")
    speech = record.get("speech_duration")
    if not isinstance(speech, (int, float)) or not 0 < speech <= frames / FPS:
        raise ValueError(f"Invalid measured speech duration: {unit['id']}")
    # Reading headers is sufficient to reject stale-size PNGs without an imaging dependency.
    png = Path(unit["picture"]).read_bytes()
    if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24:
        raise ValueError(f"Unreadable PNG: {unit['id']}")
    if (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")) != (
        WIDTH,
        HEIGHT,
    ):
        raise ValueError(f"Expected {WIDTH}x{HEIGHT} picture: {unit['id']}")
    hold_frames = round(unit["hold_seconds"] * FPS)
    return {
        **unit,
        "speech_duration": speech,
        "voice_frames": frames,
        "frames": frames + hold_frames,
        "audio_sha256": digest(Path(unit["audio"]).read_bytes()),
        "picture_sha256": digest(png),
        "receipt_sha256": digest(Path(unit["receipt"]).read_bytes()),
    }


def validate_capture(unit, production, modules):
    """Reject pictures from a different script/asset revision before encoding."""
    production, modules = Path(production), Path(modules)
    learn = modules.parent.parent
    if unit["lesson"] in PILOTS:
        manifest = read_json(production / "visual-qa" / "frame-hashes.json")
        entries = manifest if isinstance(manifest, list) else manifest.get("frames", [])
        matches = [e for e in entries if e["file"] == Path(unit["picture"]).name]
        cues = [
            c
            for name in ("a1", "other")
            for c in read_json(modules.parent / f"pilot-cues-{name}.json")
        ]
        cue = next((c for c in cues if c["id"] == unit["id"]), None)
        if not cue or cue["text"] != unit["text"]:
            raise ValueError("Stale pilot picture cue: " + unit["id"])
        expected = digest(json.dumps(cue, ensure_ascii=False, separators=(",", ":")))
        if len(matches) != 1 or matches[0].get("source_sha256") != expected:
            raise ValueError("Stale pilot picture binding: " + unit["id"])
        bound = matches[0]
        if bound.get("renderer_sha256") != digest(
            (learn / "pilot-frames.mjs").read_bytes()
        ):
            raise ValueError("Stale pilot picture renderer: " + unit["id"])
        png_hash = bound.get("sha256")
    else:
        manifest = read_json(production / "visual-qa" / "academy-slide-bindings.json")
        matches = [
            e
            for e in manifest["frames"]
            if e["lesson"] == unit["lesson"] and str(e["slide"]) == unit["slide"]
        ]
        if len(matches) != 1 or matches[0].get("narration_sha256") != digest(
            unit["text"]
        ):
            raise ValueError("Stale slide picture binding: " + unit["id"])
        bound = matches[0]
        if manifest.get("renderer_sha256") != digest(
            (learn / "visuals.mjs").read_bytes()
        ):
            raise ValueError("Stale slide picture renderer: " + unit["id"])
        current_slides = [
            slide
            for source_path in sorted(modules.glob("*.json"))
            for lesson in read_json(source_path)
            if lesson["id"] == unit["lesson"]
            for slide in lesson["slides"]
            if str(slide["id"]) == unit["slide"]
        ]
        if len(current_slides) != 1:
            raise ValueError("Current slide visual cannot be resolved: " + unit["id"])
        visual_hash = digest(
            json.dumps(
                current_slides[0]["visual"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        if bound.get("visual_input_sha256") != visual_hash:
            raise ValueError("Stale slide picture visual input: " + unit["id"])
        expected_path = (production / bound["file"]).resolve()
        if expected_path != Path(unit["picture"]).resolve():
            raise ValueError("Wrong slide picture path: " + unit["id"])
        png_hash = bound.get("png_sha256")
    if png_hash != digest(Path(unit["picture"]).read_bytes()):
        raise ValueError("Captured PNG changed after binding: " + unit["id"])
    for asset in bound.get("asset_files", []):
        path = Path(asset["file"])
        if not path.is_absolute():
            path = learn / path
        if digest(path.read_bytes()) != asset["sha256"]:
            raise ValueError("Captured illustration changed: " + unit["id"])
    return True


def validate_motion(row, production, modules):
    if row["id"] != "B1-05-p03":
        return None
    directory = Path(production) / "motion" / row["id"]
    receipt_path = directory / "ready.json"
    if not receipt_path.exists():
        raise FileNotFoundError(
            "Required voice-aligned threshold motion is missing: " + str(receipt_path)
        )
    ready = read_json(receipt_path)
    expected = row["voice_frames"]
    if row["frames"] != expected or row.get("hold_seconds", 0):
        raise ValueError("Threshold motion cannot contain an unaccounted hold")
    fields = {
        "id": row["id"],
        "status": "ready",
        "fps": FPS,
        "frames": expected,
        "frame_count": expected,
        "width": WIDTH,
        "height": HEIGHT,
        "first_frame": 0,
        "last_frame": expected - 1,
    }
    if any(ready.get(k) != value for k, value in fields.items()):
        raise ValueError(
            "Motion metadata/frame coverage differs from current narration"
        )
    learn = Path(modules).parent.parent
    hashes = {
        "audio_sha256": digest(Path(row["audio"]).read_bytes()),
        "audio_receipt_sha256": digest(Path(row["receipt"]).read_bytes()),
        "source_sha256": digest(row["text"]),
        "renderer_sha256": digest((learn / "pilot-frames.mjs").read_bytes()),
    }
    if any(ready.get(k) != value for k, value in hashes.items()):
        raise ValueError("Stale motion audio/source/renderer binding")
    if abs(ready.get("duration", -1) - expected / FPS) > 0.00001:
        raise ValueError("Motion duration differs from current narration")
    start, end = ready.get("movement_start_frame", -1), ready.get(
        "movement_end_frame", -1
    )
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not 0 <= start < end < expected
    ):
        raise ValueError("Motion movement clause is outside narration")
    if (
        ready.get("saved_value") != 35
        or ready.get("initial_value") != 35
        or ready.get("final_value") != 39
    ):
        raise ValueError(
            "Motion does not show the scripted 35 to 39 percent draft edit"
        )
    paths = {}
    for key, filename in (
        ("word_anchors", "word-anchors.json"),
        ("frame_hashes", "frame-hashes.json"),
    ):
        supplied = Path(ready.get(key, ""))
        if not supplied.is_absolute():
            supplied = directory / supplied
        if supplied.resolve() != (directory / filename).resolve():
            raise ValueError("Motion receipt references another production: " + key)
        paths[key] = supplied
    alignment = read_json(paths["word_anchors"])
    words = alignment.get("words", alignment.get("actual_voice_anchors"))
    if not isinstance(words, list) or not words or alignment.get("measured") is False:
        raise ValueError("Motion requires measured actual-voice word anchors")
    previous = -1
    for word in words:
        if (
            not word.get("word")
            or not 0
            <= word.get("start", -1)
            < word.get("end", -1)
            <= expected / FPS + 0.1
            or word["start"] < previous
        ):
            raise ValueError("Invalid actual-voice motion word anchors")
        previous = word["start"]

    def normalized(word):
        return re.sub(r"[^a-z-]", "", word["word"].lower())

    change = next((i for i, w in enumerate(words) if normalized(w) == "changes"), -1)
    to = next(
        (i for i, w in enumerate(words) if i > change and normalized(w) == "to"), -1
    )
    percent = next(
        (i for i, w in enumerate(words) if i > to and normalized(w) == "percent"), -1
    )
    if not 0 <= change < to < percent:
        raise ValueError("Actual voice lacks the motion changes-to-percent clause")
    expected_start = math.floor(words[change]["start"] * FPS + 0.5)
    expected_end = math.floor(words[percent]["end"] * FPS + 0.5)
    if (start, end) != (expected_start, expected_end):
        raise ValueError("Motion timing does not match actual voice word anchors")
    manifest = read_json(paths["frame_hashes"])
    if digest(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    ) != ready.get("frames_manifest_sha256"):
        raise ValueError("Motion frame manifest hash differs")
    expected_names = [f"frame_{index:04}.png" for index in range(expected)]
    images = directory / "frames"
    if (
        sorted(p.name for p in images.glob("frame_*.png")) != expected_names
        or len(manifest) != expected
    ):
        raise ValueError("Missing or stale trailing motion frames")
    for filename, record in zip(expected_names, manifest):
        if record.get("file") != filename or record.get("sha256") != digest(
            (images / filename).read_bytes()
        ):
            raise ValueError("Motion frame hash differs: " + filename)
    if manifest[0]["sha256"] == manifest[-1]["sha256"]:
        raise ValueError("Motion initial and final pictures do not change")
    return {
        "directory": str(images),
        "word_anchors": str(paths["word_anchors"]),
        "signature": digest(
            receipt_path.read_bytes()
            + paths["word_anchors"].read_bytes()
            + paths["frame_hashes"].read_bytes()
        ),
    }


def make_timeline(units):
    result, offset = [], 0
    for unit in units:
        frames = unit["frames"]
        result.append(
            {
                **unit,
                "start_frame": offset,
                "end_frame": offset + frames,
                "start": offset / FPS,
                "end": (offset + frames) / FPS,
            }
        )
        offset += frames
    return result


def concatenate_pcm(rows, output):
    """Copy each WAV's exact samples, then append explicit retrieval silence."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        total = 0
        for row in rows:
            with wave.open(row["audio"], "rb") as part:
                if (part.getnchannels(), part.getsampwidth(), part.getframerate()) != (
                    1,
                    2,
                    RATE,
                ):
                    raise ValueError("Incompatible PCM source: " + row["id"])
                samples = part.getnframes()
                if samples != row["voice_frames"] * SAMPLES_PER_FRAME:
                    raise ValueError("Source changed during PCM assembly: " + row["id"])
                target.writeframes(part.readframes(samples))
            padding = (row["frames"] - row["voice_frames"]) * SAMPLES_PER_FRAME
            target.writeframes(b"\0" * padding * 2)
            total += samples + padding
    if total != sum(row["frames"] for row in rows) * SAMPLES_PER_FRAME:
        raise ValueError("Concatenated PCM is not frame aligned")
    return total


def stamp(seconds, vtt=True):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}{'.' if vtt else ','}{ms % 1000:03}"


def normalize(word):
    return re.sub(r"[^a-z0-9]", "", word.lower().replace("liters", "litres"))


def caption_unit(row, words=None):
    """Retain script words; ASR supplies measured anchors, never replacement copy."""
    source = row["text"].split()
    speech = row["speech_duration"]
    audit = {
        "id": row["id"],
        "source_words_retained": len(source),
        "timing": (
            "measured-asr-with-interpolated-unmatched-script"
            if words
            else "estimated-proportional-source-span"
        ),
    }
    if words:
        words = [w for w in words if 0 <= w["start"] < speech and w["end"] > w["start"]]
        if not words:
            raise ValueError("ASR has no words in measured speech: " + row["id"])
        matcher = difflib.SequenceMatcher(
            None,
            [normalize(w) for w in source],
            [normalize(w["word"]) for w in words],
            autojunk=False,
        )
        anchors = {-1: 0, len(source): min(speech, words[-1]["end"] + 0.1)}
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                anchors[block.a + k] = words[block.b + k]["start"]
        starts = []
        for index in range(len(source)):
            if index in anchors:
                starts.append(anchors[index])
            else:
                low = max(k for k in anchors if k < index)
                high = min(k for k in anchors if k > index)
                starts.append(
                    anchors[low]
                    + (anchors[high] - anchors[low]) * (index - low) / (high - low)
                )
        stop = anchors[len(source)]
        audit.update(
            asr_match_ratio=round(matcher.ratio(), 4),
            exact_script_anchors=len(anchors) - 2,
        )
    else:
        # Explicit opt-in only. These are not represented as measured word anchors.
        weights = [max(1, len(word)) for word in source]
        denominator = sum(weights)
        starts, offset = [], 0
        for weight in weights:
            starts.append(speech * offset / denominator)
            offset += weight
        stop = speech
    captions, index = [], 0
    while index < len(source):
        end = index + 1
        while (
            end < len(source)
            and end - index < 9
            and starts[end] - starts[index] < 4
            and not re.search(r"[.!?]$", source[end - 1])
        ):
            end += 1
        start = starts[index]
        finish = starts[end] if end < len(source) else stop
        # Remove a tiny cue gap only where possible; never overlap another source span.
        finish = min(speech, finish)
        if finish <= start:
            raise ValueError("Non-monotonic caption anchors: " + row["id"])
        text = "\n".join(
            textwrap.wrap(
                " ".join(source[index:end]),
                44,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
        captions.append((row["start"] + start, row["start"] + finish, text))
        index = end
    if row.get("hold_seconds"):
        captions.append(
            (
                row["start"] + row["voice_frames"] / FPS,
                row["end"] - 0.05,
                "[Pause and answer before continuing.]",
            )
        )
    return captions, audit


def write_captions(captions, vtt, srt):
    for index, (start, end, _) in enumerate(captions):
        if not 0 <= start < end or (
            index and captions[index - 1][1] > start + 0.000001
        ):
            raise ValueError("Caption cues overlap or have invalid timing")
    Path(vtt).write_text(
        "WEBVTT\n\n"
        + "\n\n".join(f"{stamp(a)} --> {stamp(b)}\n{text}" for a, b, text in captions)
        + "\n",
        encoding="utf-8",
    )
    Path(srt).write_text(
        "\n\n".join(
            f"{i+1}\n{stamp(a,False)} --> {stamp(b,False)}\n{text}"
            for i, (a, b, text) in enumerate(captions)
        )
        + "\n",
        encoding="utf-8",
    )


def validate_probe(probe, frames, audio=True):
    video = probe.get("video") or {}
    if (
        video.get("width"),
        video.get("height"),
        video.get("fps"),
        video.get("nb_frames"),
    ) != (WIDTH, HEIGHT, FPS, frames):
        raise ValueError(
            f"Video frame mismatch: expected {frames} frames at {WIDTH}x{HEIGHT}/{FPS}, got {video}"
        )
    if audio:
        track = probe.get("audio") or {}
        if track.get("channels") != 1 or track.get("sample_rate") != 48000:
            raise ValueError("Final audio must be mono at 48000 Hz")
        if abs(probe.get("duration", 0) - frames / FPS) > 0.1:
            raise ValueError(
                "Final container duration differs from exact frame timeline"
            )
    elif probe.get("audio"):
        raise ValueError("Picture core unexpectedly contains audio")


class Skill:
    def __init__(self, root, scripts, timeout=3600):
        self.root, self.scripts, self.timeout = Path(root), Path(scripts), timeout
        self.environment = {
            **os.environ,
            "FFMPEG_SKILL_NO_OVERWRITE": "1",
            "PYTHONIOENCODING": "utf-8",
        }

    def call(self, name, argv, key, writing=True):
        doc = None
        for dry in [True, False] if writing else [False]:
            command = [
                sys.executable,
                str(self.scripts / name),
                *map(str, argv),
                "--timeout",
                str(self.timeout),
                *(["--dry-run"] if dry else []),
                "--json",
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=self.environment,
                timeout=self.timeout + 60,
            )
            base = self.root / "reports" / f"{key}{'-plan' if dry else ''}"
            base.parent.mkdir(parents=True, exist_ok=True)
            base.with_suffix(".json").write_text(result.stdout, encoding="utf-8")
            base.with_suffix(".log").write_text(result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(
                    f"{name} {key}: {result.stdout[-4000:]}\n{result.stderr[-2000:]}"
                )
            doc = json.loads(result.stdout)
            if doc.get("status") == "failed":
                raise RuntimeError(
                    json.dumps(doc.get("error", doc), ensure_ascii=False)
                )
        return doc

    def probe(self, path, key):
        doc = self.call("probe.py", [path], key, writing=False)
        return doc.get("probe", doc)


class Builder:
    def __init__(self, args):
        self.args, self.root = args, args.production.resolve()
        self.tool = Skill(self.root, args.skill, args.tool_timeout)
        self.model = None
        for name in (
            "reports",
            "work",
            "projects",
            "exports/lessons",
            "exports/groups",
            "captions",
            "public-media/lessons",
            "public-media/groups",
        ):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def cached(self, key, signature, output):
        receipt = self.root / "reports" / f"{key}-complete.json"
        return (
            output.exists()
            and receipt.exists()
            and read_json(receipt).get("signature") == signature
            and read_json(receipt).get("output_sha256") == digest(output.read_bytes())
        )

    def complete(self, key, signature, output, **extra):
        write_json(
            self.root / "reports" / f"{key}-complete.json",
            {
                "signature": signature,
                "output_sha256": digest(output.read_bytes()),
                **extra,
            },
        )

    @staticmethod
    def overwrite(path):
        return ["--overwrite"] if path.exists() else []

    def alignment(self, row):
        if row.get("motion"):
            anchors = read_json(row["motion"]["word_anchors"])
            return anchors.get("words", anchors.get("actual_voice_anchors"))
        path = self.root / "reports" / f"{row['id']}-asr.json"
        signature = digest(
            row["audio_sha256"] + "|" + self.args.asr_model + "|cpu-int8|beam3|words-r3"
        )
        if path.exists() and read_json(path).get("signature") == signature:
            return read_json(path)["words"]
        if self.model is None:
            from faster_whisper import WhisperModel

            self.model = WhisperModel(
                self.args.asr_model,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                num_workers=1,
            )
        segments, details = self.model.transcribe(
            row["audio"],
            language="en",
            word_timestamps=True,
            beam_size=3,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        words = [
            {"word": word.word.strip(), "start": word.start, "end": word.end}
            for segment in segments
            for word in segment.words or []
        ]
        if not words:
            raise ValueError("No recognized speech: " + row["id"])
        write_json(
            path,
            {
                "signature": signature,
                "words": words,
                "duration": details.duration,
                "model": self.args.asr_model,
                "measured": True,
            },
        )
        return words

    def still(self, row):
        if row["id"] == "B1-05-p03":
            return self.motion_picture(row)
        signature = digest(
            f"insert-r3|{row['picture_sha256']}|{row['frames']}|{WIDTH}|{HEIGHT}|{FPS}"
        )
        output = self.root / "work" / "pictures" / f"{signature}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        if not self.cached(signature, signature, output):
            result = self.tool.call(
                "insert.py",
                [
                    row["picture"],
                    "--duration",
                    row["frames"] / FPS,
                    "--width",
                    WIDTH,
                    "--height",
                    HEIGHT,
                    "--fps",
                    FPS,
                    "--preset",
                    "fast",
                    "--quality",
                    18,
                    "-o",
                    output,
                    *self.overwrite(output),
                ],
                signature + "-insert",
            )
            validate_probe(result["probe"], row["frames"], audio=False)
            self.complete(signature, signature, output)
        return output

    def motion_picture(self, row):
        motion = row.get("motion") or validate_motion(row, self.root, self.args.modules)
        signature = digest(motion["signature"] + "|sequence-24fps-r3")
        output = self.root / "work" / "pictures" / f"{signature}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        if not self.cached(signature, signature, output):
            result = self.tool.call(
                "sequence.py",
                [
                    "--dir",
                    motion["directory"],
                    "--pattern",
                    "frame_%04d.png",
                    "--fps",
                    FPS,
                    "--width",
                    WIDTH,
                    "--height",
                    HEIGHT,
                    "--preset",
                    "fast",
                    "--quality",
                    18,
                    "-o",
                    output,
                    *self.overwrite(output),
                ],
                row["id"] + "-motion",
            )
            actual = (result.get("probe", {}).get("video") or {}).get("nb_frames")
            if actual == row["frames"] + 1:
                trimmed = output.with_name(signature + "-trimmed.mp4")
                result = self.tool.call(
                    "cut.py",
                    [
                        output,
                        "--start",
                        0,
                        "--end",
                        row["frames"] / FPS,
                        "--accurate",
                        "--quality",
                        18,
                        "-o",
                        trimmed,
                        *self.overwrite(trimmed),
                    ],
                    row["id"] + "-motion-trim",
                )
                validate_probe(result["probe"], row["frames"], audio=False)
                trimmed.replace(output)
            else:
                validate_probe(result["probe"], row["frames"], audio=False)
            self.complete(
                signature, signature, output, motion_signature=motion["signature"]
            )
        return output

    def picture_core(self, key, clips, frames):
        """Skill join synthesizes silence: strip it before a core is reused in groups."""
        signature = digest(
            json.dumps([(str(p), digest(p.read_bytes())) for p in clips])
            + "|picture-core-r3"
        )
        output = self.root / "work" / f"{key}-picture.mp4"
        if not self.cached(key + "-picture", signature, output):
            if len(clips) == 1:
                shutil.copy2(clips[0], output)
            else:
                joined = self.root / "work" / f"{key}-picture-joined.mp4"
                project = {
                    "output": str(joined),
                    "frame": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
                    "clips": [{"src": str(p)} for p in clips],
                    "transition": {"type": "none"},
                }
                path = self.root / "projects" / f"{key}-picture.json"
                write_json(path, project)
                self.tool.call(
                    "render.py",
                    [
                        path,
                        "--cache",
                        self.root / "work" / "skill-cache",
                        *self.overwrite(joined),
                    ],
                    key + "-picture-join",
                )
                # The skill exposes --no-audio via proxy.py; native size + CRF18 are explicit.
                result = self.tool.call(
                    "proxy.py",
                    [
                        joined,
                        "--no-audio",
                        "--width",
                        WIDTH,
                        "--fps",
                        FPS,
                        "--quality",
                        18,
                        "-o",
                        output,
                        *self.overwrite(output),
                    ],
                    key + "-picture-strip",
                )
                validate_probe(result["probe"], frames, audio=False)
            validate_probe(
                self.tool.probe(output, key + "-picture-probe"), frames, audio=False
            )
            self.complete(key + "-picture", signature, output)
        return output

    def final(self, key, picture, audio, captions, chapters, frames, kind):
        output = self.root / "exports" / kind / f"{key}.mp4"
        signature = digest(
            digest(picture.read_bytes())
            + digest(audio.read_bytes())
            + captions.read_text(encoding="utf-8")
            + json.dumps(chapters)
            + "|final-r3"
        )
        if not self.cached(key + "-final", signature, output):
            normalized = self.root / "work" / f"{key}-normalized.wav"
            norm_signature = digest(audio.read_bytes() + b"|normalize-pcm48k-r3")
            if not self.cached(key + "-pcm-normalize", norm_signature, normalized):
                self.tool.call(
                    "loudness.py",
                    [
                        audio,
                        "-I",
                        -16,
                        "--tp",
                        -1.5,
                        "--sample-rate",
                        48000,
                        "-o",
                        normalized,
                        *self.overwrite(normalized),
                    ],
                    key + "-pcm-normalize",
                )
                self.complete(key + "-pcm-normalize", norm_signature, normalized)
            project = {
                "output": str(output),
                "frame": {"width": WIDTH, "height": HEIGHT, "fps": FPS},
                "clips": [{"src": str(picture)}],
                "audio": {"replace": str(normalized)},
                "chapters": [{"at": c["start"], "title": c["title"]} for c in chapters],
            }
            path = self.root / "projects" / f"{key}-final.json"
            write_json(path, project)
            self.tool.call(
                "render.py",
                [
                    path,
                    "--cache",
                    self.root / "work" / "skill-cache",
                    *self.overwrite(output),
                ],
                key + "-final-render",
            )
            # PCM was normalized losslessly at 48kHz before its single final AAC encode.
            probe = self.tool.probe(output, key + "-final-probe")
            validate_probe(probe, frames)
            self.tool.call(
                "check.py",
                [output, "--platform", "youtube", "--lufs", -16, "--tp", -1],
                key + "-delivery-check",
                writing=False,
            )
            self.tool.call(
                "look.py",
                [
                    output,
                    "--tiles",
                    "3x2",
                    "-o",
                    self.root / "reports" / f"{key}-contact.png",
                    *self.overwrite(self.root / "reports" / f"{key}-contact.png"),
                ],
                key + "-contact",
            )
            self.complete(
                key + "-final",
                signature,
                output,
                frames=frames,
                duration=frames / FPS,
                look=str(self.root / "reports" / f"{key}-contact.png"),
            )
        else:
            validate_probe(self.tool.probe(output, key + "-resume-probe"), frames)
        target = self.root / "public-media" / kind / output.name
        shutil.copy2(output, target)
        shutil.copy2(captions, target.with_suffix(".vtt"))
        return output

    def lesson(self, lesson):
        lid = lesson["id"]
        units = source_units(lesson, self.root)
        missing = [
            u[k]
            for u in units
            for k in ("audio", "receipt", "picture")
            if not Path(u[k]).exists()
        ]
        if missing:
            raise FileNotFoundError(
                f"{lid}: {len(missing)} missing inputs; first: {missing[0]}"
            )
        for unit in units:
            validate_capture(unit, self.root, self.args.modules)
        rows = make_timeline([validate_unit(unit) for unit in units])
        for row in rows:
            if row["id"] == "B1-05-p03":
                row["motion"] = validate_motion(row, self.root, self.args.modules)
        write_json(self.root / "reports" / f"{lid}-timeline.json", rows)
        captions, audit, chapters, last = [], [], [], None
        for row in rows:
            words = self.alignment(row) if self.args.caption_mode == "asr" else None
            cue, check = caption_unit(row, words)
            captions.extend(cue)
            audit.append(check)
            if row["slide"] != last:
                chapters.append(
                    {
                        "id": row["slide"],
                        "slide": row["slide"],
                        "title": row["title"],
                        "start": row["start"],
                    }
                )
                last = row["slide"]
        vtt, srt = (
            self.root / "captions" / f"{lid}.vtt",
            self.root / "captions" / f"{lid}.srt",
        )
        write_captions(captions, vtt, srt)
        write_json(self.root / "reports" / f"{lid}-caption-audit.json", audit)
        audio = self.root / "work" / f"{lid}-narration.wav"
        concatenate_pcm(rows, audio)
        self.tool.probe(audio, lid + "-pcm-probe")
        pictures = [self.still(row) for row in rows]
        picture = self.picture_core(lid, pictures, rows[-1]["end_frame"])
        final = self.final(
            lid, picture, audio, vtt, chapters, rows[-1]["end_frame"], "lessons"
        )
        item = {
            "src": f"media/lessons/{lid}.mp4?v={self.args.cache_version}",
            "captions": f"media/lessons/{lid}.vtt?v={self.args.cache_version}",
            "voice": VOICE,
            "chapters": chapters,
            "source_sha256": source_hash(lesson),
            "duration": rows[-1]["end"],
            "frames": rows[-1]["end_frame"],
        }
        write_json(
            self.root / "reports" / f"{lid}-lesson.json",
            {
                "lesson": lid,
                "metadata": item,
                "picture": str(picture),
                "audio": str(audio),
                "captions": captions,
                "source": "\n\n".join(s["narration"] for s in lesson["slides"]),
            },
        )
        print(
            f"LESSON READY {lid}: {item['duration']:.3f}s, {item['frames']} exact frames: {final}",
            flush=True,
        )
        return item

    def group(self, definition, lesson_map):
        entries = [
            read_json(self.root / "reports" / f"{lid}-lesson.json")
            for lid in definition["lessons"]
        ]
        # Refuse stale lesson outputs even if their files still exist.
        for entry in entries:
            if entry["metadata"]["source_sha256"] != source_hash(
                lesson_map[entry["lesson"]]
            ):
                raise ValueError("Stale group lesson: " + entry["lesson"])
        offset, chapters, captions, pcm_rows, pictures = 0, [], [], [], []
        for entry in entries:
            lid = entry["lesson"]
            chapters.extend(
                {
                    "id": chapter["id"],
                    "lesson": lid,
                    "title": chapter["title"],
                    "start": offset / FPS + chapter["start"],
                }
                for chapter in entry["metadata"]["chapters"]
            )
            captions.extend(
                (a + offset / FPS, b + offset / FPS, text)
                for a, b, text in entry["captions"]
            )
            count = entry["metadata"]["frames"]
            pictures.append(Path(entry["picture"]))
            pcm_rows.append(
                {
                    "id": lid,
                    "audio": entry["audio"],
                    "voice_frames": count,
                    "frames": count,
                }
            )
            offset += count
        key = definition["id"]
        audio = self.root / "work" / f"group-{key}-narration.wav"
        concatenate_pcm(pcm_rows, audio)
        self.tool.probe(audio, key + "-pcm-probe")
        vtt, srt = (
            self.root / "captions" / f"group-{key}.vtt",
            self.root / "captions" / f"group-{key}.srt",
        )
        write_captions(captions, vtt, srt)
        picture = self.picture_core("group-" + key, pictures, offset)
        self.final(key, picture, audio, vtt, chapters, offset, "groups")
        return {
            **definition,
            "src": f"media/groups/{key}.mp4?v={self.args.cache_version}",
            "captions": f"media/groups/{key}.vtt?v={self.args.cache_version}",
            "chapters": chapters,
            "duration": offset / FPS,
            "frames": offset,
            "source_sha256": digest("\n\n".join(entry["source"] for entry in entries)),
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", type=Path, required=True)
    parser.add_argument(
        "--modules", type=Path, default=Path("www/learn/course/modules")
    )
    parser.add_argument(
        "--skill", type=Path, default=Path.home() / ".codex/skills/ffmpeg-skill/scripts"
    )
    parser.add_argument("--edition", default=EDITION)
    parser.add_argument("--cache-version", default=CACHE_VERSION)
    parser.add_argument("--lessons", nargs="+")
    parser.add_argument("--groups", nargs="+", choices=[g["id"] for g in GROUPS])
    parser.add_argument("--skip-groups", action="store_true")
    parser.add_argument(
        "--groups-only",
        action="store_true",
        help="Reuse completed lesson picture/PCM cores; do not rebuild individual lessons",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Inventory source/inputs; no ASR or media processing",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate selected source, audio, captures and asset receipts without ASR or encoding",
    )
    parser.add_argument(
        "--caption-mode",
        choices=("asr", "proportional"),
        default="asr",
        help="Proportional timing is an explicit estimated fallback; ASR uses CPU2 sequentially",
    )
    parser.add_argument("--asr-model", default="small.en")
    parser.add_argument("--tool-timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    lessons = load_lessons(args.modules)
    wanted = set(args.lessons or [lesson["id"] for lesson in lessons])
    if wanted - {lesson["id"] for lesson in lessons}:
        parser.error(
            "Unknown lesson(s): "
            + ", ".join(sorted(wanted - {lesson["id"] for lesson in lessons}))
        )
    if args.plan_only:
        inventory = []
        for lesson in lessons:
            if lesson["id"] not in wanted:
                continue
            units = source_units(lesson, args.production)
            inventory.append(
                {
                    "lesson": lesson["id"],
                    "source_sha256": source_hash(lesson),
                    "units": units,
                    "missing": [
                        u[k]
                        for u in units
                        for k in ("audio", "receipt", "picture")
                        if not Path(u[k]).exists()
                    ],
                }
            )
        write_json(
            args.production / "reports" / "course-plan.json",
            {
                "edition": args.edition,
                "fps": FPS,
                "width": WIDTH,
                "height": HEIGHT,
                "lessons": inventory,
            },
        )
        print(
            json.dumps(
                {
                    "lessons": len(inventory),
                    "units": sum(len(x["units"]) for x in inventory),
                    "missing_inputs": sum(len(x["missing"]) for x in inventory),
                },
                indent=2,
            )
        )
        return 0
    if args.validate_only:
        for lesson in lessons:
            if lesson["id"] in wanted:
                units = source_units(lesson, args.production)
                for unit in units:
                    validate_capture(unit, args.production, args.modules)
                    checked = validate_unit(unit)
                    validate_motion(checked, args.production, args.modules)
                print(
                    f"INPUTS READY {lesson['id']}: {len(units)} source/audio/picture bindings",
                    flush=True,
                )
        return 0
    builder = Builder(args)
    index_path = args.production / "video-index.json"
    index = (
        read_json(index_path)
        if index_path.exists()
        else {"edition": args.edition, "lessons": {}}
    )
    if index.get("edition") != args.edition:
        index = {"edition": args.edition, "lessons": {}}
    for lesson in lessons:
        if lesson["id"] in wanted and not args.groups_only:
            index["lessons"][lesson["id"]] = builder.lesson(lesson)
            write_json(index_path, index)
    if not args.skip_groups:
        definitions = [g for g in GROUPS if not args.groups or g["id"] in args.groups]
        group_path = args.production / "video-groups.json"
        old = read_json(group_path) if group_path.exists() else {}
        grouped = (
            {g["id"]: g for g in old.get("groups", [])}
            if old.get("edition") == args.edition
            else {}
        )
        for definition in definitions:
            grouped[definition["id"]] = builder.group(
                definition, {lesson["id"]: lesson for lesson in lessons}
            )
            write_json(
                group_path,
                {
                    "edition": args.edition,
                    "groups": [grouped[g["id"]] for g in GROUPS if g["id"] in grouped],
                },
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
