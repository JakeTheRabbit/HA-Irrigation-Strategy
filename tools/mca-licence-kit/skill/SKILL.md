---
name: mca-licence-builder
description: Prepare New Zealand Medicinal Cannabis Agency (MCA) licence applications for indoor grow facilities - new licences, amendments that add or change a location, and renewals. Use when a consultant needs to take a customer from first interview to a lodged, audit-clean package; to turn an intake questionnaire (intake.json from the Grow Licence Intake app) into a data file; to draw the site layout and floor plans; to run a pre-lodgement audit; or to write the customer emails, weekly to-do lists and information-request replies. Triggers on "licence application", "MCA", "Medicinal Cannabis Agency", "Form A", "Form LA", "Form RA", "renewal", "add a location", "grow facility licence", "site security plan", "floor plan for the licence", "intake.json".
---

# MCA licence builder

This skill makes a complete, consistent MCA licence package for one grow facility. It also
runs the customer communication around it. One data file holds every fact. Every document,
map and email comes from that file. A readiness check blocks lodging while a gap is open.

The method comes from a real amendment for a container-based indoor site. A desk audit of
that package found 3 blockers and 25 high-risk issues before lodging. Each lesson is in
`references/audit-checklist.md`. Apply them from the first interview, not at the end.

## Workflow

Do the steps in this order. Do not skip the gate at the end of a step.

1. **Intake.** Send the customer through the questionnaire (Android app or the printable form,
   `assets/questionnaire.json`). Result: `intake.json`, photos, `layout.png`, `sketch.png`.
   Gate: route (new / amend / renew / other) is known.
2. **Data file.** Run `scripts/intake_to_yaml.py intake.json -o <case>/application_data.yaml`.
   It fills `assets/application_data.template.yaml` and writes `gaps.md`, the list of
   unanswered or "not known" facts, each with its owner.
   Gate: you read every answer against the photos. Spoken answers are short. "Yes" or "there
   will be" is not a fact. Ask again until each field holds one specific fact.
3. **Follow-up questions.** Send the gaps to the customer in the weekly email
   (`references/client-comms.md`). Give each question a reference (for example `XX-07`) and
   one fact to supply. Keep the case tracker (one row per reference) up to date.
4. **Third-party evidence.** Start the slow items on day 1: record of title (LINZ), landlord
   and owner consent, the buyer's licence copy and signed supply agreement, council position,
   beforeUdig and pipeline operator, installer quotes. These decide the licensed area and the
   documents that depend on it.
5. **Site layout and floor plans.** Decide the licensed area first. Recommended: a small,
   newly fenced compound around the grow buildings, not the whole lot. Then run
   `scripts/floorplan.py application_data.yaml -o <case>/plans`. It draws the site plan
   (Figure 1) and a unit plan for each building type (Figure 2), A4, with scale bar,
   north arrow, legend, licensed area, fence, gates, cameras and alarm devices.
   See `references/floor-plans.md`.
   Gate: the customer checks each plan on site and says what is wrong.
6. **Documents.** Write the package in `references/document-set.md` order. Use the data file
   for every fact. Use the future tense for anything not built. Never write "draft" on a
   document you will send.
7. **Readiness check and audit.** Run `scripts/readiness_check.py application_data.yaml`.
   Then do the audit in `references/audit-checklist.md`, as the MCA assessor would read it.
   Gate: zero blockers. Each high item is fixed, or the cover letter answers it.
8. **Signing.** Statutory declarations go before a JP in the week of lodging, on the final
   forms. The name must match the ID exactly. After any change to a sworn fact, swear again.
9. **Lodge.** Email 1 = the package PDFs, one file per attachment, in list order. Email 2 and
   3 = videos, as replies. Phone the MCA the next working day to confirm receipt.
10. **After lodging.** Pay each invoice on the day it arrives. Answer each information request
    within 48 hours. Finish and test the build. Assemble the inspection evidence pack. Ask for
    the inspection only when the MCA says you can, with at least one month's notice.
11. **Renewal.** One licence has one expiry date. A location added by amendment expires with
    the licence. Diary the renewal window on day 1 (`references/mca-process.md`).

## Rules that prevent the common failures

- One fact per question, one source per fact. If two documents say different things, the
  data file is wrong. Fix the data file and rebuild. Do not hand-edit a built document.
- Never alter a used record (manifest, register, return). Write a signed, dated correction
  note and keep the original. If cannabis was at an unlicensed site, stop: get legal advice.
- Name the real legal entity for every third party (monitoring company, buyer, landlord,
  owner). Check each one on the Companies Office and the MCA licence-holder list.
- The buyer must hold the activity the application says it holds (for example possession
  for manufacture). Get a copy of its licence. A sworn form must not say more than you can prove.
- The registered owner on the title must consent, not only the person who calls himself the
  landlord. The consent must name the licence, the site and the licensed area on a plan.
- Every security item that is not built is "will be installed and tested before the
  inspection" with a supplier and a date. Never describe it as existing.
- Put a wired camera inside each room (two where racks block the view) and at each point of
  entry. Battery and solar cameras do not count.
- Show every structure, entrance and vehicle crossing on the plan, inside or outside the
  licensed area. An unexplained gate or building is an information request.
- State upper limits for research quantities, dried stock held and plant numbers.
- Consultant authority: the cover letter says who the consultant is, what the consultant may
  do, and any link to another licence holder.
- Ask for confidentiality of the security documents under the OIA (s 6(c) and 9(2)(b)(ii)).
- Keep customer data private. Do not put a customer's names, addresses or licence numbers in
  a public repository. Keep each case in a private folder.

## Files

| Path | Use |
| --- | --- |
| `assets/questionnaire.json` | The intake questions (single source for the app and the printable form) |
| `assets/application_data.template.yaml` | The data file template with every field and its meaning |
| `scripts/intake_to_yaml.py` | intake.json to application_data.yaml plus gaps.md |
| `scripts/floorplan.py` | Site plan and unit plans as SVG and PDF (A4) |
| `scripts/readiness_check.py` | Blocks lodging on placeholders, missing evidence and contradictions |
| `scripts/print_questionnaire.py` | Printable A4 questionnaire (HTML) from the JSON |
| `references/mca-process.md` | Forms, fees, time limits, renewal window, inspection |
| `references/document-set.md` | The package, file by file, with what each must contain |
| `references/audit-checklist.md` | Pre-lodgement audit, from the lessons of a real audit |
| `references/client-comms.md` | Email templates: kick-off, weekly list, JP day, lodge day, chasers, RFI reply |
| `references/floor-plans.md` | Drawing rules and the layout data format |

## Output style

Write documents for the MCA in plain, formal New Zealand English. Write instructions for the
customer in ASD-STE100 style: short sentences, one instruction per sentence, active voice,
the verb first. Give dates as "Tue 13 Oct 2026". Give money with GST status.
