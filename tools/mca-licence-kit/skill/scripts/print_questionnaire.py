#!/usr/bin/env python3
"""Make a printable A4 HTML questionnaire from assets/questionnaire.json.

Usage:
    python print_questionnaire.py -o intake-form.html [--questions questionnaire.json]
Open the HTML in a browser and print to PDF (A4). Pure standard library.
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

CSS = """
@page{size:A4;margin:14mm 14mm 16mm}
:root{--ink:#1d241f;--muted:#5d6a61;--line:#c9d1c8;--accent:#2f6b3f}
body{font:10.5pt/1.4 "Helvetica Neue",Arial,sans-serif;color:var(--ink);margin:0;background:#fff}
.page{max-width:182mm;margin:0 auto;padding:12px 16px}
h1{font-size:19pt;margin:0 0 2mm;color:var(--accent)}
h2{font-size:13pt;margin:7mm 0 2mm;padding-bottom:1mm;border-bottom:1.5pt solid var(--accent);break-after:avoid}
.intro{border:1pt solid var(--line);border-radius:3mm;padding:3mm 4mm;margin:3mm 0}
.intro li{margin:1mm 0}
.q{break-inside:avoid;margin:0 0 3mm;padding:2mm 0;border-bottom:.5pt dotted var(--line)}
.q b{display:block}
.id{font:8pt monospace;color:var(--muted);margin-right:2mm}
.req{color:#a4501a;font-size:8pt;margin-left:1mm}
.help{font-size:8.5pt;color:var(--muted);margin:1mm 0}
.ans{height:13mm;border:.5pt solid var(--line);border-radius:1.5mm;margin-top:1.5mm}
.ans.tall{height:24mm}.ans.huge{height:70mm}
.opts{font-size:9.5pt;margin-top:1mm}.opts span{margin-right:5mm}
.photo{font-size:8.5pt;margin-top:1mm}
.meta{color:var(--muted);font-size:9pt}
.cond{font-size:8.5pt;color:var(--muted);font-style:italic;margin:0 0 2mm}
@media screen{body{background:#eef1ec}.page{background:#fff;margin:16px auto;box-shadow:0 1px 6px rgba(0,0,0,.15)}}
@media (max-width:600px){.page{padding:12px}}
"""


def render(q: dict) -> str:
    out = [
        (
            "<!doctype html><html lang='en-NZ'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>Licence Intake Form</title>"
            f"<style>{CSS}</style></head><body><div class='page'>"
        ),
        (
            f"<h1>{escape(q['title'])}</h1><div class='meta'>Questionnaire v{escape(q['version'])} · "
            "New Zealand Medicinal Cannabis Agency licence: new, amendment or renewal</div>"
        ),
        "<div class='intro'><b>How to use this form</b><ul>"
        + "".join(f"<li>{escape(n)}</li>" for n in q["notes"])
        + "<li>Questions marked <span class='req'>required</span> must have an answer before we write the application.</li>"
        "<li>Routes: " + "; ".join(f"<b>{escape(k)}</b> = {escape(v)}" for k, v in q["routes"].items()) + ".</li>"
        "</ul></div>",
    ]
    for s in q["sections"]:
        out.append(f"<h2>{escape(s['title'])}</h2>")
        if s.get("show_if"):
            out.append(
                "<p class='cond'>Only for routes: "
                + escape(", ".join(r for v in s["show_if"].values() for r in v))
                + "</p>"
            )
        for x in s["questions"]:
            h = (
                f"<div class='q'><b><span class='id'>{x['id']}</span>{escape(x['q'])}"
                + ("<span class='req'>required</span>" if x.get("required") else "")
                + "</b>"
            )
            if x.get("help"):
                h += f"<div class='help'>{escape(x['help'])}</div>"
            if x["type"] in ("choice", "yesno"):
                opts = ["yes", "no", "not known"] if x["type"] == "yesno" else x["options"] + ["not known"]
                h += (
                    "<div class='opts'>"
                    + "".join(f"<span>☐ {escape(o)}</span>" for o in opts)
                    + "</div><div class='ans'></div>"
                )
            elif x["type"] in ("layout", "sketch"):
                h += "<div class='ans huge'></div>"
            else:
                h += f"<div class='ans{' tall' if x['type'] in ('text', 'photos') else ''}'></div>"
            if x.get("photo") or x["type"] == "photos":
                h += f"<div class='photo'>☐ Photo taken: {escape(x.get('photo', 'yes'))}</div>"
            out.append(h + "</div>")
    out.append("</div></body></html>")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--questions", type=Path, default=ASSETS / "questionnaire.json")
    a = ap.parse_args(argv)
    a.out.write_text(render(json.loads(a.questions.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
