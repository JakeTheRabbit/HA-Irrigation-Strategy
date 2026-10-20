# Crop Steering Academy: R4 rebuild record

**Edition:** `2026-10-20-r4`. **Status:** built and verified locally; media release published as the [course-media-2026.10.20-r4 prerelease](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases/tag/course-media-2026.10.20-r4) (asset SHA-256 and size match the pin).

## What changed

**Lessons were rewritten for a true beginner.** All 24 lessons (153 slides) follow the [R4 writing guide](R4-WRITING-GUIDE.md). Nothing is used before it is explained, and a term ledger assigns every term to the one lesson that introduces it. Operators skip C2–C7, so the D lessons re-explain any setup term they use. Each slide follows the same order: link to what you know, explain, name, point at the picture, worked numbers, why it matters, bridge to the next slide. Each slide carries at most one caveat, phrased as an instruction. Narration roughly doubled, from about 10,500 to about 24,000 words.

**Questions are now part of the lesson.** Every slide has a `check` question that applies its one idea to a new case, which makes 153 quick checks. The graded end quiz is unchanged in role: pass with 80% and every safety-critical answer correct.

**The lesson page is one screen.** `www/learn/lesson.mjs` was rebuilt as a stepper: introduction, each section, practice, one question per screen, result. The page never scrolls on a phone or desktop; only the side panel scrolls when its content is long. On each section step the video plays only that section, then pauses at its end. Continue unlocks when the check is answered correctly, or after two wrong tries, when the answer is revealed. The site header is hidden in lesson mode. A menu drawer holds the step list, lesson navigation, transcript, print and sources.

**Corrections made against current docs:**
- Home Assistant install facts: the `homeassistant.local` address, the Imager path, drives that use only 4K sectors, and the size of the Ubuntu USB stick.
- App screen labels now match the app: "Rescue floor", "Arm plan", "Disarm plan", "Apply & verify" and "AI assistant", which replaces "Crop AI".
- One word per idea: "dripper" throughout, and "one owner per output" for the outside switching system.

## Media

| Item | R4 |
| --- | ---: |
| Lesson videos | 24, 854 × 480, H.264 24 fps, captioned |
| Longer parts | 5 |
| Paragraph-matched cards (A1, A2, A3, B1, C1) | 108, re-rendered with 0 overflowing labels |
| Other lesson scenes | 126, re-rendered with 0 overflowing labels |
| Total lesson duration | 10,383.333 s (about 173 min; R3 was 85.7 min) |
| Total group duration | 12,254.667 s |
| Archive | `crop-steering-academy-media-2026.10.20-r4.zip`, 662,601,881 bytes, SHA-256 `d8329c99f6c8e9ed9fd0f661cb5e7b22e8c354781555028de2bbe081cd04d7a3` |

Narration uses Kokoro `af_heart` at speed 0.82, generated locally. Pronunciation rules were added for lesson IDs ("C2a" is read as "C two A"), TEROS, METER, HACS and NUC. Production masters are in `C:\Content\Crop Steering from Zero\2026-10-20-course-r4`.

## Verification (local, Vite preview on :8794)

| Check | Result |
| --- | --- |
| `build_course.py --verify-media` | 24 lessons, 5 groups, 153 bindings, 59 files verified |
| `build_course_videos.py --validate-only` | 24 lessons INPUTS READY |
| Python academy suites | 68 run, OK, 1 skipped |
| `node --test tests/academy.test.mjs` | 9/9 pass |
| `academy-navigation.browser.mjs` | PASS: lesson navigation, route order, section seeking, auto-pause, resume |
| `academy.browser.mjs` | PASS: all 24 lessons and sources, safety-critical quiz gate, resume, export/import, no overflow at 320/360/768/1440 px, axe clean on 7 routes, storage denied |
| `academy-video.browser.mjs` | PASS: captions below the picture, toggle |
| `academy-media.browser.mjs` with `HASH_MEDIA=1` | PASS: all 29 videos play, seek and hash-match; caption words equal the current scripts |
| `academy-scene-sync.browser.mjs` | PASS: all 29 videos match their scene images, including the threshold animation |
| Human listening review | Not performed |
| Learner outcome trial | Not conducted |

## Still to do

1. Merge and deploy the site, then repeat `academy-media.browser.mjs` against the public URL.
2. Human listening review of the R4 narration.
