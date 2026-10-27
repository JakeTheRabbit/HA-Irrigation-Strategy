# Crop Steering Academy — delivery specification

User request: finish the five simplified Scarjo pilots, then create the rest of the tutorials without Higgsfield, choose a suitable teaching voice, build a scaffolded e-learning website, and host it on the existing website.

## Decisions

- Finish and preserve the five revised pilots at C:/Content/Crop Steering from Zero/2026-10-19-STE-Scarjo.
- Publish a 24-lesson academy at the existing GitHub Pages site under /learn/. Preserve the functioning Crop Steering dashboard and demo.
- Four modules follow COURSE-PLAN.md: A1–A6, B1–B4, C1/C2a/C2b/C3–C7, D1–D6. Pi and x86-64 host lessons are alternatives, not cumulative requirements.
- The five existing pilots use the selected saved Scarjo voice. Remaining 19 lessons use local Kokoro af_heart neural speech at a measured teaching pace. No more Higgsfield generation after the five-pilot revision. Disclose synthetic narration.
- Native web slides, exact SVG diagrams, worked examples, progressively reduced assistance, independent practice, explanatory retry feedback, spaced review, glossary, transcripts/captions, route choice, local progress and export/import.
- No account required. Progress belongs to this browser and can be exported/imported. Do not imply cloud sync, instructor verification or professional certification.
- New lessons are narrated interactive slide lessons, not claims of filmed physical installation. Existing pilot MP4s remain available. Public learning examples must not operate Home Assistant.
- All numerical crop settings are examples. Preserve distinctions between actual/saved/draft, EC types, water delivery/uptake, program reference/physical capacity, and software OFF/physical isolation.
- Physical commissioning and handover require competent local supervision. Passing a quiz is not evidence that hardware is safe.
- Media generation and masters live under C:/Content. The code repository stores editable lesson data and the website. Large generated media is distributed through versioned GitHub release assets and incorporated into the Pages build, rather than duplicating masters in Git history.

## Lesson JSON interface

Each module file is a JSON array of lesson objects:

{id, module, title, summary, outcomes: string[], prerequisites: string[], route: everyone|builder|pi|x86|operator, slides: [{id,title,body:string[],narration,visual:{type,title?,labels?:string[],values?:number[],caption?:string}, workedExample?:{prompt,steps:string[],answer}}], practice:{kind,prompt,hints:string[],success}, quiz:[{id,prompt,options:[{text,correct,feedback}],safetyCritical:boolean}], practicalTask:{instructions:string[],requiresLocalSupervision:boolean,proof:explain|demo|physical}, sources:[{title,url,accessed}]}

Supported visuals: root-zone, fraction, capacity, dryback, ec-path, sensor-check, combined-graph, phases, steering, flow, equipment, host, entities, water-path, controls, mapping, commissioning, navigation, target, calendar, comparison, troubleshooting, daily-check. Other types fall back to an accessible labeled process diagram.

Each new lesson: 6–8 useful slides; 400–650 spoken words in total, with complete teachable explanations. Include at least one worked example, a partially completed task, an independent task with different data, and recall of an earlier idea. 3–5 meaningful quiz questions with specific feedback per option. Do not generate placeholders or question sets that merely repeat the same example.

## Acceptance

24 substantive lessons; all 19 new lessons have generated audio and timed captions; all 5 pilot MP4s play; every quiz has one correct option and feedback; progress resumes and survives malformed input/storage failures; alternative host routes work; calculations and synthetic threshold graph are correct; mobile/keyboard/contrast checks pass; sources link to primary documentation; public Pages URL and media return successful responses after deployment.
