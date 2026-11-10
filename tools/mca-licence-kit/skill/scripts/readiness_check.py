#!/usr/bin/env python3
"""Readiness check for an MCA package. Exits 1 while any blocker is open.

Usage:
    python readiness_check.py application_data.yaml [--submit-dir SUBMIT]

Blockers: placeholders like [licence number] anywhere, missing core facts, no signed supply
evidence, cannabis reported at an unlicensed site, and (with --submit-dir) placeholders or
.docx/.txt files in the folder that goes to the MCA. Warnings: every `confirm:` item, high-risk
gaps from the audit checklist, and renewal-window timing.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

NZ = ZoneInfo("Pacific/Auckland")
PLACEHOLDER = re.compile(r"\[[^\]\n]{2,40}\]|_{6,}|\bTBC\b|\bXXX+\b", re.IGNORECASE)

CORE = {  # path -> why (blocker when empty)
    "applicant.legal_name": "Applicant legal name",
    "applicant.company_number": "Company number",
    "applicant.director.full_name": "Responsible person name exactly as on the ID",
    "site.one_line": "Site address",
    "site.legal_description": "Legal description (Lot/DP)",
    "site.owner": "Registered owner on the title (owner consent)",
    "supply.buyer_name": "Where the crop goes (the MCA returns applications without it)",
    "supply.buyer_licence": "Buyer's licence number and activity",
}
HIGH = {
    "security.alarm_monitoring_company": "Monitoring company exact legal name",
    "security.alarm_installer": "Alarm installer and security technician licence",
    "records.electronic_system": "Electronic record system (product, version, host, owner)",
    "planning.council": "Council position on consent, in writing",
    "planning.nearest_dwelling_m": "Distance to nearest dwelling",
    "cultivation.max_dried_kg": "Maximum dried stock held on site",
    "staff.list": "Staff, witnesses",
    "timeline.build_complete": "Realistic build-finish date",
    "odour.filters_installed": "Carbon filters fitted, or the date they will be",
}


def get(doc, path):
    cur = doc
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def empty(v) -> bool:
    return v is None or (isinstance(v, str) and (not v.strip() or v.strip().lower().startswith("not known"))) or v == []


def walk_strings(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_strings(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def parse_date(s: str):
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%a %d %b %Y", "%A %d %B %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=NZ).date()
        except (ValueError, AttributeError):
            pass
    return None


def check(doc: dict, submit: Path | None) -> tuple[list[str], list[str], list[str]]:
    blockers, warnings, info = [], [], []
    route = (get(doc, "meta.route") or "").strip()

    for path, text in walk_strings(doc):
        if ".confirm" in path or path.startswith("meta.") or "help" in path:
            continue
        if PLACEHOLDER.search(text):
            blockers.append(f"Placeholder in {path}: {PLACEHOLDER.search(text).group(0)!r}")

    for p, why in CORE.items():
        if empty(get(doc, p)):
            blockers.append(f"Missing {why} ({p})")
    if route in ("amend", "renew", "other") and empty(get(doc, "licence.number")):
        blockers.append("Missing current licence number (licence.number)")
    if not (get(doc, "supply.agreement_pdf") or "").strip():
        kind = (get(doc, "supply.agreement_kind") or "").lower()
        blockers.append(
            "No signed supply agreement or letter of intent file (supply.agreement_pdf)"
            + ("" if "signed" in kind else f" - intake says: {kind or 'not given'}")
        )
    if (get(doc, "records.cannabis_at_new_site") or "").lower().startswith("yes"):
        blockers.append("Cannabis reported at the new site before approval: STOP and get legal advice")
    if "change" in (get(doc, "records.known_issues") or "").lower():
        warnings.append("Record issue mentions 'change': correct by signed note only, never alter a used record")

    for p, why in HIGH.items():
        if empty(get(doc, p)):
            warnings.append(f"HIGH: {why} ({p})")
    if not (get(doc, "layout.items") or []):
        warnings.append("HIGH: no site layout drawn (layout.items) - floor plans cannot be built")
    lic = (get(doc, "supply.buyer_licence") or "").lower()
    if lic and "manufactur" not in lic:
        warnings.append(
            "HIGH: buyer licence does not mention manufacture - prove the activity before any sworn form says it"
        )
    for p in ("security.alarm_monitoring_company", "supply.buyer_name", "site.owner"):
        v = get(doc, p) or ""
        if v.strip() and not re.search(r"\b(limited|ltd|trust|incorporated|inc|council)\b", v, re.IGNORECASE):
            warnings.append(f"HIGH: {p} = {v!r} is not a legal entity name - check the Companies Office")
    if re.search(
        r"battery|solar|wireless|wi-?fi",
        str(get(doc, "security.cctv_existing")) + str(get(doc, "security.cctv")),
        re.IGNORECASE,
    ):
        warnings.append("HIGH: battery, solar or wireless cameras mentioned - only wired cameras count")
    if (get(doc, "planning.public_access") or "").lower().startswith("yes"):
        warnings.append("HIGH: the public visits the property - rethink the perimeter")
    try:
        d = float(str(get(doc, "planning.nearest_dwelling_m") or "").split()[0])
        if d < 120:
            warnings.append(
                f"Nearest dwelling {d:g} m (< 120 m in some SOPs): strengthen the odour and visibility plan"
            )
    except (ValueError, IndexError):
        pass

    for path, text in walk_strings(doc):
        if ".confirm[" in path:
            warnings.append(f"CONFIRM: {text}")

    exp = parse_date(get(doc, "timeline.licence_expiry") or "")
    if exp:
        opens, closes = exp - timedelta(days=90), exp - timedelta(days=31)
        info.append(
            f"Licence expiry {exp:%a %d %b %Y}. Renewal window about {opens:%a %d %b %Y} to "
            f"{closes:%a %d %b %Y} (check the Form RA wording). Diary both dates."
        )
        if route == "amend" and datetime.now(NZ).date() < closes:
            info.append(
                "Amendment before renewal: the MCA gives the renewal priority and the added location "
                "shares the expiry. Ask the MCA in writing how to sequence them."
            )

    if submit and submit.is_dir():
        for f in sorted(submit.rglob("*")):
            if f.suffix.lower() in (".docx", ".doc", ".txt") and "body" not in f.name.lower():
                blockers.append(f"Working file in SUBMIT: {f.relative_to(submit)} (send PDFs only)")
            if f.suffix.lower() == ".txt" and f.stat().st_size < 200_000:
                m = PLACEHOLDER.search(f.read_text(encoding="utf-8", errors="ignore"))
                if m:
                    blockers.append(f"Placeholder {m.group(0)!r} in {f.relative_to(submit)}")
            if "draft" in f.name.lower():
                blockers.append(f"'draft' in a file name in SUBMIT: {f.name}")
    return blockers, warnings, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("--submit-dir", type=Path)
    a = ap.parse_args(argv)
    doc = yaml.safe_load(a.data.read_text(encoding="utf-8")) or {}
    blockers, warnings, info = check(doc, a.submit_dir)
    for i in info:
        print("INFO   ", i)
    for w in warnings:
        print("WARN   ", w)
    for b in blockers:
        print("BLOCKER", b)
    print(
        f"\n{len(blockers)} blocker(s), {len(warnings)} warning(s). "
        + ("NOT READY TO LODGE." if blockers else "No blockers: do the audit checklist next.")
    )
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
