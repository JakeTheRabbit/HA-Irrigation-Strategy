#!/usr/bin/env python3
"""Convert an intake.json (Grow Licence Intake app) into application_data.yaml and gaps.md.

Usage:
    python intake_to_yaml.py intake.json -o cases/<name>/application_data.yaml

Writes the YAML (from assets/application_data.template.yaml) and, beside it, gaps.md:
every required question that is missing, "not known" or too short to be a fact.
Needs PyYAML.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
ENTITY = re.compile(r"\b(limited|ltd|trust|incorporated|inc|council|partnership|society)\b", re.IGNORECASE)
VAGUE = {"yes", "there will be", "will be", "maybe", "tbc", "soon", "same", "as above", "ok", "confirmed"}


def load_questions(path: Path) -> list[dict]:
    q = json.loads(path.read_text(encoding="utf-8"))
    return [
        dict(x, section=s["title"], section_show_if=s.get("show_if")) for s in q["sections"] for x in s["questions"]
    ]


def visible(rule: dict | None, answers: dict) -> bool:
    if not rule:
        return True
    return all((answers.get(k, "") or "").split("\n")[0].strip() in v for k, v in rule.items())


def set_path(doc: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = doc
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def value_of(q: dict, raw: str):
    raw = (raw or "").strip()
    if q["type"] in ("choice", "yesno"):
        first, _, rest = raw.partition("\n")
        return first.strip() if not rest.strip() else f"{first.strip()} - {rest.strip()}"
    return raw


def classify(q: dict, raw: str) -> str | None:
    """Return a gap status, or None when the answer looks like a usable fact."""
    a = (raw or "").strip()
    if not a:
        return "missing" if q.get("required") else None
    low = a.lower()
    if low.startswith("not known"):
        return "not known"
    core = low.strip(" .!")
    if q["type"] not in ("yesno", "choice") and core in VAGUE:
        return "check: vague - ask for the fact"
    if q.get("legal_entity") and not ENTITY.search(a):
        return "check: give the exact legal name (Limited, Trust...)"
    return None


def convert(intake: dict, questions: list[dict], template: dict) -> tuple[dict, list[dict]]:
    doc = template
    answers = intake.get("answers", {})
    gaps = []
    for q in questions:
        if not (visible(q.get("section_show_if"), answers) and visible(q.get("show_if"), answers)):
            continue
        raw = answers.get(q["id"], "")
        if q["type"] == "layout":
            lay = intake.get("layout") or {}
            if lay.get("items"):
                doc.setdefault("layout", {})
                doc["layout"]["site"] = lay.get("site", {"w": 40, "d": 30})
                doc["layout"]["north_deg"] = lay.get("north", 0)
                doc["layout"]["items"] = lay["items"]
                doc["layout"]["source"] = "phone layout tool - indicative"
            elif q.get("required"):
                gaps.append({"q": q, "status": "missing", "answer": ""})
            continue
        if q["type"] == "sketch":
            if intake.get("sketch"):
                set_path(doc, q["map"], "sketch.png")
            continue
        photos = intake.get("photos", {}).get(q["id"], [])
        if q["type"] == "photos":
            val = ", ".join(photos)
            if raw.strip():
                val = raw.strip() + (" | files: " + val if val else "")
            set_path(doc, q["map"], val)
            if not val and q.get("required"):
                gaps.append({"q": q, "status": "missing", "answer": ""})
            continue
        status = classify(q, raw)
        if raw.strip():
            set_path(doc, q["map"], value_of(q, raw))
        if photos:
            set_path(doc, "evidence." + q["id"], photos)
        if status:
            gaps.append({"q": q, "status": status, "answer": raw.strip()})
        if q["id"] == "Q122" and raw.lower().startswith("yes"):
            gaps.insert(0, {"q": q, "status": "STOP: legal advice", "answer": raw.strip()})
    route = (answers.get("Q002", "") or "").split("\n")[0].strip()
    doc.setdefault("meta", {})["route"] = route
    doc["meta"]["intake_id"] = intake.get("id", "")
    doc["meta"]["questionnaire_version"] = intake.get("questionnaire_version", "")
    return doc, gaps


def gaps_markdown(intake: dict, gaps: list[dict]) -> str:
    name = (intake.get("answers", {}).get("Q010") or "unnamed").split("\n")[0]
    lines = [
        f"# Gaps - {name}",
        "",
        (
            f"Intake `{intake.get('id', '')}`, exported {intake.get('exported', '')}. "
            f"{len(gaps)} item(s) to resolve before the documents are written."
        ),
        "",
        "Send these as the 'Questions for me' table in the next weekly email. Ask one fact per line.",
        "",
        "| Ref | Status | Question | Field | Answer so far |",
        "| --- | --- | --- | --- | --- |",
    ]
    for g in gaps:
        a = g["answer"].replace("\n", " / ").replace("|", "/")
        lines.append(f"| {g['q']['id']} | {g['status']} | {g['q']['q']} | `{g['q']['map']}` | {a} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("intake", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True, help="application_data.yaml to write")
    ap.add_argument("--questions", type=Path, default=ASSETS / "questionnaire.json")
    ap.add_argument("--template", type=Path, default=ASSETS / "application_data.template.yaml")
    a = ap.parse_args(argv)

    intake = json.loads(a.intake.read_text(encoding="utf-8"))
    if intake.get("schema") != "mca-intake/1":
        print(f"warning: unexpected schema {intake.get('schema')!r}", file=sys.stderr)
    template = yaml.safe_load(a.template.read_text(encoding="utf-8"))
    doc, gaps = convert(intake, load_questions(a.questions), template)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Generated from intake " + intake.get("id", "") + " by intake_to_yaml.py.\n"
        "# Private customer data: do not commit to a public repository.\n"
    )
    a.out.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    gp = a.out.with_name("gaps.md")
    gp.write_text(gaps_markdown(intake, gaps), encoding="utf-8")
    stop = [g for g in gaps if g["status"].startswith("STOP")]
    print(
        f"wrote {a.out} and {gp}: {len(gaps)} gap(s)" + (" - STOP: cannabis reported at the new site" if stop else "")
    )
    return 2 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
