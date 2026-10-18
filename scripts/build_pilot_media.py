"""Render paragraph-bound pilot videos from local voice takes and PNG cards.

Requires faster-whisper (cached small.en), soundfile, and the ffmpeg-skill
scripts. Run build_pilot_audio.py first, or concurrently. No cloud media calls.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import time
import wave

from pilot_timing import plan

HOLDS = {"A1-04-p02": 8, "A2-01-p02": 8, "B1-06-p01": 8}


def stamp(t, vtt=True):
    ms = round(t * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}{"." if vtt else ","}{ms%1000:03}'


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("liters", "litres"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--production", type=Path, required=True)
    ap.add_argument("--skill", type=Path, required=True)
    ap.add_argument(
        "--source", type=Path, default=Path("www/learn/course/modules/pilots.json")
    )
    ap.add_argument(
        "--lessons", nargs="+", help="Optional independent lesson partition"
    )
    args = ap.parse_args()
    p = args.production.resolve()
    os.environ["FFMPEG_SKILL_NO_OVERWRITE"] = "1"
    for d in ("records", "work", "projects", "exports", "captions", "checks"):
        (p / d).mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel

    model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=2)
    lessons = json.loads(args.source.read_text(encoding="utf-8-sig"))
    if args.lessons:
        if set(args.lessons) - {lesson["id"] for lesson in lessons}:
            raise ValueError("Unknown pilot lesson")
        lessons = [lesson for lesson in lessons if lesson["id"] in args.lessons]
    cues = []
    for name in ("a1", "other"):
        cues.extend(
            json.loads(
                (args.source.parent.parent / f"pilot-cues-{name}.json").read_text(
                    encoding="utf-8"
                )
            )
        )

    def tool(name, argv, key, writing=True):
        doc = None
        for dry in [True, False] if writing else [False]:
            run = subprocess.run(
                [
                    sys.executable,
                    str(args.skill / name),
                    *map(str, argv),
                    *(["--dry-run"] if dry else []),
                    "--json",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            (p / "records" / f'{key}{"-plan" if dry else ""}.json').write_text(
                run.stdout, encoding="utf-8"
            )
            if run.returncode:
                raise RuntimeError(key + ": " + run.stdout[-2000:] + run.stderr[-1500:])
            doc = json.loads(run.stdout)
        return doc

    def one(card):
        key = card["id"]
        receipt = p / "narration" / f"{key}.json"
        frame = p / "frames" / f"{key}.png"
        deadline = time.monotonic() + 3600
        while not receipt.exists() or not frame.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("Missing voice or picture: " + key)
            time.sleep(1)
        r = json.loads(receipt.read_text())
        assert r["text"] == card["text"], f"Stale source: {key}"
        hold = HOLDS.get(key, 0)
        # Use the same PCM file for clip audio and alignment. Holds stay on the
        # question picture; the answer picture cannot appear during this time.
        audio = p / "work" / f"{key}.wav"
        with wave.open(str(receipt.with_suffix(".wav")), "rb") as source:
            params, samples = source.getparams(), source.readframes(source.getnframes())
        with wave.open(str(audio), "wb") as target:
            target.setparams(params)
            target.writeframes(
                samples
                + b"\0"
                * (hold * params.framerate * params.nchannels * params.sampwidth)
            )
        r = {
            **r,
            "frames": r["frames"] + hold * 24,
            "duration": r["duration"] + hold,
            "hold_seconds": hold,
        }
        motion = p / "motion" / key / "frames"
        if key == "B1-05-p03":
            while not (motion.parent / "ready.json").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("Missing timed threshold animation")
                time.sleep(1)
        motion_signature = b""
        if motion.exists():
            images = sorted(motion.glob("frame_*.png"))
            assert (
                len(images) == r["frames"]
            ), "Animation must cover the same frame count as speech"
            motion_signature = b"".join(
                hashlib.sha256(f.read_bytes()).digest() for f in images
            )
        signature = hashlib.sha256(
            b"insert-audio-v1"
            + audio.read_bytes()
            + frame.read_bytes()
            + motion_signature
        ).hexdigest()
        alignment = p / "records" / f"{key}-alignment.json"
        if (
            alignment.exists()
            and json.loads(alignment.read_text()).get("signature") == signature
        ):
            a = json.loads(alignment.read_text())
        else:
            segments, details = model.transcribe(
                str(audio),
                language="en",
                word_timestamps=True,
                beam_size=3,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            words = [
                {"word": w.word.strip(), "start": w.start, "end": w.end}
                for seg in segments
                for w in seg.words or []
            ]
            if not words:
                raise RuntimeError("No recognized speech: " + key)
            a = {"signature": signature, "duration": details.duration, "words": words}
            alignment.write_text(json.dumps(a, indent=2), encoding="utf-8")
        clip = p / "work" / f"{key}.mp4"
        saved = p / "records" / f"{key}-render-source.json"
        valid = (
            clip.exists()
            and saved.exists()
            and json.loads(saved.read_text()).get("signature") == signature
        )
        if valid:
            probe = tool("probe.py", [clip], key + "-probe", False)
        else:
            picture = p / "work" / f"{key}-picture.mp4"
            if motion.exists():
                motion_doc = tool(
                    "sequence.py",
                    [
                        "--dir",
                        motion,
                        "--pattern",
                        "frame_%04d.png",
                        "--fps",
                        24,
                        "--width",
                        854,
                        "--height",
                        480,
                        "--preset",
                        "fast",
                        "-o",
                        picture,
                        *(["--overwrite"] if picture.exists() else []),
                    ],
                    key + "-picture",
                )
                if motion_doc["probe"]["video"]["nb_frames"] != r["frames"]:
                    trimmed = picture.with_name(key + "-trimmed.mp4")
                    tool(
                        "cut.py",
                        [
                            picture,
                            "--start",
                            0,
                            "--end",
                            r["duration"],
                            "--accurate",
                            "-o",
                            trimmed,
                            *(["--overwrite"] if trimmed.exists() else []),
                        ],
                        key + "-motion-trim",
                    )
                    os.replace(trimmed, picture)
            else:
                tool(
                    "insert.py",
                    [
                        frame,
                        "--duration",
                        r["duration"],
                        "--width",
                        854,
                        "--height",
                        480,
                        "--fps",
                        24,
                        "--preset",
                        "fast",
                        "-o",
                        picture,
                        *(["--overwrite"] if picture.exists() else []),
                    ],
                    key + "-picture",
                )
            out = tool(
                "audio.py",
                [
                    picture,
                    "--replace",
                    audio,
                    "-o",
                    clip,
                    *(["--overwrite"] if clip.exists() else []),
                ],
                key + "-render",
            )
            probe = out["probe"]
            saved.write_text(json.dumps({"signature": signature}), encoding="utf-8")
        if probe["video"]["nb_frames"] != r["frames"]:
            raise RuntimeError(
                f'Frame mismatch {key}: {probe["video"]["nb_frames"]} != {r["frames"]}'
            )
        print(f'CLIP {key}: {r["duration"]:.2f}s, {r["frames"]} frames', flush=True)
        return r, a

    completed = {}
    for lesson in lessons:
        cards = [c for c in cues if c["lesson"] == lesson["id"]]
        with ThreadPoolExecutor(max_workers=2) as pool:
            for r, alignment in pool.map(one, cards):
                completed[r["id"]] = (r, alignment)
        # Validate against the original source, not merely against each other.
        rows = plan([lesson], cards, [completed[c["id"]][0] for c in cards])
        lid = lesson["id"]
        (p / "records" / f"{lid}-timeline.json").write_text(
            json.dumps(rows, indent=2), encoding="utf-8"
        )
        captions, audit, chapters, last = [], [], [], None
        for row in rows:
            r, a = completed[row["id"]]
            src, words = row["text"].split(), a["words"]
            match = difflib.SequenceMatcher(
                None,
                [norm(w) for w in src],
                [norm(w["word"]) for w in words],
                autojunk=False,
            )
            anchors = {}
            for block in match.get_matching_blocks():
                for k in range(block.size):
                    anchors[block.a + k] = words[block.b + k]["start"]
            anchors[-1], anchors[len(src)] = 0, min(
                r["speech_duration"], words[-1]["end"] + 0.1
            )
            starts = []
            for i in range(len(src)):
                if i in anchors:
                    starts.append(anchors[i])
                else:
                    lo, hi = max(k for k in anchors if k < i), min(
                        k for k in anchors if k > i
                    )
                    starts.append(
                        anchors[lo] + (anchors[hi] - anchors[lo]) * (i - lo) / (hi - lo)
                    )
            i = 0
            while i < len(src):
                end = i + 1
                while (
                    end < len(src)
                    and end - i < 9
                    and starts[end] - starts[i] < 4
                    and not re.search(r"[.!?]$", src[end - 1])
                ):
                    end += 1
                start = starts[i]
                stop = (starts[end] if end < len(src) else anchors[len(src)]) - 0.02
                stop = min(r["duration"], max(start + 0.12, stop))
                text = "\n".join(
                    textwrap.wrap(
                        " ".join(src[i:end]),
                        44,
                        break_long_words=False,
                        break_on_hyphens=False,
                    )
                )
                captions.append((row["start"] + start, row["start"] + stop, text))
                i = end
            if r["hold_seconds"]:
                captions.append(
                    (
                        row["start"] + r["speech_duration"] + 0.3,
                        row["end"] - 0.1,
                        "[Pause and answer. Continue when ready.]",
                    )
                )
            audit.append(
                {
                    "id": row["id"],
                    "source_words_retained": len(src),
                    "asr_match_ratio": round(match.ratio(), 3),
                }
            )
            if row["scene"] != last:
                title = next(
                    s["title"] for s in lesson["slides"] if s["id"] == row["scene"]
                )
                chapters.append({"at": row["start"], "title": title})
                last = row["scene"]
        for n in range(1, len(captions)):
            assert (
                captions[n - 1][1] <= captions[n][0] + 0.002
            ), f"Overlapping captions: {lid}/{n}"
        srt, vtt = p / "captions" / f"{lid}.srt", p / "captions" / f"{lid}.vtt"
        srt.write_text(
            "\n\n".join(
                f"{i+1}\n{stamp(a,False)} --> {stamp(b,False)}\n{t}"
                for i, (a, b, t) in enumerate(captions)
            )
            + "\n",
            encoding="utf-8",
        )
        vtt.write_text(
            "WEBVTT\n\n"
            + "\n\n".join(f"{stamp(a)} --> {stamp(b)}\n{t}" for a, b, t in captions)
            + "\n",
            encoding="utf-8",
        )
        # Concatenate PCM, not individual AAC streams. Decoding AAC separately
        # introduces encoder padding that otherwise lengthens each visual hold.
        episode_audio = p / "work" / f"{lid}-episode.wav"
        with wave.open(str(episode_audio), "wb") as target:
            target.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            for row in rows:
                with wave.open(str(p / "work" / f'{row["id"]}.wav'), "rb") as part:
                    assert (
                        part.getnchannels(),
                        part.getsampwidth(),
                        part.getframerate(),
                    ) == (1, 2, 24000)
                    assert part.getnframes() == row["frames"] * 1000
                    target.writeframes(part.readframes(part.getnframes()))
        core, final = (
            p / "exports" / f"{lid}-core-480p.mp4",
            p / "exports" / f"{lid}-480p.mp4",
        )
        project = {
            "output": str(core),
            "frame": {"width": 854, "height": 480, "fps": 24},
            "clips": [
                {"src": str(p / "work" / f'{r["id"]}-picture.mp4')} for r in rows
            ],
            "transition": {"type": "none"},
            "audio": {"replace": str(episode_audio)},
            "chapters": chapters,
        }
        project_path = p / "projects" / f"{lid}.json"
        project_path.write_text(json.dumps(project, indent=2), encoding="utf-8")
        tool(
            "render.py",
            [project_path, *(["--overwrite"] if core.exists() else [])],
            lid + "-episode",
        )
        normalized = p / "exports" / f"{lid}-normalized-480p.mp4"
        tool(
            "loudness.py",
            [
                core,
                "-I",
                -16,
                "--tp",
                -1.5,
                "--sample-rate",
                48000,
                "-o",
                normalized,
                *(["--overwrite"] if normalized.exists() else []),
            ],
            lid + "-normalize",
        )
        tool(
            "caption.py",
            [
                normalized,
                "--srt",
                str(srt) + ":eng",
                "--mode",
                "mux",
                "--track-title",
                "English - source script",
                "--default-track",
                "eng",
                "-o",
                final,
                *(["--overwrite"] if final.exists() else []),
            ],
            lid + "-captions",
        )
        probe = tool("probe.py", [final], lid + "-final-probe", False)
        assert (
            abs(probe["video"]["nb_frames"] - rows[-1]["end_frame"]) <= 1
        ), f"Final timeline drift: {lid}"
        assert (
            probe["video"]["width"],
            probe["video"]["height"],
            probe["video"]["fps"],
            probe["audio"]["channels"],
            probe["audio"]["sample_rate"],
            probe["subtitle_streams"],
        ) == (854, 480, 24, 1, 48000, 1)
        tool(
            "check.py",
            [final, "--platform", "youtube", "--lufs", -16, "--tp", -1],
            lid + "-check",
            False,
        )
        (p / "records" / f"{lid}-caption-audit.json").write_text(
            json.dumps(audit, indent=2), encoding="utf-8"
        )
        print(
            f'FINAL {lid}: {probe["duration"]:.2f}s, {len(rows)} matched cards',
            flush=True,
        )


if __name__ == "__main__":
    main()
