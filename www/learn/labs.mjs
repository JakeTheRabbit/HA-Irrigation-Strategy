import {
  calculateDryback,
  calculateFlow,
  planningPreview,
} from "./practice.mjs";

// Styling hooks: practice-labs, practice-lab, lab-form/field/result/readings,
// threshold-chart. All calculations are local examples; no controller connection.
const el = (tag, className = "", text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
};
const number = (value) =>
  new Intl.NumberFormat("en-NZ", { maximumFractionDigits: 4 }).format(value);
function field(form, text, value, { min = 0, max, step = "any", name } = {}) {
  const label = el("label", "lab-field");
  label.append(el("span", "", text));
  const input = el("input");
  input.type = "number";
  input.value = String(value);
  input.min = String(min);
  input.step = String(step);
  input.required = true;
  if (max !== undefined) input.max = String(max);
  if (name) input.name = name;
  label.append(input);
  form.append(label);
  return input;
}
function read(input) {
  if (!input.value.trim())
    throw Error("Complete each input before calculating.");
  const value = Number(input.value);
  if (!Number.isFinite(value))
    throw Error("Use a finite number for each input.");
  return value;
}
function resultArea() {
  const result = el("div", "lab-result");
  result.setAttribute("role", "status");
  result.setAttribute("aria-live", "polite");
  return result;
}
function calculationForm(title, description) {
  const section = el("section", "practice-lab panel");
  section.append(el("h2", "", title), el("p", "", description));
  const form = el("form", "lab-form");
  form.noValidate = true;
  const result = resultArea();
  const button = el("button", "", "Calculate");
  button.type = "submit";
  section.append(form, result);
  return { section, form, result, button };
}
function drybackLab() {
  const { section, form, result, button } = calculationForm(
    "Dryback: points and relative percentage",
    "Use the same probe and a stated interval. These values describe water content, not percent plant-available water or measured uptake.",
  );
  const start = field(form, "Starting VWC (%)", 60, {
    min: 0.01,
    max: 100,
    name: "start",
  });
  const end = field(form, "Ending VWC (%)", 45, { max: 100, name: "end" });
  form.append(button);
  const calculate = () => {
    try {
      const a = read(start),
        b = read(end);
      const value = calculateDryback(a, b);
      result.className = "lab-result";
      result.replaceChildren(
        el(
          "p",
          "",
          `${number(a)}% to ${number(b)}% VWC: ${number(value.points)} percentage points; ${number(value.relative)}% relative dryback.`,
        ),
        el(
          "p",
          "muted",
          `Points = ${number(a)} − ${number(b)}. Relative dryback = (${number(a)} − ${number(b)}) ÷ ${number(a)} × 100.`,
        ),
      );
    } catch (error) {
      result.className = "lab-result incorrect";
      result.textContent = error.message;
    }
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    calculate();
  });
  calculate();
  section.append(
    el(
      "p",
      "muted",
      "Try 50% to 40%. Explain why 10 percentage points and 20% relative dryback describe the same fall.",
    ),
  );
  return section;
}
function flowLab() {
  const { section, form, result, button } = calculationForm(
    "Water delivery: per plant and per zone",
    "Multiply emitter flow by emitters per plant and effective runtime in hours. Multiply that per-plant amount by plant count for the zone estimate.",
  );
  const flow = field(form, "Flow per emitter (L/h)", 4, {
    min: 0.001,
    name: "litersPerHour",
  });
  const drippers = field(form, "Emitters per plant", 2, {
    min: 1,
    step: 1,
    name: "drippersPerPlant",
  });
  const seconds = field(form, "Effective runtime (seconds)", 45, {
    min: 0.001,
    name: "seconds",
  });
  const plants = field(form, "Plants in the zone", 20, {
    min: 1,
    step: 1,
    name: "plants",
  });
  const basisLabel = el("label", "lab-field");
  basisLabel.append(el("span", "", "Source of flow value"));
  const basis = el("select");
  basis.name = "flowBasis";
  for (const [value, text] of [
    ["nominal", "Rated / assumed flow"],
    ["measured", "Measured by a suitable catch test"],
  ]) {
    const option = el("option", "", text);
    option.value = value;
    basis.append(option);
  }
  basisLabel.append(basis);
  form.append(basisLabel, button);
  const calculate = () => {
    try {
      const inputs = {
        litersPerHour: read(flow),
        drippersPerPlant: read(drippers),
        seconds: read(seconds),
        plants: read(plants),
      };
      const value = calculateFlow(inputs);
      result.className = "lab-result";
      result.replaceChildren(
        el(
          "p",
          "",
          `${number(value.perPlant)} L (${number(value.perPlant * 1000)} mL) per plant. ${number(value.zone)} L per zone.`,
        ),
        el(
          "p",
          "muted",
          `${number(inputs.litersPerHour)} × ${number(inputs.drippersPerPlant)} × ${number(inputs.seconds)} ÷ 3600 = litres per plant. Then multiply by ${number(inputs.plants)} plants.`,
        ),
        el(
          "p",
          "muted",
          `${basis.value === "measured" ? "Using a measured flow input" : "Using a rated or assumed flow input"}. Runtime-based delivery estimate; this does not measure current equal delivery, runoff or plant uptake.`,
        ),
      );
    } catch (error) {
      result.className = "lab-result incorrect";
      result.textContent = error.message;
    }
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    calculate();
  });
  calculate();
  section.append(
    el(
      "p",
      "muted",
      "Use effective runtime after duration limits. A shot equal to 2% of substrate volume does not guarantee a two-point VWC rise. Conditional shots prevent a guaranteed whole-day total.",
    ),
  );
  return section;
}
const svgEl = (tag, attributes = {}, text) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) =>
    node.setAttribute(key, String(value)),
  );
  if (text !== undefined) node.textContent = String(text);
  return node;
};
function thresholdLab() {
  const section = el("section", "practice-lab panel");
  section.append(
    el("h2", "", "Move a draft threshold; keep actual data fixed"),
    el(
      "p",
      "",
      "Synthetic teaching data. An emergency floor is a reference used by a rule. Changing it does not rewrite observations, schedule a shot, or operate equipment.",
    ),
  );
  const points = Object.freeze(
    [62, 60, 56, 54, 49, 47].map((vwc, i) =>
      Object.freeze({ hour: i * 4, vwc }),
    ),
  );
  const savedFloor = 35;
  const label = el("label", "lab-field");
  const labelText = el("span", "", "Draft P3 emergency floor: ");
  const valueText = el("output", "", `${savedFloor}% VWC`);
  const slider = el("input");
  slider.type = "range";
  slider.min = "0";
  slider.max = "100";
  slider.step = "1";
  slider.value = String(savedFloor);
  slider.name = "draftFloor";
  slider.setAttribute("aria-label", "Draft P3 emergency floor, percent VWC");
  labelText.append(valueText);
  label.append(labelText, slider);
  const reset = el("button", "", "Reset example floor");
  reset.type = "button";
  section.append(label, reset);
  const figure = el("figure", "threshold-chart");
  const svg = svgEl("svg", {
    viewBox: "0 0 760 370",
    role: "img",
    "aria-labelledby": "threshold-lab-title threshold-lab-description",
  });
  svg.append(
    svgEl(
      "title",
      { id: "threshold-lab-title" },
      "Synthetic VWC observations and a draft emergency floor",
    ),
    svgEl(
      "desc",
      { id: "threshold-lab-description" },
      "The blue solid actual trace stays fixed. The dashed draft floor changes with the slider. The dotted saved floor stays at 35% VWC. A data table follows.",
    ),
  );
  const left = 65,
    top = 25,
    width = 650,
    height = 250;
  const y = (value) => top + height * (1 - value / 100);
  const x = (hour) => left + (width * hour) / 20;
  svg.append(
    svgEl("rect", {
      x: left,
      y: top,
      width,
      height,
      fill: "#fff",
      stroke: "#8a9ca8",
    }),
  );
  [0, 20, 40, 60, 80, 100].forEach((value) => {
    svg.append(
      svgEl("line", {
        x1: left,
        x2: left + width,
        y1: y(value),
        y2: y(value),
        stroke: "#d7e1e8",
      }),
      svgEl(
        "text",
        {
          x: left - 10,
          y: y(value) + 5,
          "text-anchor": "end",
          fill: "#172c3c",
          "font-size": 15,
        },
        `${value}`,
      ),
    );
  });
  [0, 4, 8, 12, 16, 20].forEach((hour) =>
    svg.append(
      svgEl(
        "text",
        {
          x: x(hour),
          y: 300,
          "text-anchor": "middle",
          fill: "#172c3c",
          "font-size": 15,
        },
        `${hour} h`,
      ),
    ),
  );
  svg.append(
    svgEl("text", { x: 5, y: 17, fill: "#172c3c", "font-size": 15 }, "VWC (%)"),
  );
  const saved = svgEl("line", {
    x1: left,
    x2: left + width,
    y1: y(savedFloor),
    y2: y(savedFloor),
    stroke: "#53616e",
    "stroke-width": 2,
    "stroke-dasharray": "2 5",
    "data-saved-floor": "",
  });
  const actual = svgEl("polyline", {
    points: points.map((p) => `${x(p.hour)},${y(p.vwc)}`).join(" "),
    fill: "none",
    stroke: "#126396",
    "stroke-width": 4,
    "data-actual-trace": "",
  });
  const floor = svgEl("line", {
    x1: left,
    x2: left + width,
    y1: y(savedFloor),
    y2: y(savedFloor),
    stroke: "#9c3e00",
    "stroke-width": 3,
    "stroke-dasharray": "12 7",
    "data-draft-floor": "",
  });
  svg.append(saved, actual, floor);
  svg.append(
    svgEl(
      "text",
      { x: 65, y: 333, fill: "#126396", "font-size": 16 },
      "Solid blue: actual observations",
    ),
    svgEl(
      "text",
      { x: 65, y: 359, fill: "#9c3e00", "font-size": 16 },
      "Dashed brown: draft floor",
    ),
    svgEl(
      "text",
      { x: 395, y: 359, fill: "#53616e", "font-size": 16 },
      "Dotted grey: saved floor 35%",
    ),
  );
  figure.append(
    svg,
    el(
      "figcaption",
      "",
      "Illustration only. All six actual VWC values remain fixed when you move the floor. Actual data, saved reference and draft reference are separate.",
    ),
  );
  section.append(figure);
  const result = resultArea();
  const update = () => {
    const preview = planningPreview(slider.value, points);
    valueText.textContent = `${preview.floor}% VWC`;
    slider.setAttribute("aria-valuetext", `${preview.floor} percent VWC`);
    floor.setAttribute("y1", String(y(preview.floor)));
    floor.setAttribute("y2", String(y(preview.floor)));
    result.textContent = `Draft floor: ${preview.floor}% VWC. Saved floor: ${savedFloor}% VWC. The six actual observations are unchanged. This is a local preview, with no applied change or scheduled shot.`;
  };
  slider.addEventListener("input", update);
  reset.addEventListener("click", () => {
    slider.value = String(savedFloor);
    update();
  });
  const table = el("table", "lab-readings");
  table.append(el("caption", "", "Fixed synthetic observations"));
  const head = el("thead");
  const headings = el("tr");
  for (const text of ["Hours from example start", "Actual VWC (%)"]) {
    const th = el("th", "", text);
    th.scope = "col";
    headings.append(th);
  }
  head.append(headings);
  const body = el("tbody");
  points.forEach((point) => {
    const row = el("tr");
    row.append(el("td", "", point.hour), el("td", "", point.vwc));
    body.append(row);
  });
  table.append(head, body);
  section.append(result, disclosureTable(table));
  update();
  return section;
}
function disclosureTable(table) {
  const details = el("details");
  details.append(el("summary", "", "Read the actual-data table"), table);
  return details;
}

/** Return three standalone, local-only learning labs. No DOM effects on import. */
export function renderPractice() {
  const root = el("article", "practice-labs");
  root.append(
    el("h1", "", "Practice with the numbers"),
    el(
      "p",
      "",
      "Examples only — not recommended crop settings. These calculators run in this browser and do not connect to Home Assistant.",
    ),
    drybackLab(),
    flowLab(),
    thresholdLab(),
  );
  return root;
}
