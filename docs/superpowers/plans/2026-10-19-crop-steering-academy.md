# Crop Steering Academy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the five revised pilots and a complete hosted 24-lesson beginner learning platform.

**Architecture:** Static accessible academy alongside the existing dashboard. Lesson JSON is the content source; native slides, deterministic SVGs, narration and captions share the same slide identifiers. Browser-local progress has a versioned schema and explicit import/export. Media comes from a pinned release asset at Pages build time.

**Tech Stack:** HTML, CSS, ES modules, Node test runner, Playwright/axe, Python local Kokoro ONNX, existing FFmpeg skill.

**Spec:** docs/superpowers/specs/2026-10-19-crop-steering-academy.md

## Global Constraints

No further Higgsfield generation after the five-pilot revision. No live HA writes. Preserve unrelated untracked aigrow-ops files. No paid API or subscription changes. Public progress is local to the browser. Course completion is not hardware certification.

## Review Focus

- Alternative Pi/x86 route must not require both lessons.
- Storage denial and corrupt/imported progress must not break access or mark unsafe tasks as verified.
- Numeric practice must distinguish percentage points from relative percentages and delivery from uptake.
- Missing audio/media must provide readable lesson content and a clear retry path.
- New static course assets must survive the dashboard packaging step and preserve existing demo routes.

### Task 1 — Finish revised five-pilot media

- [x] Confirm all 36 completed narration files, retain failed/replacement provenance.
- [x] Assemble and verify 5 MP4s, captions, chapters, offline player, scripts and delivery ZIP.

### Task 2 — Author remaining lesson modules

**Files:** www/learn/course/modules/foundations.json, setup.json, operations.json.
**Interface:** lesson JSON from the spec. Independent authors own separate module files.

- [x] Write full scripts/slides/practice/quiz feedback for A4–A6 and B2–B4.
- [x] Write C2a/C2b/C3–C7 using current official HA documentation and repository behavior.
- [x] Write D1–D6 against current routes and local user guide.
- [x] Validate content structure, unique IDs, answer keys, source links and mathematical examples.

### Task 3 — Build academy and meaningful tests

**Files:** www/learn/index.html, styles.css, app.mjs, state.mjs, visuals.mjs, practice.mjs; tests/academy.test.mjs.

- [x] Pin failing tests for route selection, progress validation, calculator math and immutable recorded graph data.
- [x] Implement navigation, slide/audio player, transcripts/captions, quiz feedback, practice, glossary, progress/review and import/export.
- [x] Run unit tests and browser keyboard/mobile/axe checks.

### Task 4 — Produce and bind media

- [x] Preflight local Kokoro speech, retain exact voice/rate and source script.
- [x] Generate all 19 lessons as per-slide audio plus timed captions; preserve originals under C:/Content.
- [x] Generate one coherent teaching image with built-in image_gen; keep measurement diagrams deterministic.
- [x] Build media manifest and compact publishable asset bundle; verify every lesson's binding.

### Task 5 — Publish and verify

**Files:** .github/workflows/pages.yml, README.md; course documentation and release media.

- [x] Integrate academy into Pages build and link from repository/documentation.
- [x] Build and test existing frontend; inspect whole change and resolve material findings.
- [ ] Commit only owned files, push authorized main, publish versioned media and deploy Pages.
- [ ] Verify public course, all lesson data/media, captions, mobile screenshots and progress behavior.

Ruling: User explicitly authorized autonomous implementation and hosting; no additional plan-approval stop is required. Choose reversible static-site defaults and report actual limitations.

Ruling: Microsoft speech preflight failed with a service 403. Use locally generated Kokoro af_heart instead; no provider credentials, cloud speech dependency, or generation fees. Retain the first failure record and measure local output before the batch.

Local verification: 9 knowledge/practice/catalogue tests pass; 17 media-installer tests pass with one Windows directory-symlink test skipped. ZIP symlink rejection passes. Frontend production build, repository Ruff, Black (122 files) and tracked YAML lint pass. Real-data Edge checks cover all 24 lessons, critical-answer blocking/retry, resume/import/export/reset, storage denial, keyboard focus and 320–1440px layouts. Six axe scans report no tested A/AA violations. These automated checks are not a complete accessibility certification or human listening review.

Media acceptance: 126 new tracks, 74.52 minutes, 1,455 non-overlapping timed caption cues, all source words retained. All 153 slide bindings match current narration. Local install verifies 263 archive members; all 131 playable items decode and advance in Edge. A transient playback failure during changing local media was investigated with a fresh-context reproduction, unchanged matching file/HTTP hashes and a complete successful stable-bundle rerun. Clean staged-source snapshot passes both line-ending checks; the existing Windows working tree fails that broad check because of pre-existing CRLF files and local artifacts. The targeted installer/container/promotion checks otherwise pass (83 passed, one skip, 11 subtests).
