"""Join rendered lessons into one continuous YouTube video (lossless), with chapters,
SRT captions and a description draft.
Usage: python video/scripts/youtube.py --render <lessons dir> --output <dir> [--lessons A1 ...]
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

OPERATOR = "A1 A2 A3 A4 A5 A6 B1 B2 B3 B4 C1 D1 D2 D3 D4 D5 D6".split()
ROOT = Path(__file__).resolve().parents[2]


def seconds(s):
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def srt(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def chapter(t):
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--lessons", nargs="+", default=OPERATOR)
    ap.add_argument("--name", default="crop-steering-academy-full-course")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    course = json.loads((ROOT / "www/learn/course/course.json").read_text(encoding="utf-8"))
    titles = {lesson["id"]: lesson["title"] for lesson in course["lessons"]}

    listing = args.output / "concat.txt"
    listing.write_text("".join(f"file '{(args.render / f'{lid}.mp4').as_posix()}'\n" for lid in args.lessons))
    video = args.output / f"{args.name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", "-movflags", "+faststart", str(video)], check=True)
    listing.unlink()

    offset, chapters, cues = 0.0, [], []
    for lid in args.lessons:
        meta = json.loads((args.render / f"{lid}.chapters.json").read_text(encoding="utf-8"))
        chapters.append(f"{chapter(offset)} {lid} · {titles[lid]}")
        text = (args.render / f"{lid}.vtt").read_text(encoding="utf-8")
        for a, b, body in re.findall(r"([\d:.]+) --> ([\d:.]+)\n(.+?)(?:\n\n|\n*\Z)", text, re.S):
            cues.append((offset + seconds(a), offset + seconds(b), body.strip()))
        offset += meta["duration"]

    (args.output / f"{args.name}.srt").write_text(
        "\n".join(f"{i}\n{srt(a)} --> {srt(b)}\n{t}\n" for i, (a, b, t) in enumerate(cues, 1)), encoding="utf-8")
    (args.output / f"{args.name}-chapters.txt").write_text("\n".join(chapters) + "\n", encoding="utf-8")
    (args.output / f"{args.name}-description.txt").write_text(
        "Crop steering from zero: a complete beginner course on watering plants in substrate, reading "
        "moisture (VWC) and EC, planning a watering day, and running the free Crop Steering software for "
        "Home Assistant. Every term is explained before it is used, with animated examples throughout.\n\n"
        "Interactive version with quick checks, practice and transcripts: "
        "https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/\n\n"
        "Chapters\n" + "\n".join(chapters) + "\n\n"
        "All crop numbers are teaching examples, not recommended settings. Narration is synthetic (Kokoro). "
        "Real equipment needs a competent local installer and the installation's approved procedure.\n",
        encoding="utf-8")
    print(json.dumps({"video": str(video), "duration": round(offset, 3), "chapters": len(chapters), "captions": len(cues)}))


if __name__ == "__main__":
    main()
