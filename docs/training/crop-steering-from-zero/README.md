# Crop Steering from Zero

**A practical introduction for someone who has never used a moisture sensor or an irrigation controller.**

[Start the online academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/) · [Use the isolated software demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) · [Academy use, provenance and developer guide](../../ACADEMY.md)

Start inside the pot: water, roots and air. Learn what VWC and EC actually measure, then read a watering day and practise the control workflow. Builders continue through supported host installation, mapping and supervised commissioning. Operators can learn with fictional data before a local handover.

The 19 October 2026 academy edition contains **24 lessons and 153 slides**. Five rebuilt pilot videos are delivered in 480p and cover 27 slides through 108 paragraph-matched visual cards. The remaining 19 lessons contain 126 interactive slides with locally generated Kokoro `af_heart` narration. This directory holds the supporting teaching pack; editable lesson data and native SVG diagrams live in the website source.

## Choose your sequence

| Route | Sequence | Recommended online lessons |
| --- | --- | ---: |
| Existing-system operator | A1–A6 → B1–B4 → C1 overview → D1–D6 | 17 |
| Raspberry Pi builder | A1–A6 → B1–B4 → C1 → C2a → C3–C7 → D1–D6 | 23 |
| Dedicated x86-64 builder | A1–A6 → B1–B4 → C1 → C2b → C3–C7 → D1–D6 | 23 |

The host lessons are alternatives, not two required installations. Keep an existing suitable supported host rather than reinstalling it for practice. Real operators also need a competent local handover covering the room/zone labels, physical shutdown and commissioning evidence. A demo can teach the interface before that handover, but cannot prove physical readiness.

Use several sessions. The lesson pattern is explanation, worked example, partly supported practice, independent practice and explanatory quiz feedback. Recall earlier ideas before revealing the answer, then revisit them after a delay. This approach is informed by the IES [teaching and study practice guide](https://ies.ed.gov/ncee/wwc/PracticeGuide/1); **no learner outcome trial has been conducted for this course**.

## Read, listen and keep progress

Use captions, full transcripts and downloadable lesson transcripts if you prefer reading. New slide narration has pause, speed and caption controls. Pilot videos provide browser video controls and caption tracks. A media failure does not remove the lesson text. Diagrams include text alternatives and the website supports keyboard navigation.

Progress belongs to this browser and site. There is no learner account or cloud sync. In **Progress**, export a JSON copy before clearing site data, changing browser or importing another record. Import replaces the current browser record. When browser storage is blocked, continue in the current session and export before closing it. The course does not upload progress, although opening the website and media makes normal hosting requests. Learners need no Home Assistant credentials or LLM API keys.

The knowledge check requires at least 80% and every safety-critical answer correct. A pass is an online learning record, not professional certification, verified identity or evidence of safe hardware. The [equipment guide](EQUIPMENT-AND-SETUP.md) describes the separate physical checks.

## Open the supporting pack

| Resource | Purpose |
| --- | --- |
| [Course plan](COURSE-PLAN.md) | Four modules, outcomes, practice and evidence gates; includes the original production sequence |
| [Equipment and setup](EQUIPMENT-AND-SETUP.md) | Functional kit, compatibility sheet, water/control paths and staged commissioning |
| [Current complete transcript](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/course/all-lesson-transcripts.txt) | Recorded narration and independent practice for all 24 lessons |
| [Original pilot scripts](PILOT-SCRIPTS.md) | Archived production draft for the five pilot storyboards; superseded for narration by the current academy source |
| [Illustrated storyboard](storyboard/index.html) · [PDF](storyboard/storyboard.pdf) | Original 27-scene pilot planning material, with narration and production directions |
| [Learner workbook](WORKBOOK.md) | Glossary, calculations, graph exercises, setup record, daily routine and explained answers |
| [Production and evidence](PRODUCTION-AND-SOURCES.md) | Source ledger, production rationale and proposed evaluation/update process |
| [Editable lesson JSON](../../../www/learn/course/modules/) · [SVG diagram source](../../../www/learn/visuals.mjs) | The academy's authored lesson content and native teaching diagrams |

Planning documents can describe an earlier production intention. The current website source and pinned media release define this academy edition. Recheck interface explanations against the software release being taught.

## Limits and production disclosure

All crop numbers are examples. A software OFF state is not physical isolation. Watering OFF also blocks Controller test shots. First-water commissioning needs an installer-approved equipment catch test with the Controller disabled; a supervised enabled Controller cycle follows only after every readiness check passes. Prove the correct outlet, actual stopping and no unwanted siphon. No mains wiring tutorial is supplied.

The writing uses principles from [ASD-STE100](https://www.asd-ste100.org/), including short instructions and consistent terms. It has not been assessed for full formal conformance. All lessons use synthetic narration generated locally through [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx). Native slides are teaching illustrations, not footage proving an installation.

**Human listening review has not been performed.** Automated file and caption checks do not prove pronunciation, pacing, instructional quality or learner outcomes. The course does not certify an installation or replace manufacturer documentation and competent local supervision.

For catalogue compilation, local HTTP preview, tests and pinned-release installation, use the [developer workflow](../../ACADEMY.md#editable-sources-and-local-development). Large media is installed into the website from the checksum-pinned public bundle rather than committed as duplicate masters.
