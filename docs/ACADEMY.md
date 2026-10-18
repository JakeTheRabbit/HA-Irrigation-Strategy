# Crop Steering Academy

The [delivered edition and verification record](training/crop-steering-from-zero/DELIVERY-2026-10-19.md) distinguishes the live website from the source review and application release process.

[Open the academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/) · [Try the isolated software demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) · [Course plan and workbook](training/crop-steering-from-zero/README.md)

The academy teaches a beginner to explain a reading, understand a watering day and check what a Crop Steering action changes. It contains **24 lessons and 153 slides**. Five lessons preserve the saved Scarjo pilot videos in 480p, covering 27 slides. The other 19 lessons provide 126 interactive slides with locally generated Kokoro `af_heart` narration. The public learning exercises do not connect to Home Assistant or operate equipment.

## Choose a learning route

Start with water, roots and air. Continue through VWC, capacity, dryback, EC and trustworthy readings before interpreting the combined graph. Then learn phases, steering direction and delivered-water calculations. The equipment overview explains what a complete system needs before any installation work.

| Route | Recommended sequence | Online lessons |
| --- | --- | ---: |
| Use an existing installation | A1–A6 → B1–B4 → C1 equipment overview → D1–D6 | 17 |
| Build with Raspberry Pi | A1–A6 → B1–B4 → C1 → C2a → C3–C7 → D1–D6 | 23 |
| Build with dedicated x86-64 | A1–A6 → B1–B4 → C1 → C2b → C3–C7 → D1–D6 | 23 |

C2a and C2b are alternatives. Existing suitable Home Assistant installations need not be erased or reinstalled for the course. Operators can study the software in the demo before local handover; independent live operation still requires that handover and verified commissioning evidence. Builders should prove one zone before expanding.

Use several sessions and return to the exercises. Installation, measurement and local supervision take additional time; an online lesson count is not a physical-work deadline. The [course plan](training/crop-steering-from-zero/COURSE-PLAN.md) describes the gates, and the [equipment guide](training/crop-steering-from-zero/EQUIPMENT-AND-SETUP.md) gives the compatibility record and staged commissioning sequence.

## Learn, practise and return

Lessons connect a concrete object or screen to a short explanation. The new slide lessons include a worked example, a partly completed exercise and an independent problem with different data. Retrieval questions revisit earlier ideas. Quizzes explain why each answer is right or wrong and allow another attempt. The practice bench provides dryback and delivery calculations and a synthetic threshold graph whose recorded example observations do not move when a reference changes.

This design draws on the IES practice guide [Organizing Instruction and Study to Improve Student Learning](https://ies.ed.gov/ncee/wwc/PracticeGuide/1), including worked examples, graphics with explanations, retrieval and spaced study. The academy's particular sequence and review intervals are design choices. **No learner outcome trial has been conducted**, so this release does not establish that the course improves competence or retention.

Use the slide and complete lesson transcripts, downloadable transcript, timed English captions and pause controls. New slide narration includes playback-speed selection and a caption toggle. Pilot videos use browser video controls and caption tracks. Text remains available when media cannot load. Diagrams have text alternatives; controls support keyboard use. These features do not constitute a claim of complete accessibility conformance across every browser or assistive technology.

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

The five preserved pilot videos use the saved custom voice named Scarjo. The 19 new lessons use synthetic speech generated locally with [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx), voice `af_heart`. Native web slides and editable SVG diagrams explain the remaining material; they are not footage of physical installation. Caption timings and transcripts accompany the narration.

**Human listening review has not been performed.** File validation, caption generation and browser playback checks do not establish pronunciation, pacing or instructional quality. The course also has no completed learner outcome trial. These remain explicit review tasks when assessing a later edition.

## Editable sources and local development

The academy is a static site under [www/learn](../www/learn/). Edit lesson modules in [course/modules](../www/learn/course/modules/), glossary entries in [glossary.json](../www/learn/course/glossary.json), diagrams in [visuals.mjs](../www/learn/visuals.mjs), and practice behaviour in [labs.mjs](../www/learn/labs.mjs) and [practice.mjs](../www/learn/practice.mjs). Lesson text, correct-answer feedback, example values and diagram captions must agree. Keep physical evidence separate from online progress.

From the repository root:

```sh
python scripts/build_course.py
node --test tests/academy.test.mjs
python -m unittest tests.test_course_media -v
python scripts/install_course_media.py
python -m http.server 8080 --directory www
```

Open [the local academy](http://localhost:8080/learn/). Use an HTTP server rather than opening the HTML file directly, because the course loads JSON and media resources. The catalogue compiler validates lesson IDs, required content, quiz answers and prerequisites, then writes `www/learn/course/course.json`. It does not regenerate narration.

Large media masters stay outside Git history. Pages installs a versioned public release bundle using `www/learn/course/media-release.json`, which supplies an HTTPS `url` and the whole-archive `sha256`. The [installer](../scripts/install_course_media.py) verifies that pin before inspecting the ZIP, requires root `manifest.json` schema 1, binds each declared path to its byte count and SHA-256, rejects unsafe members, and stages a complete replacement. Every non-manifest file must be declared; the manifest does not list itself. The destination is restricted to this repository's `www/learn/media`.

For a previously downloaded matching bundle, use:

```sh
python scripts/install_course_media.py --archive /path/to/course-media.zip
```

The configured checksum remains mandatory for local archives. When replacing a media edition, publish the bundle, update its pin and verify the installed catalogue/media together. The [Pages workflow](../.github/workflows/pages.yml) builds the workspace and academy catalogue, runs knowledge/practice tests, installs the pinned media, then uploads `www`. Learners do not install Kokoro, provide keys or run these commands.
