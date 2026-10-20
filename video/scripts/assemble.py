"""Turn rendered Remotion lessons into the academy's publishable media layout.

Reads <render>/<ID>.mp4|.vtt|.chapters.json, writes <production>/public-media/{lessons,groups}
and <production>/video-index.json + video-groups.json in the schema build_course.py and
package_course_videos.py verify. Groups are lossless concatenations of their lessons.
Usage: python video/scripts/assemble.py --render <dir> --production <dir>
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_course as compiler  # noqa: E402
from build_course_videos import GROUPS  # noqa: E402

FPS = 30
VOICE = "Kokoro af_heart · source-matched local narration"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stamp(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}"


def seconds(s):
    h, m, rest = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def cues(vtt):
    text = vtt.read_text(encoding="utf-8")
    return re.findall(r"([\d:.]+) --> ([\d:.]+)\n(.+?)(?:\n\n|\n*\Z)", text, re.S)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render", type=Path, required=True)
    ap.add_argument("--production", type=Path, required=True)
    args = ap.parse_args()
    # Read the editable modules directly: compiling would reject the previous edition's index.
    lessons = {
        lesson["id"]: lesson
        for path in sorted((compiler.COURSE / "modules").glob("*.json"))
        for lesson in compiler.read_json(path)
    }
    media = args.production / "public-media"
    (media / "lessons").mkdir(parents=True, exist_ok=True)
    (media / "groups").mkdir(parents=True, exist_ok=True)
    q = "?v=" + compiler.CACHE_VERSION

    index = {"edition": compiler.EDITION, "lessons": {}}
    for lid in compiler.ORDER:
        meta = json.loads((args.render / f"{lid}.chapters.json").read_text(encoding="utf-8"))
        for ext in ("mp4", "vtt"):
            shutil.copy2(args.render / f"{lid}.{ext}", media / "lessons" / f"{lid}.{ext}")
        frames = round(meta["duration"] * FPS)
        chapters = [
            {"id": c["id"], "slide": c["id"], "title": c["title"], "start": 0.0 if i == 0 else c["start"]}
            for i, c in enumerate(meta["chapters"])
        ]
        index["lessons"][lid] = {
            "src": f"media/lessons/{lid}.mp4{q}",
            "captions": f"media/lessons/{lid}.vtt{q}",
            "voice": VOICE,
            "chapters": chapters,
            "source_sha256": compiler.source_hash(lessons[lid]),
            "duration": frames / FPS,
            "frames": frames,
        }

    groups = {"edition": compiler.EDITION, "groups": []}
    for g in GROUPS:
        gid, ids = g["id"], g["lessons"]
        listing = args.production / f"concat-{gid}.txt"
        listing.write_text("".join(f"file '{(media / 'lessons' / f'{lid}.mp4').as_posix()}'\n" for lid in ids))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", "-movflags", "+faststart", str(media / "groups" / f"{gid}.mp4")], check=True)
        listing.unlink()
        offset, chapters, lines = 0, [], ["WEBVTT", ""]
        for lid in ids:
            video = index["lessons"][lid]
            t0 = offset / FPS
            chapters += [{"id": c["id"], "lesson": lid, "title": f"{lid} · {c['title']}", "start": t0 + c["start"]} for c in video["chapters"]]
            for a, b, body in cues(media / "lessons" / f"{lid}.vtt"):
                lines += [f"{stamp(t0 + seconds(a))} --> {stamp(t0 + seconds(b))}", body.strip(), ""]
            offset += video["frames"]
        (media / "groups" / f"{gid}.vtt").write_text("\n".join(lines), encoding="utf-8")
        groups["groups"].append({
            "id": gid, "title": g["title"], "description": g["description"], "routes": g["routes"], "lessons": ids,
            "src": f"media/groups/{gid}.mp4{q}", "captions": f"media/groups/{gid}.vtt{q}",
            "chapters": chapters, "duration": offset / FPS, "frames": offset,
            "source_sha256": sha("\n\n".join(s["narration"] for lid in ids for s in lessons[lid]["slides"])),
        })

    for name, data in (("video-index.json", index), ("video-groups.json", groups)):
        (args.production / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total = sum(v["duration"] for v in index["lessons"].values())
    print(json.dumps({"lessons": len(index["lessons"]), "groups": len(groups["groups"]), "lesson_seconds": round(total, 3)}))


if __name__ == "__main__":
    main()
