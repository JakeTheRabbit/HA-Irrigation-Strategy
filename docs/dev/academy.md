# Crop Steering Academy: developer notes

For course authors and contributors. The learner guide is [ACADEMY.md](../ACADEMY.md).

## Course records

The [R4 rebuild record](../training/crop-steering-from-zero/COURSE-REBUILD-2026-10-20-R4.md) tracks the current rewrite, media build and checks; the [R4 writing guide](../training/crop-steering-from-zero/R4-WRITING-GUIDE.md) holds the scaffolding rules and term ledger every lesson follows. The [R3 rebuild record](../archive/academy/COURSE-REBUILD-2026-10-19-R3.md), [R2 pilot repair](../archive/academy/PILOT-REPAIR-2026-10-19.md) and [original delivery record](../archive/academy/DELIVERY-2026-10-19.md) are historical records of earlier editions.

Edit narration in [lesson modules](../../www/learn/course/modules/), then regenerate the catalogue and transcript. Do not maintain a second spoken script in the archived pilot document. The source defines the intended edition; the pinned release and verified deployment establish what learners can currently load. Athena resources are credited in the relevant lessons and [references and acknowledgements](../REFERENCES.md).

## Editable sources and local development

The academy is a static site under [www/learn](../../www/learn/). Edit lesson modules in [course/modules](../../www/learn/course/modules/), glossary entries in [glossary.json](../../www/learn/course/glossary.json), diagrams in [visuals.mjs](../../www/learn/visuals.mjs), and practice behaviour in [labs.mjs](../../www/learn/labs.mjs) and [practice.mjs](../../www/learn/practice.mjs). Lesson text, correct-answer feedback, example values and diagram captions must agree. Keep physical evidence separate from online progress.

From the repository root:

```sh
python scripts/build_course.py
node --test tests/academy.test.mjs
python -m unittest tests.test_course_media tests.test_academy_catalogue -v
python scripts/install_course_media.py
npm ci --prefix frontend
node frontend/node_modules/vite/bin/vite.js preview --outDir www --host 127.0.0.1 --port 8080
```

Open the local academy at `http://localhost:8080/learn/` on your own install (the public academy is linked at the top of this page). Use the Vite preview server rather than opening the HTML file directly. It serves JSON, modules and byte-range requests for video seeking; Python’s basic HTTP server does not provide reliable seeking in this browser. The catalogue compiler validates lesson IDs, required content, quiz answers and prerequisites, then writes `www/learn/course/course.json`. When `course/video-index.json` is present, it must bind all 24 videos to the current narration hash and exact chapter IDs. `course/video-groups.json` defines the five parts and their learning-route coverage. The compiler does not regenerate narration.

Large media masters stay outside Git history. Pages installs a versioned public release bundle using `www/learn/course/media-release.json`, which supplies an HTTPS `url` and the whole-archive `sha256`. The [installer](../../scripts/install_course_media.py) verifies that pin before inspecting the ZIP, requires root `manifest.json` schema 1, binds each declared path to its byte count and SHA-256, rejects unsafe members, and stages a complete replacement. Every non-manifest file must be declared; the manifest does not list itself. The destination is restricted to this repository's `www/learn/media`.

Stop the local preview server before replacing media on Windows; its directory watch can prevent the installer’s atomic folder replacement. For a previously downloaded matching bundle, use:

```sh
python scripts/install_course_media.py --archive /path/to/course-media.zip
```

The configured checksum remains mandatory for local archives. When replacing a media edition, publish the bundle, update its pin and run `python scripts/build_course.py --verify-media` against the installed catalogue/media. This requires all 24 lesson videos, five route-complete groups, all 153 narration bindings and matching file byte counts and SHA-256 hashes. A failed check leaves the generated catalogue and transcript untouched. The [Pages workflow](../../.github/workflows/pages.yml) builds the workspace and academy catalogue, runs knowledge/practice tests, installs the pinned media, then uploads `www`. Learners do not install Kokoro, provide keys or run these commands.


## Verify a completed video edition

Serve the compiled website for media checks. Vite preview preserves the published HTML bytes and supports byte-range requests for seeking:

```sh
node frontend/node_modules/vite/bin/vite.js preview --outDir www --host 127.0.0.1 --port 8794
node tests/academy-navigation.browser.mjs
node tests/academy-video.browser.mjs
node tests/academy.browser.mjs
node tests/academy-media.browser.mjs
```

The media check requires all 24 individual videos and five longer parts, verifies caption words against current scripts, decodes and seeks each video, and checks the actual served dashboard bytes. `HASH_MEDIA=1` additionally downloads and hashes every video against the installed manifest. Use `BASE_URL` to repeat against the published academy.

With the private production masters available, set `ACADEMY_PRODUCTION` and run `node tests/academy-scene-sync.browser.mjs`. It compares decoded video scenes with their source-bound PNGs, including a changed-pixel check that the draft threshold actually moves. `QA_PARTIAL=1` permits an explicitly labelled check of completed files during production; it never establishes that all 29 videos are complete.

Assemble with [build_course_videos.py](../../scripts/build_course_videos.py), then package completed outputs with [package_course_videos.py](../../scripts/package_course_videos.py). Source masters stay outside Git. The final archive and installed media must pass the strict compiler and browser checks before publication. Synthetic speech still needs human listening review; these checks do not establish learner outcomes.

## Production records and sources

| Resource | Purpose |
| --- | --- |
| [R3 rebuild record](../archive/academy/COURSE-REBUILD-2026-10-19-R3.md) | R3 rewrite, asset scope, verification gates and publication status |
| [Original pilot scripts](../archive/academy/PILOT-SCRIPTS.md) | Archived production draft for the five pilot storyboards; superseded for narration by the current academy source |
| [Historical storyboard](../archive/academy/storyboard/index.html) · [PDF](../archive/academy/storyboard/storyboard.pdf) | Original 27-scene pilot planning material, superseded for current narration and timing |
| [Editable lesson JSON](../../www/learn/course/modules/) · [SVG diagram source](../../www/learn/visuals.mjs) | The academy's authored lesson content and native teaching diagrams |
