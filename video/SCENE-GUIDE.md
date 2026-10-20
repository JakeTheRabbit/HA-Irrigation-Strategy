# Scripting lesson visuals

Each lesson video is the existing narration audio plus a sequence of animated **beats**. A beat is one scene from the library (see `CATALOG.md` and each `src/scenes/<Name>.tsx` `example`). You write `video/scenes/<LessonID>.json`:

```json
{
  "slides": {
    "A4-1": [
      { "type": "Analogy", "props": { "left": { "icon": "bank", "label": "Balance falls $60 → $45" }, "right": { "icon": "pot", "label": "Water content falls" } } },
      { "type": "Define", "cue": "growers call that fall", "steps": ["fall between two", "for example"], "props": { "term": "Dryback", "meaning": "How much the water content falls between two readings." } },
      { "type": "DrybackBars", "cue": "sixty percent at", "steps": ["sixty percent", "forty-five percent", "fifteen percentage points", "a quarter of"], "props": { "start": 60, "end": 45 } }
    ]
  }
}
```

## Rules

1. **Cover the whole narration.** The first beat of each slide has no `cue` and starts at 0. Every later beat starts when its `cue` is spoken.
2. **Change the picture often.** Start a new beat every 8–15 seconds of speech, so a slide of about 60 seconds has 4–7 beats. Every paragraph (pilot lessons separate paragraphs with a blank line) gets at least one beat that shows what that paragraph talks about.
3. **Show, don't print.** At least 75% of beats must be illustrated scenes, not Title, Points or Calc. Use Calc only for a real worked calculation, and Points only for a genuine list. Never put the narration on screen as sentences.
4. **Explain every new word.** The first time a term is defined in the narration (the course's term ledger is in `docs/training/crop-steering-from-zero/R4-WRITING-GUIDE.md`), give it a `Define` beat cued where the narrator starts explaining it. Keep the `meaning` to 12 words or fewer.
5. **Use the narrator's exact words for cues and steps.**
   - A `cue` is 3–6 consecutive words copied exactly from the narration, spelled as spoken ("sixty percent", "P three"), and unique after the previous cue.
   - `steps` are phrases spoken inside that beat, in order. They trigger reveals inside the scene, so each element appears as it is mentioned.
   - Check each scene's `doc` for what its steps mean.
6. **Keep numbers consistent.** Every number on screen must match the narration exactly.
7. **Use more examples.** Where the narration gives one example, a scene can show it concretely: real values on a graph, real cups filling, the real screen region. Use ScreenTour on the demo screenshots for every app lesson (C3, C4, D1–D6). Focus boxes are in image pixels; the image sizes are listed in the doc and the screenshot manifest.
8. **Keep labels short:** 32 characters or fewer, and use the course's own words.

## Check your work

From `video/`:

```sh
node scripts/prepare.mjs <ID>          # must print no "cue not spoken" or "step not spoken" lines
node scripts/stills.mjs <ID> <port>    # renders a contact sheet: one frame per beat, out/stills/<ID>/
```

Open the contact sheet PNGs and fix anything that is unreadable, clipped, empty or does not match what is being said.
