# Crop Steering Academy: R3 rebuild record

**Edition:** `2026-10-19-r3`. **Status:** published; local and public media checks passed.

The [academy guide](../../ACADEMY.md), [course plan](../../training/crop-steering-from-zero/COURSE-PLAN.md) and [supporting-pack guide](../../training/crop-steering-from-zero/README.md) describe the current route. [Original delivery](DELIVERY-2026-10-19.md), [R2 pilot repair](PILOT-REPAIR-2026-10-19.md), [pilot scripts](PILOT-SCRIPTS.md) and the original storyboard remain historical records. Their narration, voice references, media counts and release status do not override R3 sources.

## What changed

The course now starts with familiar objects and explains each idea before relying on its technical name: water and air in a pot, equal-volume boxes for VWC, a draining sponge for capacity, a balance for dryback and labelled water locations for EC. It separates physical measurements, software references, proposals and accepted settings. The script review also checks that demo instructions use the actual Room A/Room B labels, while fixed teaching scenarios are explicitly fictional.

All 24 lessons have captioned 480p videos, plus five longer chaptered parts. The material remains available as slides, transcript, exercises and knowledge checks. The delivery checks below cover installation, seeking and public availability.

The shared setup sequence is now:

| Lesson | Purpose |
| --- | --- |
| C2a OR C2b | Give Home Assistant one supported host; protect storage before an installation write |
| C3 | Explain software addresses, install both matching Crop Steering parts and protect recovery access |
| C4 | Map a named zone, check units/sizing/time and distinguish saving from Controller acceptance |
| C5 | Verify physical protection, documented interfaces, shutdown and one owner per output |
| C6 | Use an approved equipment catch test with Watering OFF; supervise an enabled Controller cycle only after readiness passes |
| C7 | Observe and document Growlink, then hand over one output at a time with commissioning and rollback evidence |

C7 can be a paper exercise for a learner who has no Growlink installation. It does not require buying another system, assume an automatic importer or permit two controllers to command one output.

## Video and image scope

| Item | Verified R3 count |
| --- | ---: |
| Lessons | 24 |
| Authored slides | 153 |
| Individual captioned lesson videos | 24 |
| Longer chaptered parts | 5 |
| Paragraph-matched visual cards in A1, A2, A3, B1 and C1 | 108 |
| Scenes in the other 19 lessons | 126 |
| AI-generated physical teaching images | 13 |
| Captures of the isolated application demo | 15 |

The image counts describe source assets, not unique video scenes. Native diagrams supply exact calculations where needed. AI-generated pictures explain concepts; they are not photographs of an installed system. Demo screenshots show the real application with synthetic data, not a live facility. A picture, event marker or reported output state does not measure delivered water or prove stopping.

The five parts are Foundations (A1–A6), Watering and equipment (B1–B4, C1), Raspberry Pi setup (C2a, C3–C7), Dedicated x86 setup (C2b, C3–C7) and Daily operation (D1–D6). Recommended routes contain 17 operator lessons or 23 builder lessons, with one host alternative. All 24 lessons remain directly available.

## Continuous learning controls

Each lesson has previous/next lesson controls at the top and bottom and a selector for every lesson. Recommended-route order applies where the current lesson belongs to that route. An alternative lesson can still be opened directly. Video sections seek to real timestamps and track the current section as playback advances.

The grouped player has a part selector, direct section list, previous/next section and part controls, a link to the relevant regular lesson, and optional continuation to the next part. Captions appear below the picture. Loading and media failures have readable messages. Watching, seeking, skipping or continuing does not pass a knowledge check.

## Source and media bindings

Edit narration in [lesson modules](../../../www/learn/course/modules/) and compile it with [build_course.py](../../../scripts/build_course.py). The [generated source transcript](../../../www/learn/course/all-lesson-transcripts.txt) is the reading/recording output of those modules. Do not maintain a second current spoken script in the historical pilot document.

Any narration change requires regeneration of the affected speech, captions and matching video. Individual video metadata in `course/video-index.json` must identify all 24 lessons, match the SHA-256 of their ordered narration joined with blank lines, and list every slide chapter in order starting at zero. `course/video-groups.json` defines the five ordered parts, their lessons, routes and chapter timestamps.

The media manifest inventories delivered files with byte counts and SHA-256 hashes and contains exactly 153 source-text narration bindings. `python scripts/build_course.py --verify-media` checks the installed files, all 24 videos, five groups and exact 17/23/23 route coverage before writing the generated catalogue or transcript. A failed check preserves those outputs. The archive installer additionally checks the pinned release hash and archive contents.

These checks establish file and source consistency. Decoder playback, readable frames, caption alignment and useful chapter seeking still need their own checks against the final bundle.

## Verification and release status

| Check | Recorded status |
| --- | --- |
| Current narration, quizzes and source bindings | 24 lessons, 153 slides, 234 source/audio/image bindings validated |
| Python media/catalogue/production regression checks | 67 passed; one Windows symlink test skipped; 21 subtests passed |
| Knowledge, calculation, route and progress logic | Nine Node tests passed |
| Final frame bindings and image review | 108 paragraph frames and 126 other scenes checked; all 126 cached captures reused without changes after final catalogue compilation |
| Complete lesson/group encodes | 24 lessons and five parts; 854 × 480, H.264, 24 fps, mono AAC at 48 kHz; exact frame counts validated |
| Format and audio delivery checks | 29 reports, zero failed rows; expected warnings for requested 480p and external caption tracks |
| Complete bundle installation and strict media verification | 59 inventoried files and 153 narration bindings installed and verified; 60 ZIP members including the manifest |
| Actual decoded pictures | 502 comparisons across all 29 videos passed; maximum mean absolute RGB error 4.015/255; B1's before/after threshold movement passed its changed-pixel check |
| Final browser media checks | All 29 videos played and sought successfully; exact caption words matched current scripts; actual served dashboard hash matched released 3.16.0 |
| Navigation and accessibility | Direct lesson/section navigation, grouped player, fallback and progress preservation passed; seven routes passed axe scans and 320/360/768/1440 px overflow checks; all 24 lessons also checked at 320 px |
| README screenshots | Refreshed from the final local edition; A3 shows the new drainage illustration and real section controls |
| Public deployment and hash readback | Pages run 39177337531 succeeded; all 29 public videos decoded, sought and downloaded with matching byte counts/SHA-256; caption words matched current scripts; published dashboard bytes remained the stable build |
| Human listening review | Not performed |
| Learner outcome trial | Not conducted |

The individual lessons total **5,142.833 seconds (85 min 42.833 sec)**, including both alternative host lessons. The operator route is about 61 minutes; either builder route is about 82 minutes. The five video parts total 6,224.083 seconds because the alternative setup parts repeat the shared setup lessons.

| Part | Measured duration | Frames |
| --- | ---: | ---: |
| Foundations | 20:02.000 | 28,848 |
| Watering and equipment | 20:57.917 | 30,190 |
| Raspberry Pi setup | 21:08.000 | 30,432 |
| Dedicated x86 setup | 21:31.875 | 31,005 |
| Daily operation | 20:04.292 | 28,903 |

The archive is `crop-steering-academy-media-2026.10.19-r3.zip`, 332,394,228 bytes. SHA-256: `98217d36f466b3c57ba9cd82e065569132166633996e615ea36d6b056ed4f32d`. Its pin is in `www/learn/course/media-release.json`; the public media release is separate from application releases.

The [published R3 course](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/?v=20261019r3) is served from website commit `9ce066b` through [Pages run 39177337531](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/actions/runs/39177337531). The [R3 media release](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases/tag/course-media-2026.10.19-r3) is a course prerelease and does not replace the latest stable irrigation application. Public acceptance used `BASE_URL` for the HTTPS academy, `HASH_MEDIA=1` and `tests/academy-media.browser.mjs`; every video was downloaded and hashed. The actual published dashboard SHA-256 was `1914a9180d3051636f560d00074de48213df134edb34b5ed6e806161884d220c`.

Source changes, Athena acknowledgements and screenshots are in [PR 190 into testing](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/pull/190), awaiting the repository's required human review. Production `main` remains `9f19e594ef70e21b8eb9dee760798289226393dc`, application release `v3.16.0`; no Home Assistant configuration was written.

Local checks used `build_course.py --verify-media`, both capture renderers' source checks, `build_course_videos.py --validate-only`, the academy Node/Python suites and the navigation, caption, full-course, media and scene-sync browser checks. The Windows installer initially encountered a preview-server directory lock; stopping only the owned preview server allowed atomic installation, after which the server and browser checks were restarted. No installer validation was bypassed.


Athena’s handbook and irrigation resources informed the project and are credited in relevant lessons and [references and acknowledgements](../../REFERENCES.md). The project’s examples and application workflows remain distinct from Athena’s recommendations. Attribution does not imply endorsement.

This website/media rebuild does not release irrigation-controller software or verify physical commissioning. Real hardware still requires the installation’s approved procedure and competent local evidence.
