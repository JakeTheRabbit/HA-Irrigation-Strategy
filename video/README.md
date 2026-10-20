# Academy lesson videos (R5)

Remotion renders every lesson video from the existing narration audio. Each slide is a sequence of animated **beats** cued to the exact spoken word. HyperFrames renders the 4-second lesson openers.

- Scene library: `src/scenes/*.tsx`. `CATALOG.md` is generated from each scene's `doc`.
- Lesson scripts: `scenes/<LessonID>.json`. Write them by following `SCENE-GUIDE.md`.
- Openers: `hyperframes/opener/index.html`, with one variables file per lesson in `hyperframes/vars/`.

Narration WAVs and word timings come from the R4 production folder (`--production`, default `C:/Content/Crop Steering from Zero/2026-10-20-course-r4`). They are not stored in Git.

## Rebuild

Use bun or pnpm. Run from `video/`:

```sh
bun install
node scripts/gen-registry.mjs                  # after adding or changing a scene
node scripts/prepare.mjs                       # audio, word timing, cue resolution → public/data
node scripts/stills.mjs A4 3491                # contact sheet per beat for review
node scripts/render.mjs --out <dir>/lessons    # 1080p30 lessons + .vtt + .chapters.json
```

Render the openers in `hyperframes/opener`, once per lesson:

```sh
bunx hyperframes@0.8.181 render . -o ../../public/clips/openers/<ID>.mp4 --quality delivery --variables-file ../vars/<ID>.json
```

Publish (Pages limits the site to 1 GB, so web copies use CRF 30):

```sh
# re-encode each lesson for the web into <dir>/lessons-web (ffmpeg -crf 30 -tune animation, AAC 96k mono)
python video/scripts/assemble.py --render <dir>/lessons-web --production <dir>
python scripts/package_course_videos.py --production <dir> --archive <zip>
python video/scripts/youtube.py --render <dir>/lessons --output <youtube dir>   # lossless 1080p YouTube cut
```

Port 3000 is taken on this machine, so the scripts use ports 3471 and up.

Licensing: Remotion is free for individuals and companies of up to 3 people. Larger companies need a Remotion company licence. HyperFrames is Apache-2.0.
