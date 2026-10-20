"""Compile editable lesson modules into the static academy catalogue.

Compilation can precede video assembly. --verify-media is the publication gate:
all lesson/group videos and all narration bindings must match the frozen source.
"""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "www/learn/course"
EDITION = "2026-10-20-r4"
CACHE_VERSION = "20261020r4"
ORDER = (
    "A1 A2 A3 A4 A5 A6 B1 B2 B3 B4 C1 C2a C2b C3 C4 C5 C6 C7 D1 D2 D3 D4 D5 D6".split()
)
ROUTES = ("operator", "builder-pi", "builder-x86")
GROUPS = {
    "foundations": ("A1 A2 A3 A4 A5 A6".split(), ROUTES),
    "watering-equipment": ("B1 B2 B3 B4 C1".split(), ROUTES),
    "setup-pi": ("C2a C3 C4 C5 C6 C7".split(), ("builder-pi",)),
    "setup-x86": ("C2b C3 C4 C5 C6 C7".split(), ("builder-x86",)),
    "operations": ("D1 D2 D3 D4 D5 D6".split(), ROUTES),
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_hash(lesson):
    return hashlib.sha256(
        "\n\n".join(slide["narration"] for slide in lesson["slides"]).encode("utf-8")
    ).hexdigest()


def media_url(value, expected):
    """Published URLs have a local fixed path and this edition's cache key."""
    if not isinstance(value, str):
        raise ValueError("Media URL must be a string")
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or parsed.path != expected
        or parsed.query != "v=" + CACHE_VERSION
    ):
        raise ValueError(f"Invalid or stale media URL: {value}")
    return parsed.path.removeprefix("media/")


def local_file(root, value):
    """Resolve a manifest path without accepting URLs, traversal or escaping links."""
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value)
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError(f"Invalid bound media path: {value}")
    root = root.resolve()
    path = root.joinpath(*PurePosixPath(value).parts).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or invalid bound media path: {value}")
    return path


def chapters_match(chapters, expected, label, duration=None):
    """Expected keys are slide IDs, or (lesson, slide) pairs for grouped videos."""
    if not isinstance(chapters, list) or len(chapters) != len(expected):
        raise ValueError(f"{label}: chapter count does not match source slides")
    keys = []
    previous = -1
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise ValueError(f"{label}: invalid chapter")
        keys.append(
            (chapter.get("lesson"), chapter.get("id"))
            if expected and isinstance(expected[0], tuple)
            else chapter.get("id")
        )
        start = chapter.get("start")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or not math.isfinite(start)
            or start < 0
            or start <= previous
            or (duration is not None and start >= duration)
        ):
            raise ValueError(
                f"{label}: chapter starts must be finite, increasing and inside the video"
            )
        if not isinstance(chapter.get("title"), str) or not chapter["title"].strip():
            raise ValueError(f"{label}: chapter title is missing")
        previous = start
    if keys != expected or (chapters and chapters[0]["start"] != 0):
        raise ValueError(
            f"{label}: chapter IDs/order must match source slides and begin at zero"
        )


def load_video_index(course_dir, lessons, required=False):
    path = course_dir / "video-index.json"
    if not path.exists():
        if required:
            raise ValueError("All 24 lesson videos require course/video-index.json")
        return None
    index = read_json(path)
    if (
        index.get("edition") != EDITION
        or not isinstance(index.get("lessons"), dict)
        or set(index["lessons"]) != set(ORDER)
    ):
        raise ValueError(
            "Video index must contain this edition and exactly all 24 approved lessons"
        )
    for lesson in lessons:
        lid = lesson["id"]
        video = index["lessons"][lid]
        if not isinstance(video, dict) or video.get("source_sha256") != source_hash(
            lesson
        ):
            raise ValueError(f"Stale lesson video source: {lid}")
        media_url(video.get("src"), f"media/lessons/{lid}.mp4")
        media_url(video.get("captions"), f"media/lessons/{lid}.vtt")
        if not isinstance(video.get("voice"), str) or not video["voice"].strip():
            raise ValueError(f"{lid}: video voice disclosure is missing")
        chapters_match(
            video.get("chapters"), [slide["id"] for slide in lesson["slides"]], lid
        )
    return index


def route_lessons(lessons, route):
    return [
        lesson["id"]
        for lesson in lessons
        if lesson.get("route", "everyone") in ("everyone", "operator")
        or (lesson.get("route") == "builder" and route != "operator")
        or (lesson.get("route") == "pi" and route == "builder-pi")
        or (lesson.get("route") == "x86" and route == "builder-x86")
    ]


def load_video_groups(course_dir, lessons, required=False):
    path = course_dir / "video-groups.json"
    if not path.exists():
        if required:
            raise ValueError("Five grouped videos require course/video-groups.json")
        return None
    data = read_json(path)
    groups = data.get("groups")
    if (
        data.get("edition") != EDITION
        or not isinstance(groups, list)
        or any(not isinstance(g, dict) for g in groups)
        or [g.get("id") for g in groups] != list(GROUPS)
    ):
        raise ValueError(
            "Grouped videos must contain this edition's five groups in course order"
        )
    indexed = {lesson["id"]: lesson for lesson in lessons}
    for group in groups:
        gid = group["id"]
        expected_lessons, expected_routes = GROUPS[gid]
        if (
            group.get("lessons") != expected_lessons
            or not isinstance(group.get("routes"), list)
            or sorted(group["routes"]) != sorted(expected_routes)
        ):
            raise ValueError(f"{gid}: grouped lesson/route coverage is incorrect")
        for key in ("title", "description"):
            if not isinstance(group.get(key), str) or not group[key].strip():
                raise ValueError(f"{gid}: missing {key}")
        duration = group.get("duration")
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError(f"{gid}: invalid video duration")
        media_url(group.get("src"), f"media/groups/{gid}.mp4")
        media_url(group.get("captions"), f"media/groups/{gid}.vtt")
        expected_chapters = [
            (lid, slide["id"])
            for lid in expected_lessons
            for slide in indexed[lid]["slides"]
        ]
        chapters_match(group.get("chapters"), expected_chapters, gid, duration)
    for route, count in zip(ROUTES, (17, 23, 23)):
        expected = route_lessons(lessons, route)
        actual = [
            lid
            for group in groups
            if route in group["routes"]
            for lid in group["lessons"]
        ]
        if len(expected) != count or actual != expected:
            raise ValueError(
                f"{route}: grouped videos do not cover the exact {count}-lesson learning route"
            )
    return data


def compile_course(course_dir=None):
    course_dir = Path(course_dir) if course_dir is not None else COURSE
    lessons = [
        lesson
        for source in sorted((course_dir / "modules").glob("*.json"))
        for lesson in read_json(source)
    ]
    indexed = {lesson["id"]: lesson for lesson in lessons}
    if len(indexed) != len(lessons) or set(indexed) != set(ORDER):
        raise ValueError(
            "Course must contain exactly the 24 distinct approved lesson IDs"
        )
    for lesson in lessons:
        for name in (
            "title",
            "summary",
            "outcomes",
            "slides",
            "practice",
            "quiz",
            "practicalTask",
            "sources",
        ):
            if not lesson.get(name):
                raise ValueError(f'{lesson["id"]}: missing {name}')
        slide_ids = [slide["id"] for slide in lesson["slides"]]
        if len(slide_ids) != len(set(slide_ids)):
            raise ValueError("Duplicate slide ID inside lesson")
        for question in lesson["quiz"]:
            if (
                sum(option.get("correct") is True for option in question["options"])
                != 1
            ):
                raise ValueError("Every question must have exactly one correct option")
            if not all(option.get("feedback") for option in question["options"]):
                raise ValueError("Every option must explain its answer")
        if any(prerequisite not in indexed for prerequisite in lesson["prerequisites"]):
            raise ValueError("Unknown prerequisite")
        if lesson["id"] in lesson["prerequisites"]:
            raise ValueError("Self-referential prerequisite")

    def visit(lid, trail):
        if lid in trail:
            raise ValueError("Prerequisite cycle")
        for prerequisite in indexed[lid]["prerequisites"]:
            visit(prerequisite, trail | {lid})

    for lid in ORDER:
        visit(lid, set())
    lessons = [indexed[lid] for lid in ORDER]
    index = load_video_index(course_dir, lessons)
    load_video_groups(course_dir, lessons)
    if index is not None:
        for lesson in lessons:
            lesson["video"] = index["lessons"][lesson["id"]].copy()
    return {
        "schema": 1,
        "title": "Crop Steering Academy",
        "description": "Learn the root zone, understand a watering day, and practise each control before live operation.",
        "edition": EDITION,
        "lessons": lessons,
        "glossary": read_json(course_dir / "glossary.json"),
        "modules": [
            {
                "id": "A",
                "title": "Understand the root zone",
                "description": "Water, air, VWC, capacity, dryback and trustworthy evidence.",
            },
            {
                "id": "B",
                "title": "Read a whole watering day",
                "description": "Combine VWC and EC, understand phases and estimate delivered water.",
            },
            {
                "id": "C",
                "title": "Build and check a system",
                "description": "Equipment, one supported host route, mapping, protection and supervised commissioning.",
            },
            {
                "id": "D",
                "title": "Operate with a clear reason",
                "description": "Find the right scope, review targets, build plans, compare evidence and investigate problems.",
            },
        ],
        "disclosures": {
            "narration": (
                "All 24 lessons have captioned videos with locally generated Kokoro af_heart narration, AI-generated teaching illustrations, native diagrams and captures of the real application. Teaching images and screenshots do not verify a physical installation."
                if index is not None
                else "All lessons use locally generated Kokoro af_heart narration. Complete lesson videos and grouped viewing are pending media verification."
            ),
            "language": "Written using ASD-STE100 principles. Not certified or represented as full formal conformance.",
            "evidence": "Research-informed instructional design; no learner outcome trial has been conducted.",
            "progress": "Local browser knowledge-practice record, not certification, verified identity or proof of safe hardware.",
        },
    }


def verify_media(compiled, course_dir=None):
    course_dir = Path(course_dir) if course_dir is not None else COURSE
    lessons = compiled["lessons"]
    index = load_video_index(course_dir, lessons, required=True)
    groups = load_video_groups(course_dir, lessons, required=True)
    if (
        compiled.get("edition") != EDITION
        or len(lessons) != 24
        or sum(len(lesson["slides"]) for lesson in lessons) != 153
    ):
        raise ValueError(
            "Publication requires the complete r3 catalogue: 24 lessons and 153 slides"
        )
    for lesson in lessons:
        if lesson.get("video") != index["lessons"][lesson["id"]]:
            raise ValueError(
                f'{lesson["id"]}: compiled video does not match the verified index'
            )
    media_root = course_dir.parent / "media"
    manifest = read_json(media_root / "manifest.json")
    if manifest.get("edition") != EDITION:
        raise ValueError("Media manifest belongs to a different edition")
    inventory = {}
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict):
            raise ValueError("Invalid media inventory entry")
        relative = entry.get("path")
        path = local_file(media_root, relative)
        if relative in inventory:
            raise ValueError(f"Duplicate media inventory path: {relative}")
        size = entry.get("bytes")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size != path.stat().st_size
        ):
            raise ValueError(f"Media byte count mismatch: {relative}")
        digest = entry.get("sha256")
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or file_hash(path) != digest
        ):
            raise ValueError(f"Media SHA-256 mismatch: {relative}")
        inventory[relative] = entry
    required_paths = set()
    for lid, video in index["lessons"].items():
        required_paths.update(
            [
                media_url(video["src"], f"media/lessons/{lid}.mp4"),
                media_url(video["captions"], f"media/lessons/{lid}.vtt"),
            ]
        )
    for group in groups["groups"]:
        gid = group["id"]
        required_paths.update(
            [
                media_url(group["src"], f"media/groups/{gid}.mp4"),
                media_url(group["captions"], f"media/groups/{gid}.vtt"),
            ]
        )
    records = manifest.get("bindings")
    if not isinstance(records, list):
        raise ValueError("Narration binding list is missing")
    if any(not isinstance(entry, dict) for entry in records):
        raise ValueError("Invalid narration binding")
    bound = {(entry.get("lesson"), entry.get("slide")): entry for entry in records}
    expected = {
        (lesson["id"], slide["id"]) for lesson in lessons for slide in lesson["slides"]
    }
    if set(bound) != expected or len(bound) != len(records):
        raise ValueError(
            "Narration bindings do not match all 153 source slides exactly once"
        )
    for lesson in lessons:
        for slide in lesson["slides"]:
            binding = bound[(lesson["id"], slide["id"])]
            if hashlib.sha256(
                slide["narration"].encode("utf-8")
            ).hexdigest() != binding.get("source_sha256"):
                raise ValueError(
                    f'Stale narration binding: {lesson["id"]}/{slide["id"]}'
                )
            for key in ("audio", "captions"):
                local_file(media_root, binding.get(key))
                required_paths.add(binding[key])
    if not required_paths <= inventory.keys():
        raise ValueError(
            "Media manifest omits referenced files: "
            + ", ".join(sorted(required_paths - inventory.keys()))
        )
    return {
        "lessons": 24,
        "groups": 5,
        "bindings": len(bound),
        "verified_files": len(inventory),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-media",
        action="store_true",
        help="Require all 24 videos, five route-complete groups and current, hashed narration bindings",
    )
    args = parser.parse_args()
    compiled = compile_course()
    # Fail before writing either generated output if media is incomplete or stale.
    if args.verify_media:
        result = verify_media(compiled)
        print("Verified media: " + json.dumps(result))
    (COURSE / "course.json").write_text(
        json.dumps(compiled, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    transcript = [
        "CROP STEERING ACADEMY — EDITION " + compiled["edition"],
        compiled["disclosures"]["narration"],
        compiled["disclosures"]["language"],
        "All numerical crop settings are examples. Online practice is not hardware certification.",
    ]
    for lesson in compiled["lessons"]:
        transcript += ["\n" + lesson["id"] + " — " + lesson["title"], lesson["summary"]]
        for slide in lesson["slides"]:
            transcript += ["\n" + slide["title"], slide["narration"]]
        transcript += [
            "\nINDEPENDENT PRACTICE",
            lesson["practice"]["prompt"],
            "Compare your reasoning: " + lesson["practice"]["success"],
            "\nSOURCES",
        ]
        transcript += [
            source["title"] + ": " + source["url"] for source in lesson["sources"]
        ]
    (COURSE / "all-lesson-transcripts.txt").write_text(
        "\n\n".join(transcript) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f'Compiled {len(compiled["lessons"])} lessons and {sum(len(lesson["slides"]) for lesson in compiled["lessons"])} slides'
    )


if __name__ == "__main__":
    main()
