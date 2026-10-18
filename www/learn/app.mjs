import {
  loadProgress,
  saveProgress,
  importProgress,
  routeLessons,
  nextLesson,
  reviewDue,
} from "./state.mjs";
import { renderLesson } from "./lesson.mjs?v=20261019r2";
import { renderPractice } from "./labs.mjs";
const main = document.querySelector("#main");
const notice = document.querySelector("#storage-notice");
document.querySelector(".skip-link").addEventListener("click", (event) => {
  event.preventDefault();
  main.focus({ preventScroll: true });
  main.scrollIntoView({ block: "start" });
});
let course,
  progress,
  renderId = 0;
const node = (tag, cls, text) => {
  const x = document.createElement(tag);
  if (cls) x.className = cls;
  if (text !== undefined) x.textContent = text;
  return x;
};
const add = (parent, ...children) => {
  for (const child of children) if (child) parent.append(child);
  return parent;
};
const link = (text, href, cls = "") => {
  const x = node("a", cls, text);
  x.href = href;
  return x;
};
const button = (text, action, cls = "") => {
  const x = node("button", cls, text);
  x.type = "button";
  x.addEventListener("click", action);
  return x;
};
const storage = {
  getItem: (key) => window.localStorage.getItem(key),
  setItem: (key, value) => window.localStorage.setItem(key, value),
};
const ids = () => course.lessons.map((x) => x.id);
const lessonById = (id) => course.lessons.find((x) => x.id === id);
const path = () => routeLessons(course.lessons, progress.route);
const passed = (lesson) => Boolean(progress.completed[lesson.id]);
const routeNames = {
  operator: "Use an existing system",
  "builder-pi": "Build with Raspberry Pi",
  "builder-x86": "Build with x86-64",
};
function save(updated) {
  if (updated && typeof updated === "object") progress = updated;
  const ok = saveProgress(storage, progress);
  notice.hidden = ok;
  notice.textContent = ok
    ? ""
    : "This browser cannot save progress. You can keep learning in this tab; export progress before closing it.";
  return ok;
}
function navigate(target) {
  if (!target || target === "home") target = "/";
  else if (lessonById(target)) target = "/lesson/" + encodeURIComponent(target);
  else if (!target.startsWith("/")) target = "/" + target;
  const hash = "#" + target;
  if (location.hash === hash) void render();
  else location.hash = hash;
}
function heading(title, description, eyebrow) {
  const h = node("header", "page-heading");
  if (eyebrow) add(h, node("p", "eyebrow", eyebrow));
  add(h, node("h1", "", title));
  if (description) add(h, node("p", "lede", description));
  return h;
}
function routePicker() {
  const box = node("section", "route-picker");
  const label = node("label", "", "Choose your learning route");
  label.htmlFor = "learning-route";
  const select = node("select");
  select.id = "learning-route";
  for (const [value, text] of Object.entries(routeNames)) {
    const o = node("option", "", text);
    o.value = value;
    o.selected = progress.route === value;
    select.append(o);
  }
  select.addEventListener("change", async () => {
    progress.route = select.value;
    save();
    await render(false);
    document.querySelector("#learning-route")?.focus({ preventScroll: true });
  });
  add(
    box,
    label,
    select,
    node(
      "p",
      "muted",
      "All lessons stay available. Builders choose one host lesson. Operators need a local installer handover before live use.",
    ),
  );
  return box;
}
function continueLesson() {
  const last = lessonById(progress.lastLesson);
  return last && !passed(last) && path().some((x) => x.id === last.id)
    ? last
    : nextLesson(course.lessons, progress);
}
function summaryLine() {
  const route = path();
  const count = route.filter(passed).length;
  return `${count} of ${route.length} recommended lessons passed in this browser`;
}
function lessonRow(lesson, recommended = true) {
  const row = node(
    "li",
    "course-lesson" + (passed(lesson) ? " is-complete" : ""),
  );
  const anchor = link(
    "",
    "#/lesson/" + encodeURIComponent(lesson.id),
    "lesson-row-link",
  );
  add(anchor, node("span", "lesson-id", lesson.id));
  const text = node("span", "lesson-row-text");
  add(
    text,
    node("strong", "", lesson.title),
    node("span", "muted", lesson.summary),
  );
  add(
    anchor,
    text,
    node(
      "span",
      "lesson-status",
      passed(lesson) ? "Passed" : recommended ? "Start lesson" : "Optional",
    ),
  );
  row.append(anchor);
  return row;
}
function home() {
  const wrap = node("div", "home-page");
  const hero = node("section", "hero");
  const copy = node("div", "hero-copy");
  add(
    copy,
    node("p", "eyebrow", "Crop steering, from zero"),
    node("h1", "", "Understand what happens after the water goes in."),
    node(
      "p",
      "hero-description",
      "Read the root zone. Make sense of a watering day. Learn each control before you use it. A practical course for people starting fresh.",
    ),
  );
  const current = continueLesson();
  const actions = node("div", "actions");
  add(
    actions,
    link(
      progress.lastLesson ? "Continue learning" : "Start with the roots",
      "#/lesson/" + encodeURIComponent(current?.id || "A1"),
      "button primary",
    ),
    link("Explore the course", "#/course", "text-link"),
  );
  add(
    copy,
    actions,
    node(
      "p",
      "hero-note",
      "24 lessons, with one host alternative. Pause, practise and return at your own pace.",
    ),
  );
  const figure = node("figure", "hero-image");
  const image = node("img");
  image.src = "assets/course-bench.png";
  image.alt =
    "An illustrative teaching bench with a plant in substrate, water jug, loose probe and irrigation parts.";
  image.width = 1400;
  image.height = 1024;
  image.fetchPriority = "high";
  add(
    figure,
    image,
    node(
      "figcaption",
      "",
      "Begin with the water, the medium and the question you need to answer.",
    ),
  );
  add(hero, copy, figure);
  add(wrap, hero);
  const intro = node("section", "learning-intro");
  add(
    intro,
    node("p", "chapter-mark", "A good place to begin"),
    node("h2", "", "You do not need to know the language yet."),
    node(
      "p",
      "",
      "Each lesson explains one idea, works through an example, then gives you space to try it. Use the isolated software demo for practice. Real equipment comes later, with competent local supervision.",
    ),
  );
  add(wrap, intro);
  const learning = node("section", "learning-map");
  add(learning, node("h2", "", "Four parts, one connected picture."));
  const grid = node("div", "module-grid");
  for (const module of course.modules) {
    const count = course.lessons.filter((x) => x.module === module.id).length;
    const item = link("", "#/course", "module-preview");
    add(
      item,
      node("span", "module-letter", module.id),
      node("h3", "", module.title),
      node("p", "", module.description),
      node("span", "muted", `${count} lessons`),
    );
    grid.append(item);
  }
  add(learning, grid);
  add(wrap, learning);
  const bench = node("section", "practice-banner");
  add(bench, node("div", "", undefined));
  add(
    bench.firstChild,
    node("h2", "", "Try the idea before changing a setting."),
    node(
      "p",
      "",
      "Practise dryback, water delivery and threshold reading with fictional examples. Nothing here operates a pump.",
    ),
  );
  add(bench, link("Open the practice bench", "#/practice", "button"));
  add(wrap, bench);
  const resume = node("section", "resume-panel");
  add(
    resume,
    node("h2", "", "Make this your learning path."),
    routePicker(),
    node("p", "progress-summary", summaryLine()),
  );
  if (current)
    add(
      resume,
      link(
        `Next: ${current.id} · ${current.title}`,
        "#/lesson/" + encodeURIComponent(current.id),
        "text-link",
      ),
    );
  add(wrap, resume);
  return wrap;
}
function productionNotes() {
  const section = node("section", "production-notes");
  add(
    section,
    node("h2", "", "Course notes and resources"),
    node(
      "p",
      "",
      "Lessons use short, consistent language informed by Simplified Technical English, worked examples and retrieval practice. Formal STE conformance is not claimed.",
    ),
    node(
      "p",
      "",
      "All lessons use the locally generated Kokoro af_heart voice. The five pilot videos use paragraph-matched diagrams. Readable transcripts remain available alongside narration.",
    ),
    link(
      "Read the course guide, production notes and sources",
      "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/3ddf84dd02a9f747227f11bb1344c2c19c81bd40/docs/ACADEMY.md",
      "text-link",
    ),
    link(
      "Download all lesson transcripts",
      "course/all-lesson-transcripts.txt",
      "text-link",
    ),
  );
  section.lastElementChild.download = "all-lesson-transcripts.txt";
  return section;
}
function catalogue() {
  const wrap = node("div", "catalogue-page");
  add(
    wrap,
    heading(
      "Your learning path",
      "Start with measurement, then build toward decisions you can explain. The recommended route changes with your choice; every lesson remains open.",
    ),
    routePicker(),
  );
  const recommended = new Set(path().map((x) => x.id));
  for (const module of course.modules) {
    const section = node("section", "course-module");
    const top = node("div", "module-heading");
    add(top, node("span", "module-letter", module.id));
    const copy = node("div");
    add(copy, node("h2", "", module.title), node("p", "", module.description));
    add(top, copy);
    section.append(top);
    const list = node("ol", "lesson-list");
    for (const lesson of course.lessons.filter((x) => x.module === module.id))
      list.append(lessonRow(lesson, recommended.has(lesson.id)));
    add(section, list);
    wrap.append(section);
  }
  add(
    wrap,
    node(
      "aside",
      "scope-note",
      "Software exercises use an isolated demo. Builders complete physical commissioning with competent local supervision. Operators need a verified local handover. Passing quizzes does not certify an installation.",
    ),
  );
  add(wrap, productionNotes());
  return wrap;
}
function glossary() {
  const wrap = node("div", "glossary-page");
  add(
    wrap,
    heading(
      "A small working vocabulary",
      "Plain meanings to come back to when a lesson introduces a new word.",
    ),
  );
  const label = node("label", "", "Find a term");
  label.htmlFor = "glossary-search";
  const input = node("input");
  input.id = "glossary-search";
  input.type = "search";
  input.placeholder = "Try “dryback” or “readback”";
  const count = node("p", "muted");
  count.setAttribute("aria-live", "polite");
  const list = node("dl", "glossary-list");
  function fill() {
    list.replaceChildren();
    const query = input.value.toLocaleLowerCase().trim();
    const terms = (course.glossary || []).filter((x) =>
      (x.term + " " + x.definition).toLocaleLowerCase().includes(query),
    );
    for (const item of terms)
      add(list, node("dt", "", item.term), node("dd", "", item.definition));
    count.textContent = terms.length
      ? `${terms.length} terms`
      : "No matching terms. Try a shorter word.";
  }
  input.addEventListener("input", fill);
  add(wrap, node("div", "search-field"));
  add(wrap.lastChild, label, input);
  add(wrap, count, list);
  fill();
  return wrap;
}
function exportFile() {
  const blob = new Blob([JSON.stringify(progress, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = link("Download progress", url);
  a.download =
    "crop-steering-academy-progress-" +
    new Date().toISOString().slice(0, 10) +
    ".json";
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function rerenderAt(selector) {
  await render(false);
  const target = main.querySelector(selector) || main;
  target.tabIndex = -1;
  target.focus();
}
function progressPage() {
  const wrap = node("div", "progress-page");
  add(
    wrap,
    heading(
      "A record of your learning",
      "Progress belongs to this browser. Keep an exported copy to move it to another browser or restore it later. There is no account or cloud sync.",
    ),
    routePicker(),
  );
  const card = node("section", "progress-overview");
  const completed = path().filter(passed).length;
  add(card, node("h2", "", summaryLine()));
  const meter = node("progress");
  meter.max = path().length || 1;
  meter.value = completed;
  meter.setAttribute("aria-label", "Recommended lessons passed");
  add(
    card,
    meter,
    node(
      "p",
      "muted",
      "A pass records the online knowledge check. Physical skills and installation safety require their own local evidence.",
    ),
  );
  const current = continueLesson();
  if (current)
    add(
      card,
      link(
        "Continue: " + current.title,
        "#/lesson/" + current.id,
        "button primary",
      ),
    );
  wrap.append(card);
  const review = node("section", "review-panel");
  add(review, node("h2", "", "Come back to the idea."));
  const due = reviewDue(progress).map(lessonById).filter(Boolean);
  add(
    review,
    node(
      "p",
      "",
      "After a first pass, revisit the lesson after about a day, then about a week. Explain the idea from memory before reading it again. These are suggested practice intervals.",
    ),
  );
  if (due.length) {
    const list = node("ul", "review-list");
    for (const lesson of due) {
      const item = node("li");
      add(
        item,
        link(lesson.id + " · " + lesson.title, "#/lesson/" + lesson.id),
        button(
          "Record a recall check",
          async () => {
            progress.reviewed[lesson.id] = Date.now();
            save();
            await rerenderAt(".review-panel h2");
          },
          "quiet",
        ),
      );
      list.append(item);
    }
    review.append(list);
  } else
    add(
      review,
      node(
        "p",
        "muted",
        "No recall checks are due yet. You can revisit any lesson whenever you need.",
      ),
    );
  wrap.append(review);
  const records = node("section", "saved-records");
  add(records, node("h2", "", "Passed knowledge checks"));
  const list = node("ul", "record-list");
  for (const lesson of course.lessons.filter(passed)) {
    const item = node("li");
    add(
      item,
      link(lesson.id + " · " + lesson.title, "#/lesson/" + lesson.id),
      node(
        "span",
        "muted",
        `${progress.completed[lesson.id].percent}% · ${new Date(progress.completed[lesson.id].passedAt).toLocaleDateString("en-NZ")}`,
      ),
    );
    list.append(item);
  }
  add(records, list);
  if (!list.children.length)
    add(
      records,
      node("p", "muted", "Your first passed check will appear here."),
    );
  wrap.append(records);
  const tools = node("section", "progress-tools");
  add(tools, node("h2", "", "Keep a copy"));
  const status = node("p", "import-status");
  status.setAttribute("role", "status");
  const file = node("input");
  file.type = "file";
  file.accept = ".json,application/json";
  file.id = "progress-file";
  const fileLabel = node("label", "", "Import a progress file");
  fileLabel.htmlFor = file.id;
  file.addEventListener("change", async () => {
    if (!file.files?.[0]) return;
    try {
      const chosen = file.files[0];
      if (chosen.size > 2000000)
        throw Error("Choose a progress file smaller than 2 MB.");
      const imported = importProgress(await chosen.text(), ids());
      progress = imported;
      save();
      await rerenderAt(".progress-page h1");
      announce("Progress imported. This browser now uses the imported record.");
    } catch (error) {
      status.textContent =
        error.message ||
        "Progress could not be imported. Your current record is unchanged.";
    } finally {
      file.value = "";
    }
  });
  const actions = node("div", "actions");
  add(actions, button("Export progress", exportFile, "primary"));
  add(
    tools,
    node(
      "p",
      "",
      "Import replaces this browser’s learning record. Export the current record first if you want to keep it.",
    ),
    actions,
    fileLabel,
    file,
    status,
  );
  const reset = node("details", "reset-progress");
  add(
    reset,
    node("summary", "", "Reset this browser’s progress"),
    node(
      "p",
      "",
      "This clears lesson positions, quiz passes and review dates here. Export first if you want a copy.",
    ),
  );
  add(
    reset,
    button(
      "Reset progress now",
      async () => {
        progress = importProgress('{"schema":1}', ids());
        save();
        await rerenderAt(".progress-page h1");
        announce("This browser’s progress has been reset.");
      },
      "danger",
    ),
  );
  tools.append(reset);
  wrap.append(tools);
  return wrap;
}
function announce(message) {
  const x = node("p", "screen-reader-status", message);
  x.setAttribute("role", "status");
  document.body.append(x);
  setTimeout(() => x.remove(), 5000);
}
function normalHash() {
  const hash = location.hash.replace(/^#/, "");
  if (!hash || hash === "/") return "/";
  return hash.startsWith("/") ? hash : "/" + hash;
}
async function render(focus = true) {
  if (!course) return;
  const token = ++renderId;
  const route = normalHash();
  const parts = route.split("/").filter(Boolean);
  let screen,
    title,
    section = parts[0] || "home";
  if (section === "lesson") {
    let id;
    try {
      id = decodeURIComponent(parts[1] || "");
    } catch {
      id = "";
    }
    const lesson = lessonById(id);
    if (lesson) {
      progress.lastLesson = lesson.id;
      save();
      screen = await renderLesson({
        lesson,
        progress,
        onSave: save,
        onNavigate: navigate,
      });
      title = lesson.title;
      section = "course";
    } else {
      screen = node("section", "panel");
      add(
        screen,
        node("h1", "", "Lesson not found"),
        node("p", "", "Choose a lesson from the course to continue."),
        link("Open the course", "#/course", "button"),
      );
      title = "Lesson not found";
    }
  } else if (section === "course") {
    screen = catalogue();
    title = "Course";
  } else if (section === "practice") {
    screen = await renderPractice();
    title = "Practice";
  } else if (section === "glossary") {
    screen = glossary();
    title = "Glossary";
  } else if (section === "progress") {
    screen = progressPage();
    title = "Progress";
  } else {
    screen = home();
    title = "Learn crop steering from zero";
    section = "home";
  }
  if (token !== renderId) return;
  for (const media of main.querySelectorAll("audio,video")) media.pause();
  main.replaceChildren(screen);
  document.title = title + " | Crop Steering Academy";
  for (const a of document.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === section) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  if (focus) {
    window.scrollTo(0, 0);
    const h = main.querySelector("h1");
    if (h) {
      h.tabIndex = -1;
      h.focus({ preventScroll: true });
    } else main.focus({ preventScroll: true });
  }
}
async function start() {
  try {
    const response = await fetch("course/course.json?v=20261019r2");
    if (!response.ok) throw Error("Course data returned " + response.status);
    course = await response.json();
    if (!Array.isArray(course.lessons) || !course.lessons.length)
      throw Error("Course lessons are unavailable.");
    course.modules = Array.isArray(course.modules) ? course.modules : [];
    progress = loadProgress(storage, ids());
    save();
    window.addEventListener("hashchange", () => void render().catch(showError));
    await render(false);
  } catch (error) {
    showError(error);
  }
}
function showError(error) {
  const panel = node("section", "panel load-error");
  add(
    panel,
    node("h1", "", "The learning bench could not open."),
    node(
      "p",
      "",
      "Check your connection and reload. Your saved learning record has not been reset.",
    ),
    node(
      "p",
      "muted",
      error.message || "An unexpected loading error occurred.",
    ),
    button("Try again", () => location.reload()),
    link(
      "Read the course workbook",
      "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/tree/3ddf84dd02a9f747227f11bb1344c2c19c81bd40/docs/training/crop-steering-from-zero",
    ),
  );
  main.replaceChildren(panel);
}
void start();
