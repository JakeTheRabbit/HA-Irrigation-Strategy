# Crop Steering Academy

**A practical introduction for someone who has never used a moisture sensor or an irrigation controller.**

[Open the academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/) · [Try the isolated software demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) · [Course plan and workbook](#the-supporting-pack)

The academy teaches a beginner to explain a reading, understand a watering day and check what a Crop Steering action changes. It contains **24 lessons and 153 slides**. R3 includes a captioned 480p video for every lesson. Its five introductory paragraph-led lessons use 108 matched visual cards; the other 19 use 126 lesson-specific scenes. The R3 rebuild record contains the measured media checks and publication status. Five longer, chaptered parts combine related lessons, with separate alternative Pi and x86 setup parts. The public learning exercises do not connect to Home Assistant or operate equipment.

## Choose a learning route

Start with water, roots and air. Continue through VWC, capacity, dryback, EC and trustworthy readings before interpreting the combined graph. Then learn phases, steering direction and delivered-water calculations. The equipment overview explains what a complete system needs before any installation work.

| Route | Recommended sequence | Online lessons |
| --- | --- | ---: |
| Use an existing installation | A1–A6 → B1–B4 → C1 equipment overview → D1–D6 | 17 |
| Build with Raspberry Pi | A1–A6 → B1–B4 → C1 → C2a → C3–C7 → D1–D6 | 23 |
| Build with dedicated x86-64 | A1–A6 → B1–B4 → C1 → C2b → C3–C7 → D1–D6 | 23 |

C2a and C2b are alternatives. Existing suitable Home Assistant installations need not be erased or reinstalled for the course. Operators can study the software in the demo before local handover; independent live operation still requires that handover and verified commissioning evidence. Real operators also need a competent local handover covering the room/zone labels, physical shutdown and commissioning evidence. A demo can teach the interface before that handover, but cannot prove physical readiness. Builders should prove one zone before expanding.

Use several sessions and return to the exercises. Installation, measurement and local supervision take additional time; an online lesson count is not a physical-work deadline. The [course plan](training/crop-steering-from-zero/COURSE-PLAN.md) describes the gates, and the [equipment guide](training/crop-steering-from-zero/EQUIPMENT-AND-SETUP.md) gives the compatibility record and staged commissioning sequence.

## Learn, practise and return

Each lesson is one screen that never needs page scrolling, on a phone or a desktop. It runs as a sequence of steps: an introduction, then one step per section, then a practice task, then one knowledge-check question per screen and a result. On each section step the video plays only that section and pauses at its end. Beside it (below it on a phone) are the section's key points, any worked example and a **quick check** question. Continue unlocks once the check is answered correctly; after two wrong tries the answer is shown with its explanation, so nobody gets stuck. Every term is explained in plain words before the course relies on it, following the [term ledger](training/crop-steering-from-zero/R4-WRITING-GUIDE.md). Operators skip the setup lessons, so daily-operation lessons re-explain any setup term they use. The practice bench provides dryback and delivery calculations and a synthetic threshold graph whose recorded example observations do not move when a reference changes.

The lesson pattern is explanation, worked example, partly supported practice, independent practice and explanatory quiz feedback. Recall earlier ideas before revealing the answer, then revisit them after a delay.

This design draws on the IES practice guide [Organizing Instruction and Study to Improve Student Learning](https://ies.ed.gov/ncee/wwc/PracticeGuide/1), including worked examples, graphics with explanations, retrieval and spaced study. The academy's particular sequence and review intervals are design choices. **No learner outcome trial has been conducted**, so this release does not establish that the course improves competence or retention.

The lesson menu (☰) holds the step list, previous/next lesson, a selector for every lesson, the full transcript, transcript download, printable notes and sources. The step bar at the top shows progress and jumps to any step. Video controls offer replay section, captions on/off, playback speed and an option to turn off the automatic pause. Arrow keys move between steps. Text remains available when media cannot load. Diagrams have text alternatives. These features do not constitute a claim of complete accessibility conformance across every browser or assistive technology.

## Watch a longer part

Open **Course videos** from the course home or any lesson. Select a part, then use its section list or previous/next section buttons. The optional **Continue to the next video when this one ends** checkbox advances along your chosen learning route. Watching or skipping never passes a knowledge check.

| Part | Lessons |
| --- | --- |
| Foundations | A1–A6 |
| Watering and equipment | B1–B4 and C1 |
| Raspberry Pi setup | C2a and C3–C7 |
| Dedicated x86 setup | C2b and C3–C7 |
| Daily operation | D1–D6 |

Choose one setup route. Existing-installation operators can go from equipment to daily operation. Open a lesson from the player whenever you want its transcript, exercises, sources or knowledge check.

Athena's grow guide and resources informed the project. The relevant lessons link the official handbook and irrigation guide; see [references and acknowledgements](REFERENCES.md). Project examples and software workflows are separate from Athena's guidance.

## Progress and privacy

No learner account, Home Assistant login or LLM API key is required. Progress is stored in this browser for this site. It records the selected route, lesson positions, knowledge-check passes and review dates. There is no course account or cloud synchronisation.

Open **Progress** to export a JSON copy. Import it in another browser to continue there. **Import replaces that browser's current learning record**, so export first if you want to preserve it. Clearing site data, changing browser/profile or using private browsing can lose saved progress. If storage is unavailable, learning can continue in the current session; export before closing it.

The academy does not upload the progress record. Opening the site and loading media still makes normal requests to its hosting infrastructure. Exported progress is a personal file: store or share it deliberately. It contains no verified identity, instructor sign-off or installation inspection.

## Knowledge checks and physical safety

A knowledge pass requires at least 80% and every safety-critical answer correct. It records online practice, **not certification or proof that equipment is safe**. A quiz cannot establish electrical competence, plumbing suitability or a successful physical handover.

All crop numbers are examples. A measured condition, a configured reference and a draft setting are different evidence. Delivered-water estimates are not plant uptake. Check quantity, units, age and physical room/zone before interpreting data.

For real equipment, follow the [installation guide](INSTALL.md), the exact manufacturer's instructions and competent local supervision. Watering OFF blocks Controller ordinary, rescue and test shots; it does not physically isolate power or independent controls. Commissioning first uses an installer-approved bounded equipment catch test with Controller Watering OFF. Only after all readiness checks pass may a supervised enabled Controller cycle proceed. Prove the intended outlet, other zones staying dry, actual cessation and no unwanted siphon. The course teaches no mains wiring procedure.

## Language and media provenance

The writing uses short sentences, consistent terms and explicit actions informed by [ASD-STE100 Simplified Technical English](https://www.asd-ste100.org/). It has not undergone a full controlled-language conformity assessment and is **not represented as formally compliant or certified**.

R4 uses synthetic speech generated locally for all 24 lessons with [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx), voice `af_heart`. It reuses the 13 AI-generated physical teaching illustrations, 15 genuine isolated-demo screenshots and native calculation diagrams. These are combined into lesson scenes; the asset count is not the scene count. Generated pictures are conceptual explanations, not photographs of installed equipment or measured evidence. Caption timings and transcripts accompany the narration.

**Human listening review has not been performed.** File validation, caption generation and browser playback checks do not establish pronunciation, pacing or instructional quality. The course also has no completed learner outcome trial. These remain explicit review tasks when assessing a later edition.

## The supporting pack

| Resource | Purpose |
| --- | --- |
| [Course plan](training/crop-steering-from-zero/COURSE-PLAN.md) | Current four-module sequence, outcomes, practice and evidence gates; original production intentions are labelled historical |
| [Equipment and setup](training/crop-steering-from-zero/EQUIPMENT-AND-SETUP.md) | Functional kit, compatibility sheet, water/control paths and staged commissioning |
| [Learner workbook](training/crop-steering-from-zero/WORKBOOK.md) | Glossary, calculations, graph exercises, setup record, daily routine and explained answers |
| [Current source transcript](../www/learn/course/all-lesson-transcripts.txt) · [published transcript](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/course/all-lesson-transcripts.txt) | Generated narration and independent practice for all 24 lessons; the published copy changes only with a release |
| [Production and evidence](training/crop-steering-from-zero/PRODUCTION-AND-SOURCES.md) | Source ledger, production rationale and proposed evaluation/update process |

Course records, editable sources, local development and media checks are in the [Academy developer notes](dev/academy.md).
