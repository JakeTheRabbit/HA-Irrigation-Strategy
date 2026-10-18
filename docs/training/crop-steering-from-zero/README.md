# Crop Steering from Zero

**A practical introduction for someone who has never used a moisture sensor or an irrigation controller.**

[Start the online academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/) · [Use the isolated software demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) · [Academy use, provenance and developer guide](../../ACADEMY.md)

Start inside the pot: water, roots and air. Learn what VWC and EC actually measure, then read a watering day and practise the control workflow. Builders continue through supported host installation, mapping and supervised commissioning. Operators can learn with fictional data before a local handover.

The R3 course contains **24 lessons and 153 slides**, with 24 captioned 480p lesson videos and five longer chaptered parts. The five introductory paragraph-led lessons use 108 visual cards; the other 19 use 126 lesson scenes. The course uses 13 AI-generated teaching images and 15 real captures of the isolated application demo, alongside native calculation diagrams. The [R3 rebuild record](COURSE-REBUILD-2026-10-19-R3.md) records media verification and publication status. Editable modules and the generated transcript supply the current narration.

## Choose your sequence

| Route | Sequence | Recommended online lessons |
| --- | --- | ---: |
| Existing-system operator | A1–A6 → B1–B4 → C1 overview → D1–D6 | 17 |
| Raspberry Pi builder | A1–A6 → B1–B4 → C1 → C2a → C3–C7 → D1–D6 | 23 |
| Dedicated x86-64 builder | A1–A6 → B1–B4 → C1 → C2b → C3–C7 → D1–D6 | 23 |

The host lessons are alternatives, not two required installations. Keep an existing suitable supported host rather than reinstalling it for practice. Real operators also need a competent local handover covering the room/zone labels, physical shutdown and commissioning evidence. A demo can teach the interface before that handover, but cannot prove physical readiness.

Use several sessions. The lesson pattern is explanation, worked example, partly supported practice, independent practice and explanatory quiz feedback. Recall earlier ideas before revealing the answer, then revisit them after a delay. This approach is informed by the IES [teaching and study practice guide](https://ies.ed.gov/ncee/wwc/PracticeGuide/1); **no learner outcome trial has been conducted for this course**.

## Read, listen and keep progress

Use captions, full transcripts and downloadable lesson transcripts if you prefer reading. Each lesson player has previous/next lesson controls above and below the material, an all-lesson selector and video section controls. Sections seek within the video; skipping or watching does not pass the knowledge check. **Watch the course videos** opens the five chaptered parts, with an optional next-video continuation setting. Captions appear below the picture. A media failure does not remove the lesson text, and controls support keyboard navigation.

Progress belongs to this browser and site. There is no learner account or cloud sync. In **Progress**, export a JSON copy before clearing site data, changing browser or importing another record. Import replaces the current browser record. When browser storage is blocked, continue in the current session and export before closing it. The course does not upload progress, although opening the website and media makes normal hosting requests. Learners need no Home Assistant credentials or LLM API keys.

The knowledge check requires at least 80% and every safety-critical answer correct. A pass is an online learning record, not professional certification, verified identity or evidence of safe hardware. The [equipment guide](EQUIPMENT-AND-SETUP.md) describes the separate physical checks.

## Open the supporting pack

| Resource | Purpose |
| --- | --- |
| [R3 rebuild record](COURSE-REBUILD-2026-10-19-R3.md) | Current rewrite, asset scope, verification gates and publication status |
| [Course plan](COURSE-PLAN.md) | Current four-module sequence, outcomes, practice and evidence gates; original production intentions are labelled historical |
| [Equipment and setup](EQUIPMENT-AND-SETUP.md) | Functional kit, compatibility sheet, water/control paths and staged commissioning |
| [Current source transcript](../../../www/learn/course/all-lesson-transcripts.txt) · [published transcript](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/course/all-lesson-transcripts.txt) | Generated narration and independent practice for all 24 lessons; the published copy changes only with a release |
| [Original pilot scripts](PILOT-SCRIPTS.md) | Archived production draft for the five pilot storyboards; superseded for narration by the current academy source |
| [Historical storyboard](storyboard/index.html) · [PDF](storyboard/storyboard.pdf) | Original 27-scene pilot planning material, superseded for current narration and timing |
| [Learner workbook](WORKBOOK.md) | Glossary, calculations, graph exercises, setup record, daily routine and explained answers |
| [Production and evidence](PRODUCTION-AND-SOURCES.md) | Source ledger, production rationale and proposed evaluation/update process |
| [Editable lesson JSON](../../../www/learn/course/modules/) · [SVG diagram source](../../../www/learn/visuals.mjs) | The academy's authored lesson content and native teaching diagrams |

Edit narration in [lesson modules](../../../www/learn/course/modules/), then regenerate the catalogue and transcript. Do not maintain a second spoken script in the archived pilot document. The source defines the intended edition; the pinned release and verified deployment establish what learners can currently load. Athena resources are credited in the relevant lessons and [references and acknowledgements](../../REFERENCES.md).

## Limits and production disclosure

All crop numbers are examples. A software OFF state is not physical isolation. Watering OFF also blocks Controller test shots. First-water commissioning needs an installer-approved equipment catch test with the Controller disabled; a supervised enabled Controller cycle follows only after every readiness check passes. Prove the correct outlet, actual stopping and no unwanted siphon. No mains wiring tutorial is supplied.

The writing uses principles from [ASD-STE100](https://www.asd-ste100.org/), including short instructions and consistent terms. It has not been assessed for full formal conformance. All lessons use synthetic narration generated locally through [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx). AI-generated illustrations, native diagrams and screenshots of the isolated demo explain the lesson; none is evidence of a real installed system.

**Human listening review has not been performed.** Automated file and caption checks do not prove pronunciation, pacing, instructional quality or learner outcomes. The course does not certify an installation or replace manufacturer documentation and competent local supervision.

For catalogue compilation, local HTTP preview, tests and pinned-release installation, use the [developer workflow](../../ACADEMY.md#editable-sources-and-local-development). Large media is installed into the website from the checksum-pinned public bundle rather than committed as duplicate masters.
