"""Join academy lesson videos into one continuous 1080p video for YouTube.

Drops the silent "pause and answer" holds, upscales the 480p lessons to 1080p,
and writes matching SRT captions, chapter list and a description draft.
Reads installed media from www/learn/media and course/course.json. Example:
  python scripts/build_youtube_course.py --output "C:/Content/Crop Steering from Zero/youtube"
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "www/learn/course"
MEDIA = ROOT / "www/learn/media/lessons"
OPERATOR = "A1 A2 A3 A4 A5 A6 B1 B2 B3 B4 C1 D1 D2 D3 D4 D5 D6".split()
HOLD_TEXT = "[Pause and answer before continuing.]"


def seconds(stamp):
    h, m, s = stamp.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def srt_stamp(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def chapter_stamp(t):
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def cues(vtt):
    text = vtt.read_text(encoding="utf-8")
    pattern = r"([\d:.]+) --> ([\d:.]+)[^\n]*\n(.+?)(?:\n\n|\Z)"
    return [(seconds(a), seconds(b), body.strip()) for a, b, body in re.findall(pattern, text, re.S)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--lessons", nargs="+", default=OPERATOR)
    ap.add_argument("--name", default="crop-steering-academy-full-course")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    course = json.loads((COURSE / "course.json").read_text(encoding="utf-8"))
    titles = {lesson["id"]: lesson["title"] for lesson in course["lessons"]}
    index = json.loads((COURSE / "video-index.json").read_text(encoding="utf-8"))["lessons"]

    inputs, parts, labels, srt, chapters = [], [], [], [], []
    offset = 0.0
    for n, lid in enumerate(args.lessons):
        duration = index[lid]["duration"]
        lesson_cues = cues(MEDIA / f"{lid}.vtt")
        holds = [(a, b) for a, b, body in lesson_cues if body == HOLD_TEXT]
        keep, start = [], 0.0
        for a, b in holds:
            keep.append((start, a))
            start = b
        keep.append((start, duration))
        inputs += ["-i", str(MEDIA / f"{lid}.mp4")]
        chapters.append((offset, f"{lid} · {titles[lid]}"))
        for k, (a, b) in enumerate(keep):
            parts.append(
                f"[{n}:v]trim={a}:{b},setpts=PTS-STARTPTS[v{n}_{k}];"
                f"[{n}:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{n}_{k}]"
            )
            labels.append(f"[v{n}_{k}][a{n}_{k}]")
        for a, b, body in lesson_cues:
            if body == HOLD_TEXT:
                continue
            removed = sum(hb - ha for ha, hb in holds if hb <= a)
            srt.append((offset + a - removed, offset + b - removed, body))
        offset += sum(b - a for a, b in keep)

    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(labels)}:v=1:a=1[v][a];" + (
        "[v]scale=1920:1080:flags=lanczos,setsar=1,fps=24,format=yuv420p[vout];"
        "[a]aresample=48000,pan=stereo|c0=c0|c1=c0[aout]"
    )
    video = args.output / f"{args.name}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats", *inputs,
         "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "stillimage",
         "-g", "48", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(video)],
        check=True,
    )

    (args.output / f"{args.name}.srt").write_text(
        "\n".join(f"{i}\n{srt_stamp(a)} --> {srt_stamp(b)}\n{body}\n" for i, (a, b, body) in enumerate(srt, 1)),
        encoding="utf-8",
    )
    chapter_lines = [f"{chapter_stamp(t)} {title}" for t, title in chapters]
    (args.output / f"{args.name}-chapters.txt").write_text("\n".join(chapter_lines) + "\n", encoding="utf-8")
    description = (
        "Crop steering from zero: a complete beginner course on watering plants in substrate, "
        "reading moisture (VWC) and EC, planning a watering day, and running the free Crop Steering "
        "software for Home Assistant. Every term is explained before it is used.\n\n"
        "Interactive version with quick checks, practice and transcripts: "
        "https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/\n\n"
        "Chapters\n" + "\n".join(chapter_lines) + "\n\n"
        "All crop numbers are teaching examples, not recommended settings. Narration is synthetic "
        "(Kokoro). Real equipment needs a competent local installer and the installation's "
        "approved procedure.\n"
    )
    (args.output / f"{args.name}-description.txt").write_text(description, encoding="utf-8")
    print(json.dumps({"video": str(video), "duration": offset, "chapters": len(chapters), "captions": len(srt)}, indent=2))


if __name__ == "__main__":
    main()
