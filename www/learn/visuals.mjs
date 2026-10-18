// Native teaching diagrams. All numbers describe examples, never live HA data.
const INK = "#172c3c";
const MUTED = "#42596a";
const BLUE = "#126396";
const PINK = "#a52a62";
const GREEN = "#216447";
const AMBER = "#805800";
const escape = (value) =>
  String(value ?? "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
const finite = (value, fallback) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const number = (value) => Number(value.toFixed(2)).toString();

function lines(value, max = 29) {
  const words = String(value ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  const result = [];
  for (const original of words) {
    const pieces = original.match(new RegExp(`.{1,${max}}`, "gu")) || [""];
    for (const word of pieces) {
      if (result.length && result.at(-1).length + word.length + 1 <= max)
        result[result.length - 1] += ` ${word}`;
      else result.push(word);
    }
  }
  return result;
}

function text(
  x,
  y,
  value,
  {
    size = 23,
    color = INK,
    anchor = "start",
    weight = 500,
    width = 32,
    gap = 28,
  } = {},
) {
  return `<text x="${x}" y="${y}" fill="${color}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}">${lines(
    value,
    width,
  )
    .map(
      (line, index) =>
        `<tspan x="${x}" dy="${index ? gap : 0}">${escape(line)}</tspan>`,
    )
    .join("")}</text>`;
}
const rect = (
  x,
  y,
  w,
  h,
  fill = "#edf3f5",
  stroke = "#b8c8d1",
  radius = 14,
  extra = "",
) =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="2" ${extra}/>`;
const line = (x1, y1, x2, y2, color = MUTED, extra = "") =>
  `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="3" ${extra}/>`;
const circle = (x, y, r, fill, stroke = INK) =>
  `<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`;
function arrow(x1, y1, x2, y2, color = MUTED) {
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const end = (offset) =>
    `${x2 - Math.cos(angle + offset) * 13},${y2 - Math.sin(angle + offset) * 13}`;
  return (
    line(x1, y1, x2, y2, color) +
    `<polyline points="${end(-0.5)} ${x2},${y2} ${end(0.5)}" fill="none" stroke="${color}" stroke-width="3"/>`
  );
}
const note = (value, y = 416) =>
  text(48, y, value, { size: 21, width: 77, color: MUTED, gap: 26 });
function card(x, y, w, h, heading, detail, color = INK) {
  const headingWidth = Math.floor(w / 14);
  const headingRows = lines(heading, headingWidth).length;
  return (
    rect(x, y, w, h) +
    text(x + 18, y + 36, heading, {
      size: 24,
      weight: 700,
      color,
      width: headingWidth,
    }) +
    text(x + 18, y + 79 + (headingRows - 1) * 28, detail, {
      size: 21,
      width: Math.floor(w / 12),
      gap: 27,
    })
  );
}

const DEFAULTS = {
  "root-zone": [
    "Inside the root zone",
    "A container contains solids, water and air. A moisture probe samples a small location; it does not establish whole-zone health.",
  ],
  fraction: [
    "Six volumes out of ten",
    "Illustration: six of ten equal total substrate volumes contain water. VWC is not percent plant-available water; the remainder includes solids and air.",
  ],
  sponge: [
    "The sponge, the pot and the Post-it",
    "A conceptual sponge analogy: water fills spaces at saturation; after excess water drains, water remains and air returns. An app reference describes a checked condition and cannot add water. The 600 mL in a 1 L total substrate sample calculation is an example, not a target.",
  ],
  capacity: [
    "Three different ideas",
    "Saturation, drained container capacity and a configured program reference are separate ideas. A program setting is not a physical capacity measurement.",
  ],
  dryback: [
    "Two ways to describe the same fall",
    "Example: VWC falls from 60% to 45%. That is 15 percentage points and 25% relative dryback from the 60% starting value.",
  ],
  "ec-path": [
    "Identify the EC measurement",
    "Feed EC, bulk substrate EC, pore-water EC and runoff or extract EC describe different measurement locations or methods. They are not interchangeable nutrient analyses.",
  ],
  "sensor-check": [
    "Can this reading be trusted?",
    "Check exact identity and location, quantity and units, data age, appropriate placement and contact, and a suitable independent check. A fresh number can still be the wrong measurement.",
  ],
  "combined-graph": [
    "Read each line against its own axis",
    "Synthetic teaching graph. Blue VWC uses the left percent axis; pink EC uses the right mS/cm axis. Night, irrigation events, actual traces and a reference have separate labels and styles. Changing a reference cannot rewrite measured history.",
  ],
  phases: [
    "A watering day in four phases",
    "This program labels morning dryback P0, ramp-up P1, maintenance P2 and overnight P3. Actual transitions and shots depend on configured conditions; this diagram gives no universal times.",
  ],
  steering: [
    "Between configured endpoints",
    "A steering position interpolates configured vegetative and generative endpoints. These example numbers are arbitrary settings, not crop recommendations or a guarantee of plant response. Identical endpoints yield no change.",
  ],
  flow: [
    "Calculate delivered water",
    "Example: emitter flow multiplied by drippers per plant, runtime in hours and plant count gives estimated zone delivery. Delivered water is not plant uptake, and runtime-derived totals are estimates unless independently measured.",
  ],
  equipment: [
    "Functions before product names",
    "A useful system needs a supported host and network, an identified measurement path, a suitable controlled water path and independent physical protections. A pump is only needed when the actual supply requires one.",
  ],
  host: [
    "Choose one supported host route",
    "Raspberry Pi HAOS and dedicated x86-64 HAOS are alternative routes. Verify storage identity and backup before image writing, which erases selected storage. Power, storage, network and recovery access need checking.",
  ],
  entities: [
    "One device can have several entities",
    "A device can expose multiple named readings or controls. Record exact entity IDs, quantity, units, data age and physical location; friendly names alone do not establish identity.",
  ],
  "water-path": [
    "Trace the actual water path",
    "A suitable pressurised supply and a reservoir with pump are alternative water paths. Actual protection and component order must follow the installation design and manufacturer instructions.",
  ],
  controls: [
    "Software control and physical isolation",
    "Watering OFF blocks Controller ordinary, rescue and test shots. It does not isolate electrical power or independent equipment controls. Use the installation physical shutdown procedure for an emergency or hardware work.",
  ],
  mapping: [
    "From real equipment to accepted mapping",
    "Verify room and zone, exact entity identity, units, freshness and sizing. Review and save, then separately verify Controller acknowledgement of the revision. Saved does not mean acknowledged.",
  ],
  commissioning: [
    "Two supervised commissioning stages",
    "First perform an installer-approved bounded equipment catch test with Controller Watering OFF. Only after all readiness checks pass may a supervised enabled Controller cycle proceed. Prove intended outlet, other zones dry, actual stopping and no unwanted siphon.",
  ],
  navigation: [
    "Keep room scope in view",
    "Find the room and zone before an action. Overview explains current state, Equipment holds mappings, Irrigation holds current targets and calendar, and History holds recorded evidence. Software actions require reviewed scope and readback.",
  ],
  target: [
    "Draft, saved and actual are different",
    "A draft target is a proposal. Review and apply it, then verify readback. A planned reference can change while actual recorded measurements remain unchanged. Plan-owned targets may require the Calendar workflow.",
  ],
  calendar: [
    "A stored plan is not active watering",
    "A plan is drafted, saved and armed before it becomes eligible at the next local lights-on. Arming does not enable Watering. Disarming requests handover at the next lights-on; it is not emergency isolation.",
  ],
  comparison: [
    "Compare like with like",
    "Match room, zone, dates, units, age, coverage and evidence type before comparing. A current reference does not reconstruct past targets, and an estimated delivery total is not measured uptake.",
  ],
  troubleshooting: [
    "Observe, check evidence, act",
    "Unexpected continuing water requires the agreed physical shutdown. For data or configuration faults, keep affected operation disabled as appropriate, investigate identity, freshness and acknowledgement, and verify the correction. Never bypass a hold or alter a recipe to hide a fault.",
  ],
  "daily-check": [
    "A short evidence-based check",
    "Check data freshness, room phase and next action, physical delivery, tank and feed context, and exceptions. Record a justified change, its evidence and a follow-up time. Unknown is not OFF and an AI suggestion is not verified evidence.",
  ],
};

function process(nodes, { y = 145, height = 174, colors = [] } = {}) {
  const count = nodes.length;
  const gap = 24;
  const width = (864 - gap * (count - 1)) / count;
  return nodes
    .map(([heading, detail], index) => {
      const x = 48 + index * (width + gap);
      return (
        card(x, y, width, height, heading, detail, colors[index] || INK) +
        (index < count - 1
          ? arrow(
              x + width + 3,
              y + height / 2,
              x + width + gap - 3,
              y + height / 2,
            )
          : "")
      );
    })
    .join("");
}

function spongeDiagram(focus, labels) {
  const shape = (x, y, wet) => {
    let result = rect(x, y, 280, 150, "#efd081", "#9d7527", 22);
    [[45,40],[115,29],[190,46],[240,32],[75,104],[155,100],[230,110]].forEach(([a,b],i) => {
      result += `<ellipse cx="${x+a}" cy="${y+b}" rx="18" ry="17" fill="${wet || i%2===0 ? '#81c9ee' : '#fff'}" stroke="${wet || i%2===0 ? BLUE : MUTED}" stroke-width="2"/>`;
    });
    if (wet) [70,145,220].forEach(a => { result += `<path d="M ${x+a} ${y+158} q -10 15 0 22 q 10 -7 0 -22" fill="#81c9ee" stroke="${BLUE}" stroke-width="2"/>`; });
    return result;
  };
  if (focus === "recall") return text(480,185,"?",{size:70,anchor:"middle",weight:700}) + text(480,270,"Reference: 60% → 70%",{size:32,anchor:"middle"}) + text(480,339,"What happens to the water?",{size:30,anchor:"middle",width:45});
  if (focus === "reference") return shape(85,155,false) + text(225,365,"Same physical sponge",{anchor:"middle",size:25}) + rect(538,134,330,170,"#fff1a9","#c5a343",3) + text(703,178,"REFERENCE NOTE",{anchor:"middle",size:24}) + text(703,246,"60% → 70%",{anchor:"middle",size:38,weight:700}) + text(703,365,"Water stays the same",{anchor:"middle",size:25}) + note("Editing the app reference cannot add or remove water.");
  if (focus === "volume") return rect(80,137,300,180,"#eeddbb",INK,10) + text(230,190,"Total substrate sample",{anchor:"middle",size:25,width:25}) + text(230,260,"1 L = 1000 mL",{anchor:"middle",size:29,weight:700}) + text(660,176,"600 mL water",{anchor:"middle",size:30,color:BLUE}) + text(660,237,"600 ÷ 1000 × 100",{anchor:"middle",size:30}) + text(660,300,"= 60% VWC",{anchor:"middle",size:36,color:BLUE,weight:700}) + note("Illustrative calculation. Your own container needs a suitable check.");
  if (focus === "comparison" || focus === "transfer") return shape(80,145,true) + shape(590,145,false) + arrow(395,217,550,217,BLUE) + text(220,369,labels[0] || "Soaked and dripping",{anchor:"middle",size:25,width:29}) + text(730,369,labels[1] || "Wet after drainage",{anchor:"middle",size:25,width:29}) + note("Let excess water drip without squeezing. The sponge still holds water.",453);
  const wet = focus === "wet";
  return shape(90,144,wet) + text(230,375,wet ? "Dripping over the sink" : "Wet after drainage",{anchor:"middle",size:25,width:28}) + text(540,185,labels[0] || (wet ? "Water fills the spaces" : "Water remains"),{size:27,width:25}) + text(540,282,labels[1] || (wet ? "Solid material stays" : "Air returns to some spaces"),{size:27,width:25}) + note("A conceptual analogy; test your own substrate and container.");
}

function render(type, values, labels, quantity, focus) {
  let svg = "";
  // Lesson-specific cue cards avoid injecting unrelated default calculations.
  if (type === "lesson-cues") {
    const cues = labels.slice(0, 4);
    const count = Math.max(1, cues.length);
    const height = (330 - (count - 1) * 15) / count;
    return cues.map((cue, i) => {
      const y = 112 + i * (height + 15);
      return rect(48, y, 864, height, "#eef5f8", "#b8cbd5", 14)
        + circle(81, y + height / 2, 17, "#d2e7f2", BLUE)
        + text(81, y + height / 2 + 7, i + 1, {size: 20, anchor: "middle", color: BLUE, weight: 750})
        + text(118, y + Math.min(39, height / 2 + 8), cue, {size: 25, width: 61, gap: 30});
    }).join("");
  }

  switch (type) {
    case "sponge": return spongeDiagram(focus || "comparison", labels);
    case "root-zone": {
      svg += rect(86, 118, 360, 246, "#e9f2f7", INK, 10);
      for (const [x, y, r] of [
        [120, 154, 21],
        [209, 168, 26],
        [292, 143, 19],
        [390, 185, 30],
        [164, 267, 27],
        [270, 285, 32],
        [382, 318, 24],
      ])
        svg += circle(x, y, r, "#846c55", "#594331");
      for (const [x, y] of [
        [148, 206],
        [251, 219],
        [337, 248],
        [111, 320],
      ])
        svg += circle(x, y, 18, "#fff", "#617b88");
      svg +=
        '<path d="M270 108 C250 174 304 208 252 341 M271 170 L229 199 M279 225 L320 263 M267 278 L221 315" fill="none" stroke="#315e3c" stroke-width="7" stroke-linecap="round"/>';
      svg +=
        circle(520, 152, 12, "#846c55") +
        text(549, 160, "Solids: the substrate");
      svg +=
        circle(520, 216, 12, "#bad9eb") +
        text(549, 224, "Water between solids");
      svg +=
        circle(520, 280, 12, "#fff") + text(549, 288, "Air between solids");
      svg += note(
        "Roots need both water and air. More water is not always better.",
      );
      break;
    }
    case "fraction": {
      const part = finite(values[0], 6),
        total = finite(values[1], 10);
      const ratio = total === 0 ? null : part / total;
      const width = 78,
        x0 = 90;
      // Ten display cells represent the reference amount. Only the drawing is
      // bounded to one reference; the actual fraction is never rounded/clamped.
      for (let i = 0; i < 10; i++) {
        const fill = ratio === null ? 0 : clamp(ratio * 10 - i, 0, 1);
        svg += rect(
          x0 + i * width + 3,
          152,
          width - 6,
          112,
          "#f7f3e9",
          "#806b50",
          4,
        );
        if (fill)
          svg += rect(
            x0 + i * width + 3,
            152,
            (width - 6) * fill,
            112,
            "#bedff1",
            BLUE,
            0,
          );
        if (!quantity && fill === 1)
          svg += text(x0 + i * width + width / 2, 218, "W", {
            anchor: "middle",
            size: 29,
            color: BLUE,
          });
      }
      const result =
        ratio === null
          ? "Division by zero is undefined"
          : `${number(part)} / ${number(total)} = ${number(ratio * 100)}%`;
      svg += text(480, 319, result, {
        anchor: "middle",
        size: 35,
        weight: 700,
        width: 45,
      });
      svg += text(480, 370, quantity || "VWC: water / total substrate volume", {
        anchor: "middle",
        size: 25,
        weight: 700,
        width: 55,
      });
      svg += note(
        quantity
          ? "Part ÷ stated reference amount × 100. Ten cells illustrate one reference."
          : "W = water. The remaining sample includes solids AND air; not available water.",
        430,
      );
      break;
    }
    case "capacity": {
      for (const [i, label, water] of [
        [0, "Saturated", 155],
        [1, "Drained capacity", 104],
        [2, "Program reference", 104],
      ]) {
        const x = 78 + i * 300;
        svg += text(x + 108, 128, label, {
          anchor: "middle",
          size: 25,
          width: 21,
        });
        svg += rect(x + 24, 160, 164, 180, "#fff", INK, 7);
        if (i < 2)
          svg += rect(x + 28, 336 - water, 156, water, "#bedff1", BLUE, 2);
        else
          svg +=
            line(x + 8, 228, x + 207, 228, BLUE, 'stroke-dasharray="12 7"') +
            text(x + 108, 287, "A saved setting", {
              anchor: "middle",
              size: 19,
              width: 17,
            });
        if (i === 1)
          svg +=
            '<path d="M122 351 l-7 13 a9 9 0 1 0 14 0z" transform="translate(300 0)" fill="#126396"/>';
      }
      svg += note(
        "Measured drained condition ≠ saturation ≠ configured reference.",
      );
      break;
    }
    case "dryback": {
      const start = clamp(finite(values[0], 60), 0.01, 100);
      const end = clamp(finite(values[1], 45), 0, start);
      svg +=
        rect(100, 140, 160, 215, "#edf3f5", INK, 5) +
        rect(104, 351 - start * 2, 152, start * 2, "#bedff1", BLUE, 2);
      svg +=
        rect(395, 140, 160, 215, "#edf3f5", INK, 5) +
        rect(399, 351 - end * 2, 152, end * 2, "#bedff1", BLUE, 2);
      svg +=
        text(180, 122, `${number(start)}%`, { anchor: "middle", size: 31 }) +
        text(475, 122, `${number(end)}%`, { anchor: "middle", size: 31 });
      svg += arrow(280, 242, 375, 242, BLUE);
      svg += text(620, 183, `${number(start - end)} percentage points`, {
        size: 25,
        weight: 700,
        width: 22,
      });
      svg += text(
        620,
        273,
        `${number(((start - end) / start) * 100)}% relative dryback`,
        { size: 25, weight: 700, width: 22 },
      );
      svg += note(
        `Subtract: ${number(start)} − ${number(end)}. Relative: (${number(start - end)} ÷ ${number(start)}) × 100.`,
      );
      break;
    }
    case "ec-path": {
      svg += card(
        48,
        148,
        245,
        184,
        "Feed EC",
        "Solution entering the water path",
        BLUE,
      );
      svg += arrow(307, 242, 340, 242);
      svg +=
        rect(355, 122, 290, 242, "#f2eee8", "#806b50") +
        text(500, 163, "Root zone", {
          anchor: "middle",
          size: 27,
          weight: 700,
        });
      svg +=
        text(379, 212, "Bulk EC", { color: PINK, size: 25, weight: 700 }) +
        text(379, 243, "Substrate measurement", { size: 19, width: 24 });
      svg +=
        text(379, 289, "Pore-water EC", {
          color: PINK,
          size: 25,
          weight: 700,
        }) + text(379, 321, "Water within pores", { size: 19 });
      svg +=
        arrow(658, 242, 689, 242) +
        card(
          705,
          148,
          207,
          184,
          "Runoff / extract",
          "Collected sample and its method",
          BLUE,
        );
      svg += note(
        "Keep measurement method and units. EC is not an exact nutrient analysis.",
      );
      break;
    }
    case "sensor-check": {
      svg +=
        rect(60, 140, 252, 220, "#edf3f5", INK) +
        text(186, 180, "Probe evidence", { anchor: "middle", weight: 700 });
      svg +=
        '<path d="M130 323V224h35v99 M147 220v-29" stroke="#172c3c" stroke-width="6" fill="none"/>';
      svg +=
        line(85, 280, 288, 280, "#806b50") +
        text(185, 347, "Placement + contact", { anchor: "middle", size: 18 });
      svg += text(358, 164, "1  Exact identity + location", {
        size: 26,
        weight: 700,
      });
      svg += text(358, 218, "2  Correct quantity + units", {
        size: 26,
        weight: 700,
      });
      svg += text(358, 272, "3  Fresh timestamp + update rate", {
        size: 26,
        weight: 700,
      });
      svg += text(358, 326, "4  Suitable independent check", {
        size: 26,
        weight: 700,
      });
      svg += note(
        "Fresh data can still be from the wrong room or measure the wrong thing.",
      );
      break;
    }
    case "combined-graph": {
      const x = 102,
        y = 140,
        w = 698,
        h = 206;
      svg +=
        rect(x, y, w, h, "#fff", "#a8bbc7", 0) +
        rect(451, y, 349, h, "#e9e9ed", "#e9e9ed", 0);
      svg += text(108, 115, "VWC (%) · left axis", {
        color: BLUE,
        size: 22,
        weight: 700,
      });
      svg += text(610, 115, "EC (mS/cm) · right axis", {
        color: PINK,
        size: 22,
        weight: 700,
      });
      for (let i = 0; i <= 3; i++) {
        const py = y + h - (i * h) / 3;
        svg +=
          line(x, py, x + w, py, "#c7d2da", 'stroke-width="1"') +
          text(86, py + 7, String(20 + i * 20), {
            size: 18,
            anchor: "end",
            color: BLUE,
          }) +
          text(818, py + 7, String(i * 2), { size: 18, color: PINK });
      }
      for (const [i, time] of ["06", "12", "18", "00", "06"].entries())
        svg += text(x + (w * i) / 4, 377, time, { size: 19, anchor: "middle" });
      svg += text(612, 165, "Night (example)", { size: 19, color: MUTED });
      svg +=
        '<polyline points="102,238 148,247 193,258 204,211 251,224 262,192 310,211 322,181 370,198 420,214 470,230 540,244 610,261 680,276 740,287 800,301" fill="none" stroke="#126396" stroke-width="5" stroke-linejoin="round"/>';
      svg +=
        '<polyline points="102,232 180,222 260,237 340,226 420,216 500,205 580,196 660,188 730,180 800,172" fill="none" stroke="#a52a62" stroke-width="4" stroke-dasharray="10 4 2 4"/>';
      svg += line(
        102,
        183,
        800,
        183,
        BLUE,
        'stroke-dasharray="13 8" stroke-width="3"',
      );
      for (const px of [204, 262, 322])
        svg +=
          line(px, 321, px, 340, GREEN) + circle(px, 316, 5, "#fff", GREEN);
      svg += text(108, 405, "Solid blue: actual VWC", {
        size: 19,
        color: BLUE,
        width: 30,
      });
      svg += text(455, 405, "Dot-dash pink: actual EC", {
        size: 19,
        color: PINK,
      });
      svg += text(108, 435, "Dashed blue: planned reference", {
        size: 19,
        color: BLUE,
      });
      svg += text(455, 435, "Stem markers: irrigation events", {
        size: 19,
        color: GREEN,
      });
      svg += note(
        "Synthetic example. A reference change cannot rewrite actual readings.",
        479,
      );
      break;
    }
    case "phases": {
      svg += process(
        [
          ["P0", "Morning dryback"],
          ["P1", "Ramp-up"],
          ["P2", "Maintenance"],
          ["P3", "Overnight"],
        ],
        { colors: [AMBER, BLUE, GREEN, PINK] },
      );
      svg += text(480, 370, "Lights-on → grow-day → next lights-on", {
        anchor: "middle",
        size: 27,
        weight: 700,
        width: 60,
      });
      svg += note(
        "Order shows program meaning; actual transitions and shots are conditional.",
      );
      break;
    }
    case "steering": {
      const a = finite(values[0], 20),
        b = finite(values[1], 40),
        amount = clamp(finite(values[2], 0.5), 0, 1);
      svg += card(
        48,
        130,
        250,
        157,
        "Vegetative endpoint",
        `Configured value: ${number(a)}`,
        GREEN,
      );
      svg += card(
        662,
        130,
        250,
        157,
        "Generative endpoint",
        `Configured value: ${number(b)}`,
        PINK,
      );
      svg +=
        line(115, 336, 845, 336, INK) +
        circle(115 + 730 * amount, 336, 13, "#fff", BLUE);
      svg += text(480, 181, `${number(amount * 100)}% of the way`, {
        anchor: "middle",
        size: 23,
      });
      svg += text(480, 238, `${number(a + (b - a) * amount)}`, {
        anchor: "middle",
        size: 46,
        weight: 700,
        color: BLUE,
      });
      svg += text(480, 384, "Example interpolation: A + position × (B − A)", {
        anchor: "middle",
        size: 24,
        width: 65,
      });
      svg += note(
        "Arbitrary configured endpoints. These are not universal crop targets.",
      );
      break;
    }
    case "flow": {
      const perEmitter = Math.max(0, finite(values[0], 4)),
        drippers = Math.max(0, finite(values[1], 2)),
        seconds = Math.max(0, finite(values[2], 30)),
        plants = Math.max(0, finite(values[3], 12));
      const perPlant = (perEmitter * drippers * seconds) / 3600;
      svg += process(
        [
          ["Emitter flow", `${number(perEmitter)} L/h`],
          ["Drippers", `${number(drippers)} / plant`],
          ["Runtime", `${number(seconds)} s ÷ 3600`],
          ["Plant count", `${number(plants)} plants`],
        ],
        { y: 132, height: 150 },
      );
      svg += text(480, 330, "Flow × drippers × seconds ÷ 3600 × plants", {
        anchor: "middle",
        size: 28,
        weight: 700,
        width: 60,
      });
      svg += text(
        480,
        379,
        `${number(perPlant * 1000)} mL / plant     |     ${number(perPlant * plants)} L / zone`,
        { anchor: "middle", size: 29, color: BLUE, weight: 700 },
      );
      svg += note("Example delivery estimate. Delivered water ≠ plant uptake.");
      break;
    }
    case "equipment": {
      svg += card(
        48,
        126,
        260,
        176,
        "Host + network",
        "Supported always-on computer and recovery",
        BLUE,
      );
      svg += card(
        350,
        126,
        260,
        176,
        "Measurement path",
        "Compatible probe, interface and fresh entity",
        PINK,
      );
      svg += card(
        652,
        126,
        260,
        176,
        "Water path",
        "Suitable supply, controlled zone and emitters",
        GREEN,
      );
      svg +=
        rect(110, 332, 740, 56, "#f8f0dc", "#aa8228") +
        text(480, 368, "Independent protection + physical shutdown", {
          anchor: "middle",
          size: 25,
          color: AMBER,
          weight: 700,
          width: 60,
        });
      svg += note(
        "Choose functions that the real installation needs. A pump is conditional.",
      );
      break;
    }
    case "host": {
      svg += card(
        62,
        132,
        340,
        172,
        "Raspberry Pi HAOS",
        "Check exact model, PSU, supported storage and Ethernet",
        BLUE,
      );
      svg += text(480, 227, "OR", { anchor: "middle", size: 37, weight: 700 });
      svg += card(
        558,
        132,
        340,
        172,
        "Dedicated x86-64 HAOS",
        "Check firmware, storage, power and Ethernet",
        GREEN,
      );
      svg += text(
        480,
        358,
        "Verify destination + backup BEFORE image writing",
        { anchor: "middle", size: 27, weight: 700, color: AMBER },
      );
      svg += note(
        "One supported host route. Writing erases the selected destination storage.",
      );
      break;
    }
    case "entities": {
      svg += card(
        48,
        193,
        240,
        133,
        "One device",
        "Known physical label",
        GREEN,
      );
      svg += line(310, 175, 310, 342) + line(288, 257, 310, 257);
      for (const [i, heading, detail] of [
        [0, "Reading: moisture", "Quantity + units + age"],
        [1, "Reading: temperature", "A different measurement"],
        [2, "Control, if present", "A command may act physically"],
      ]) {
        const y = 116 + i * 94;
        svg +=
          arrow(310, y + 42, 359, y + 42) +
          rect(365, y, 535, 79) +
          text(387, y + 31, heading, { size: 23, weight: 700 }) +
          text(387, y + 59, detail, { size: 19 });
      }
      svg += note(
        "Multiple entities do not imply multiple physical devices. Verify exact IDs.",
      );
      break;
    }
    case "water-path": {
      svg += text(48, 116, "A · Suitable pressurised supply", {
        size: 26,
        weight: 700,
        color: BLUE,
      });
      svg += process(
        [
          ["Supply", "Existing pressure"],
          ["Protection", "As designed"],
          ["Zone valve", "One owner"],
          ["Emitters", "Then drainage"],
        ],
        { y: 139, height: 116 },
      );
      svg += text(48, 294, "B · Reservoir with pump", {
        size: 26,
        weight: 700,
        color: GREEN,
      });
      svg += process(
        [
          ["Reservoir", "Usable supply"],
          ["Pump", "With verified protection"],
          ["Zone valve", "One owner"],
          ["Emitters", "Then drainage"],
        ],
        { y: 317, height: 116 },
      );
      svg += note(
        "Functional paths; not a construction drawing. Component order is site-specific.",
        482,
      );
      break;
    }
    case "controls": {
      svg += card(
        48,
        130,
        405,
        222,
        "Software: Watering OFF",
        "Blocks Controller ordinary, rescue AND test shots",
        BLUE,
      );
      svg += card(
        507,
        130,
        405,
        222,
        "Physical shutdown",
        "Installation-specific power / water isolation procedure",
        AMBER,
      );
      svg += text(480, 256, "≠", { anchor: "middle", size: 49, weight: 700 });
      svg += note(
        "Independent controls can still act. One owner per physical output.",
      );
      break;
    }
    case "mapping": {
      svg += process(
        [
          ["Identify", "Room, zone, exact entities"],
          ["Verify", "Units, freshness, sizing"],
          ["Review + save", "Stored HA revision"],
          ["Acknowledged", "Controller accepts revision"],
        ],
        { y: 139, height: 204, colors: [INK, BLUE, AMBER, GREEN] },
      );
      svg += note(
        "Saved ≠ acknowledged. Timezone ≠ the actual room lighting schedule.",
      );
      break;
    }
    case "commissioning": {
      svg += card(
        48,
        121,
        380,
        209,
        "1 · Equipment catch test",
        "Watering OFF. Installer-approved bounded procedure.",
        BLUE,
      );
      svg +=
        arrow(447, 227, 509, 227) +
        text(480, 355, "Readiness gate", {
          anchor: "middle",
          size: 23,
          weight: 700,
          color: AMBER,
        });
      svg += card(
        528,
        121,
        384,
        209,
        "2 · Controller cycle",
        "Only after all checks pass. Supervised enabled operation.",
        GREEN,
      );
      svg += note(
        "Prove outlet, other zones dry, actual stop and no unwanted siphon.",
      );
      break;
    }
    case "navigation": {
      svg +=
        rect(48, 119, 864, 58, "#e3edf2", "#a5bdcb") +
        text(74, 157, "First: verify selected room + zone + data age", {
          size: 28,
          weight: 700,
        });
      svg += process(
        [
          ["Overview", "State + next action"],
          ["Equipment", "Probes + Setup"],
          ["Irrigation", "Current day + Calendar"],
          ["History", "Recorded evidence"],
        ],
        { y: 213, height: 146 },
      );
      svg += note("Check action scope before review, apply and readback.");
      break;
    }
    case "target": {
      svg += process(
        [
          ["Draft", "A proposed value"],
          ["Review", "Check change + scope"],
          ["Apply", "Write through review"],
          ["Read back", "Verify stored result"],
        ],
        { y: 122, height: 171 },
      );
      svg +=
        line(94, 349, 856, 349, BLUE, 'stroke-dasharray="12 8"') +
        text(
          480,
          384,
          "Reference can move; actual recorded measurements stay actual.",
          { anchor: "middle", size: 24, width: 65 },
        );
      svg += note(
        "Plan-owned targets use Calendar. Example values are not crop instructions.",
      );
      break;
    }
    case "calendar": {
      svg += process(
        [
          ["Draft", "Review schedule"],
          ["Save", "Store the plan"],
          ["Arm", "Request activation"],
          ["Lights-on", "Eligible boundary"],
        ],
        { y: 128, height: 169 },
      );
      svg +=
        rect(95, 331, 770, 60, "#f8f0dc", "#aa8228") +
        text(480, 369, "Arming a plan does not enable Watering.", {
          anchor: "middle",
          size: 27,
          color: AMBER,
          weight: 700,
          width: 60,
        });
      svg += note(
        "Disarm requests next-lights-on handover; it is not emergency isolation.",
      );
      break;
    }
    case "comparison": {
      svg += card(
        48,
        126,
        405,
        220,
        "Evidence A",
        "Room / zone · dates · units · age · coverage",
        BLUE,
      );
      svg += card(
        507,
        126,
        405,
        220,
        "Evidence B",
        "Match scope and measurement type before comparing",
        PINK,
      );
      svg += text(480, 251, "?", { anchor: "middle", size: 46, weight: 700 });
      svg += note(
        "Current reference ≠ historical target evidence. Delivery ≠ measured uptake.",
      );
      break;
    }
    case "troubleshooting": {
      svg +=
        rect(48, 121, 864, 86, "#f8f0dc", "#aa8228") +
        text(73, 158, "Unexpected continuing water?", {
          size: 27,
          weight: 700,
          color: AMBER,
        }) +
        text(73, 188, "Use the agreed physical shutdown; then investigate.", {
          size: 22,
        });
      svg += process(
        [
          ["Data fault?", "Check identity + age"],
          ["Setup fault?", "Check acknowledgement"],
          ["Correct + verify", "Record cause + readback"],
        ],
        { y: 240, height: 132 },
      );
      svg += note(
        "Do not bypass holds, force outputs or change a recipe to hide a fault.",
      );
      break;
    }
    case "daily-check": {
      const checks = [
        "1  Data: identity, units and freshness",
        "2  Room: phase, readiness and next action",
        "3  Water: actual delivery and stopping",
        "4  Context: tank, feed and exceptions",
        "5  Record: evidence, action and follow-up",
      ];
      checks.forEach((item, index) => {
        svg +=
          rect(55, 116 + index * 55, 35, 35, "#fff", "#617b88", 5) +
          text(111, 142 + index * 55, item, { size: 25, width: 65 });
      });
      svg += note(
        "Unknown is not OFF. An AI suggestion is not verified plant evidence.",
      );
      break;
    }
    default:
      svg += process(
        labels.length
          ? labels
              .slice(0, 4)
              .map((label, index) => [`Step ${index + 1}`, label])
          : [
              ["Observe", "Name the real object"],
              ["Explain", "Check evidence + scope"],
              ["Practise", "Review the result"],
            ],
        { y: 147, height: 228 },
      );
      svg += note("Use the lesson cues and text explanation below.");
  }
  return svg;
}

function hash(value) {
  let result = 2166136261;
  for (const char of value)
    result = Math.imul(result ^ char.codePointAt(0), 16777619);
  return (result >>> 0).toString(36);
}

/**
 * Return a self-contained figure; importing this module has no DOM side effects.
 * Optional value orders: fraction [part, reference]; dryback [start, end];
 * fraction.quantity names a neutral fraction; without it the diagram teaches VWC.
 * steering [endpointA, endpointB, position0to1]; flow [emitterLh, drippers, seconds, plants].
 * Other types use conceptual diagrams. Supplied lesson cues remain visible in the caption.
 */
export function createVisual(
  visual = {},
  { lessonId = "", slideId = "" } = {},
) {
  const data = visual && typeof visual === "object" ? visual : {};
  const type = typeof data.type === "string" ? data.type : "process";
  const defaults = DEFAULTS[type] || [
    "A labelled learning process",
    "Observe, explain and practise the process using the supplied lesson cues.",
  ];
  const title =
    typeof data.title === "string" && data.title.trim()
      ? data.title
      : defaults[0];
  const labels = Array.isArray(data.labels)
    ? data.labels.filter((label) => typeof label === "string" && label.trim())
    : [];
  const values = Array.isArray(data.values) ? data.values : [];
  const quantity =
    typeof data.quantity === "string" ? data.quantity.trim() : "";
  let description = type === "lesson-cues" ? "Read the lesson-specific steps and examples." : defaults[1];
  if (type === "fraction") {
    const part = finite(values[0], 6),
      total = finite(values[1], 10);
    description =
      total === 0
        ? "The reference amount is zero. Division by zero is undefined."
        : quantity
          ? `${quantity}: ${number(part)} divided by ${number(total)}, multiplied by 100, equals ${number((part / total) * 100)}%. Ten cells illustrate one reference amount; the calculation retains the stated exact inputs.`
          : `${number(part)} of ${number(total)} total volumes contain water: ${number((part / total) * 100)}% VWC. This is not percent plant-available water. The rest includes solids and air.`;
  } else if (type === "dryback") {
    const start = clamp(finite(values[0], 60), 0.01, 100),
      end = clamp(finite(values[1], 45), 0, start);
    description = `Example: ${number(start)}% to ${number(end)}% VWC is ${number(start - end)} percentage points and ${number(((start - end) / start) * 100)}% relative dryback from the starting value.`;
  } else if (type === "flow") {
    const flow = Math.max(0, finite(values[0], 4)),
      drippers = Math.max(0, finite(values[1], 2)),
      seconds = Math.max(0, finite(values[2], 30)),
      plants = Math.max(0, finite(values[3], 12));
    const perPlant = (flow * drippers * seconds) / 3600;
    description = `Example: ${number(flow)} L/h per emitter × ${number(drippers)} drippers per plant × ${number(seconds)} seconds ÷ 3600 × ${number(plants)} plants = ${number(perPlant * plants)} litres per zone, or ${number(perPlant * 1000)} millilitres per plant. Estimated delivery is not plant uptake.`;
  } else if (type === "steering") {
    const a = finite(values[0], 20),
      b = finite(values[1], 40),
      position = clamp(finite(values[2], 0.5), 0, 1);
    description = `Example configured endpoints ${number(a)} and ${number(b)} at ${number(position * 100)}% of the way yield ${number(a + (b - a) * position)}. These arbitrary values are not universal crop targets. Identical endpoints yield no change.`;
  }
  const customCaption =
    typeof data.caption === "string" ? data.caption.trim() : "";
  const fullDescription = [
    typeof data.asset === "string" && data.alt ? data.alt : description,
    labels.length ? `Lesson cues: ${labels.join("; ")}.` : "",
    customCaption,
  ]
    .filter(Boolean)
    .join(" ");
  const id = `teaching-${hash(JSON.stringify([lessonId, slideId, type, title, labels, values, quantity]))}`;
  const figure = document.createElement("figure");
  figure.className = "teaching-visual";
  figure.dataset.visualType = type;
  // Asset paths are deliberately restricted to local teaching illustrations.
  if (typeof data.asset === "string" && /^assets\/(?:diagrams|screens)\/[a-zA-Z0-9_./-]+\.(?:png|jpe?g|webp)$/.test(data.asset) && !data.asset.includes("..")) {
    const img = document.createElement("img");
    img.src = data.asset;
    img.alt = typeof data.alt === "string" && data.alt.trim() ? data.alt : fullDescription;
    Object.assign(img.style, {display: "block", width: "100%", height: "auto", maxWidth: "960px", borderRadius: "14px"});
    const caption = document.createElement("figcaption");
    caption.textContent = fullDescription;
    figure.dataset.visualMode = "asset";
    figure.append(img, caption);
    return figure;
  }
  // Long lesson titles remain fully available in SVG title and the text caption.
  const heading = lines(title, 48).slice(0, 2).join(" ");
  figure.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 520" role="img" aria-labelledby="${id}-title" aria-describedby="${id}-desc" style="display:block;width:100%;height:auto;max-width:960px;background:#fbfcfd;border-radius:14px;font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"><title id="${id}-title">${escape(title)}</title><desc id="${id}-desc">${escape(fullDescription)}</desc>${rect(1, 1, 958, 518, "#fbfcfd", "#c7d4dc", 14)}${text(48, 51, heading, { size: 30, weight: 750, width: 48, gap: 34 })}${render(type, values, labels, quantity, data.focus)}</svg>`;
  const caption = document.createElement("figcaption");
  caption.textContent = fullDescription;
  figure.append(caption);
  return figure;
}
