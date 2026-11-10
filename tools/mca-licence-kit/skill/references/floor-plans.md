# Floor plans and site layout

`scripts/floorplan.py` reads the `layout:` section of `application_data.yaml` and writes:

- `fig1_site_plan.svg` / `.pdf` - the licensed area, every structure, fence, gates, cameras,
  alarm devices, north arrow, 10 m scale bar, legend and title block. A4 landscape.
- `fig2_unit_<use>.svg` / `.pdf` - one plan for each building type: entry sequence (outer
  door, vestibule, inner door), racks, aisle, cameras, motion detector, siren, filter and
  exhaust. A4 landscape.

The intake app writes the same structure in `intake.json` (`layout`), so a site drawn on the
phone becomes the plan with no re-typing.

## Layout data

```yaml
layout:
  north_deg: 0              # direction of true north, clockwise from the top of the page
  site: {w: 40, d: 30}      # licensed area in metres (west-east, north-south), origin top-left
  boundary: []              # optional polygon [[x,y], ...] if the licensed area is not a rectangle
  excluded: []              # optional polygons drawn hatched grey (not licensed)
  items:
    - {kind: building, label: C1, use: Flowering, x: 2, y: 2, l: 12.19, w: 2.44, rot: 0, doors: west end}
    - {kind: gate, label: G1, x: 18, y: 0, l: 4, rot: 0, note: "PIN + fob, electric lock"}
    - {kind: camera, label: CAM1, x: 20, y: 1, dir: 90}
    - {kind: pir, label: PIR, x: 3, y: 3}
    - {kind: siren, label: SIREN, x: 6, y: 2}
  fence: {height_m: 1.8, type: "climb-resistant mesh"}
```

`rot: 90` turns an item 90 degrees. Units are metres. Camera `dir` is degrees: 0 = east,
90 = south.

## Drawing rules

- Red solid outline = licensed area. Grey hatch = excluded (not licensed). Say so in the legend.
- Label every structure, inside or outside the licensed area, with its use. Say "holds no
  cannabis" for sheds and offices.
- Show every vehicle crossing and gate. Mark closed gates "locked shut, not used".
- Show the camera field of view. Number the cameras to match the security plan schedule.
- Give internal dimensions and the total indoor cultivation area (grow rooms only).
- Put "Indicative - not to construction scale" when positions come from a phone sketch.
- Check the plan on site with the customer before it goes in the package.
