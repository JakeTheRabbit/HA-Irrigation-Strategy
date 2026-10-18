# Pilot video repair — 19 October 2026

[Watch lesson one](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/#/lesson/A1) · [Revised media bundle](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases/tag/course-media-2026.10.19-r2) · [Original delivery record](DELIVERY-2026-10-19.md)

The original edit held one picture for the final 84.5 seconds of lesson one while its narration covered several different concepts. Small labels also lost clarity at 480p. Successful playback had not established picture-to-explanation correspondence. The learner rejected the saved Scarjo voice.

All five pilot lessons, A1, A2, A3, B1 and C1, now use local Kokoro `af_heart` narration at speed 0.82, consistent with the other 19 lessons. They contain 108 visual cards, each bound to one exact narration paragraph. The original narration wording is retained. Large, native 854×480 diagrams replace the earlier illustrations and unrelated motion inserts. No new Higgsfield or cloud speech generation was used.

## Timing and verification

Each picture and voice take shares a source paragraph ID. The build rejects missing cards, duplicate IDs, changed source wording and invalid frame durations. PCM narration is padded to whole 24fps frames and concatenated once. Picture-only clips follow those frame boundaries; joining separate AAC tracks is avoided because decoder padding can extend visual holds.

Lesson A1 has 20 cards and 4,536 video frames: 189 seconds of pictures, with a 189.1-second container duration including its audio tail. All 20 finished-video cards, eight samples around early/middle/late boundaries and three samples in the question hold were inspected. No picture mismatch or sampled cumulative drift was found. The choice screen remains until the answer starts at 86.75 seconds. The question pauses in A1, A2 and B1 last eight seconds.

The B1 draft-threshold demonstration holds 35%, moves to 39% during the actual spoken change clause, and holds 39% during the explanation. The saved 35% threshold and synthetic observed traces remain fixed. Movement occurs at 9.958–13.958 seconds within that narration paragraph; its spoken clause occupies 9.94–13.94 seconds.

All 108 source cards were checked for complete, exact paragraph coverage. Native frame checks found no text outside the reserved content bounds. The A1 cards and representative cards from the other pilots received visual inspection. Source captions retain the authored words; ASR supplies timing anchors rather than replacement wording. Media checks enforce the selected 480p delivery, 24fps picture, AAC mono at 48kHz, captions and speech loudness near −16 LUFS. The expected YouTube recommendation warning for resolution is retained because this edition deliberately uses 480p.

**Human listening review has not been performed.** These checks establish source binding, timing, readable graphics and file behaviour. They do not establish that every learner likes the replacement voice or prove learning outcomes. Synthetic diagrams do not prove hardware behaviour.

The web player displays captions below the picture so that paused controls and captions do not cover diagram labels. A browser regression check verifies the spoken cue, caption position and show/hide control.

## Revised publication bundle

The revision contains 264 declared media files and 153 source bindings. Its ZIP is 101,651,238 bytes with SHA-256 `8481c52fefb64cd50785d23a5da45aa7b6856279eb4e741c7e94ff78381d93fb`. The revised bundle was installed locally through the checksum-verifying installer. All 126 narration tracks and their captions for the other 19 lessons retain their previous hashes.

The five pilot exports total 20 minutes 20.7 seconds. All five passed their media checks, with only the expected 480p resolution recommendation warning. Nine knowledge/practice tests, five timing regression tests and 17 media-installer tests passed; one Windows directory-symlink case was skipped.

## Rebuild the pilot media

Large originals and model weights stay outside Git. Preserve the previous media bundle and generate into a new production directory. Optional production dependencies are Kokoro ONNX, ONNX Runtime, SoundFile, NumPy, faster-whisper, Playwright and the local ffmpeg-skill scripts. Learners need none of them.

```powershell
python scripts/build_pilot_audio.py --models <local-model-directory> --output <production-directory>/narration
node scripts/render_pilot_frames.mjs --help
node scripts/render_pilot_frames.mjs --output <production-directory> --motion-alignment <actual-word-anchors.json>
python scripts/build_pilot_media.py --production <production-directory> --skill <ffmpeg-skill-scripts-directory>
python -m unittest discover -s tests -p test_pilot_timing.py
```

The animation reads word anchors from the new take; do not reuse another voice's timing. The renderer also supports read-only `--check-existing`. The media builder can partition independent work with `--lessons A1 A2`. Review actual finished frames at the paragraph boundaries before replacing the versioned public bundle. Update its checksum pin, compile the catalogue, verify every media binding and deploy through the website publication workflow. This publication does not release irrigation software or change Home Assistant.
