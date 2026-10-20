#!/usr/bin/env python3
"""Print a release's GitHub notes from CHANGELOG.md.

    gh release create v2.21.0 --prerelease --target testing --title "2.21.0 (candidate)" \\
      --notes-file <(python scripts/release_notes.py 2.21.0)

The notes are the entry's opening paragraph and its "🌱 In plain English" section, with a link to
the technical notes at that tag. HACS shows a release's notes in its update dialog, so this is what
the people updating read. Links in the changelog are relative to the repository; on a release page
they would break, so they are rewritten to point at the files at that tag.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAIN = "### 🌱 In plain English"


def entry(changelog: str, version: str) -> str:
    """The body of `## [version]`, up to the next `## [` heading."""
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n", changelog, re.M)
    if not match:
        raise SystemExit(f"CHANGELOG.md has no entry for {version}")
    rest = changelog[match.end() :]
    following = re.search(r"^## \[", rest, re.M)
    return rest[: following.start()] if following else rest


def unwrap(text: str) -> str:
    """Join hard-wrapped lines back into their paragraph or bullet. A release page and HACS's
    dialog may render every newline as a line break, and the changelog is wrapped at 100.
    """
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        starts_block = (
            not stripped
            or fenced
            or re.match(r"(#{1,6} |[-*+] |\d+\. |\|)", stripped)
            or not out
            or not out[-1].strip()
            or out[-1].strip().startswith(("#", "```", "|"))
        )
        if starts_block:
            out.append(line)
        else:
            out[-1] = f"{out[-1].rstrip()} {stripped}"
    return "\n".join(out)


def notes(changelog: str, version: str, repository: str) -> str:
    body = entry(changelog, version)
    if PLAIN not in body:
        raise SystemExit(f"the {version} entry has no '{PLAIN}' section")
    opening, _, after = body.partition(PLAIN)
    plain = re.split(r"^### ", after, maxsplit=1, flags=re.M)[0]
    at_tag = f"{repository}/blob/v{version}"
    text = (
        f"{unwrap(opening.strip())}\n\n{PLAIN}\n\n{unwrap(plain.strip())}\n\n"
        f"Technical notes: [CHANGELOG.md at v{version}]({at_tag}/CHANGELOG.md)\n"
    )
    # [text](docs/INSTALL.md) -> [text](<repository>/blob/v<version>/docs/INSTALL.md)
    return re.sub(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", rf"]({at_tag}/\1)", text)


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    version = argv[1].removeprefix("v")
    manifest = json.loads(
        (ROOT / "custom_components" / "crop_steering" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # The notes carry "🌱", which a Windows console or pipe (cp1252) cannot encode.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(notes(changelog, version, manifest["documentation"].rstrip("/")))


if __name__ == "__main__":
    main(sys.argv)
