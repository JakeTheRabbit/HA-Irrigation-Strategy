"""Compile editable lesson modules into the static, dependency-free academy catalogue."""

import json
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "www/learn/course"
ORDER = (
    "A1 A2 A3 A4 A5 A6 B1 B2 B3 B4 C1 C2a C2b C3 C4 C5 C6 C7 D1 D2 D3 D4 D5 D6".split()
)


def compile_course():
    lessons = [
        lesson
        for source in sorted((COURSE / "modules").glob("*.json"))
        for lesson in json.loads(source.read_text(encoding="utf-8-sig"))
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
        slide_ids = [s["id"] for s in lesson["slides"]]
        if len(slide_ids) != len(set(slide_ids)):
            raise ValueError("Duplicate slide ID inside lesson")
        for q in lesson["quiz"]:
            if sum(o.get("correct") is True for o in q["options"]) != 1:
                raise ValueError("Every question must have exactly one correct option")
            if not all(o.get("feedback") for o in q["options"]):
                raise ValueError("Every option must explain its answer")
        if any(prereq not in indexed for prereq in lesson["prerequisites"]):
            raise ValueError("Unknown prerequisite")
        if lesson["id"] in lesson["prerequisites"]:
            raise ValueError("Self-referential prerequisite")

    def visit(lid, trail):
        if lid in trail:
            raise ValueError("Prerequisite cycle")
        for prereq in indexed[lid]["prerequisites"]:
            visit(prereq, trail | {lid})

    for lid in ORDER:
        visit(lid, set())
    return {
        "schema": 1,
        "title": "Crop Steering Academy",
        "description": "Learn the root zone, understand a watering day, and practise each control before live operation.",
        "edition": "2026-10-19-r2",
        "lessons": [indexed[lid] for lid in ORDER],
        "glossary": json.loads((COURSE / "glossary.json").read_text(encoding="utf-8")),
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
            "narration": "All lessons use locally generated Kokoro af_heart speech. Five rebuilt 480p pilot videos use 108 paragraph-matched visual cards.",
            "language": "Written using ASD-STE100 principles. Not certified or represented as full formal conformance.",
            "evidence": "Research-informed instructional design; no learner outcome trial has been conducted.",
            "progress": "Local browser knowledge-practice record, not certification, verified identity or proof of safe hardware.",
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-media",
        action="store_true",
        help="Require narration bindings to match the compiled source",
    )
    args = parser.parse_args()
    compiled = compile_course()
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
    if args.verify_media:
        manifest = json.loads(
            (COURSE.parent / "media/manifest.json").read_text(encoding="utf-8")
        )
        bound = {(b["lesson"], b["slide"]): b for b in manifest["bindings"]}
        expected = {
            (lesson["id"], slide["id"])
            for lesson in compiled["lessons"]
            for slide in lesson["slides"]
        }
        if set(bound) != expected or len(bound) != len(manifest["bindings"]):
            raise ValueError(
                "Narration bindings do not match the complete lesson/slide catalogue"
            )
        for lesson in compiled["lessons"]:
            for slide in lesson["slides"]:
                binding = bound[(lesson["id"], slide["id"])]
                digest = hashlib.sha256(slide["narration"].encode()).hexdigest()
                if digest != binding["source_sha256"]:
                    raise ValueError(
                        f'Stale narration binding: {lesson["id"]}/{slide["id"]}'
                    )
                for key in ("audio", "captions"):
                    path = Path(binding[key])
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or "\\" in binding[key]
                        or not (COURSE.parent / "media" / path).is_file()
                    ):
                        raise ValueError("Missing or invalid bound media path")
        print("Verified every narration binding against current lesson text")
    print(
        f'Compiled {len(compiled["lessons"])} lessons and {sum(len(lesson["slides"]) for lesson in compiled["lessons"])} slides'
    )
