# Illustrated pilot storyboard

[Open the visual storyboard](index.html) · [Download the 28-page PDF](storyboard.pdf) · [Markdown edition](STORYBOARD.md)

**27 scenes, each with its own image, across the five complete pilot scripts:**

| Pilot | Subject | Scenes | Proposed runtime |
| --- | --- | --- | --- |
| A1 | Water, roots and air | 5 | 4:11 |
| A2 | VWC explained | 5 | 4:09 |
| A3 | Capacity versus saturation | 5 | 4:28 |
| B1 | Combined VWC/EC graph | 6 | 4:38 |
| C1 | Equipment and first-system layout | 6 | 5:11 |

Each panel contains the image, proposed time, camera framing, edit/action notes, on-screen wording, accuracy/staging notes, and its complete section of the existing narration. Learner pauses are retained. Timing estimates use a 130-word/minute read plus demonstration/learner holds; they are not measured performances.

Open `index.html` in a browser. Use **Toggle contact sheet** for the visual overview, or scroll through the full scene cards. **Print / save PDF** prints one scene per landscape page. The supplied PDF already contains the cover and all 27 scenes. Keep the `assets` folder beside the HTML file if moving it; the PDF is independently portable.

## Images

Six built-in image_gen illustrations show planned filming setups. Twenty-one original SVG diagrams keep quantities, axes, reference styling and equipment paths precise. The images are production illustrations, not photographs/evidence of an installed or commissioned system. Equipment shapes are generic; they do not endorse exact models, wiring, protection ratings or probe compatibility.

Numeric graphs are labelled synthetic teaching examples. Observed VWC uses circle markers; observed EC uses diamond markers; references use separate dashes. Day/night reference lines are continuous, and a changed draft floor does not redraw observed values. Reference curves are not validated crop-response forecasts.

All final images are stored in [assets](assets/). The [prompt manifest](image-prompts.json) records the built-in generation prompts, including the corrected dry-control staging in C1-04. No paid CLI/API fallback was used.

## Contact sheets

- [A1: Water, roots and air](review/A1-contact-sheet.png)
- [A2: VWC](review/A2-contact-sheet.png)
- [A3: Capacity](review/A3-contact-sheet.png)
- [B1: Combined graph](review/B1-contact-sheet.png)
- [C1: Equipment](review/C1-contact-sheet.png)

## Source and rebuild

[scenes.json](scenes.json) contains the structured shot list and full assigned narration. [build_storyboard.py](build_storyboard.py) checks that every paragraph in the five source scripts appears exactly once, draws SVGs, and generates HTML/Markdown. Existing PNGs are reused unchanged. Optionally set `STORYBOARD_GENERATED_IMAGE_DIR` to import the original generated PNG filenames on the first build.

```powershell
python docs/training/crop-steering-from-zero/storyboard/build_storyboard.py
node docs/training/crop-steering-from-zero/storyboard/render_storyboard.mjs
```

The renderer uses the project's existing Playwright dependency, checks all 27 images, tests the contact-sheet button and mobile overflow, exports the PDF, and captures the contact sheets. It can use `STORYBOARD_CHROMIUM` for an installed browser executable. It makes no network or Home Assistant calls. No new application dependencies were added.

Scope: this covers every scene in A1, A2, A3, B1 and C1. The remaining 19 lesson slots in the course catalogue still have briefs rather than complete visual storyboards. No videos have been recorded, uploaded or published by this work.
