const KEY = "crop-steering-academy:progress:v1";
const ROUTES = new Set(["operator", "builder-pi", "builder-x86"]);
const DAY = 86400000;
export function emptyProgress() {
  return {
    schema: 1,
    route: "operator",
    completed: {},
    slides: {},
    reviewed: {},
    lastLesson: null,
  };
}
export function importProgress(text, lessonIds) {
  if (typeof text !== "string" || text.length > 2000000)
    throw Error("Choose a valid progress JSON file smaller than 2 MB.");
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    throw Error("The file does not contain valid JSON.");
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw) || raw.schema !== 1)
    throw Error("This progress file has an unsupported version or format.");
  const ids = new Set(lessonIds),
    p = emptyProgress();
  p.route = ROUTES.has(raw.route) ? raw.route : p.route;
  if (raw.completed && typeof raw.completed === "object")
    for (const [id, v] of Object.entries(raw.completed)) {
      if (
        ids.has(id) &&
        v &&
        Number.isFinite(v.percent) &&
        v.percent >= 80 &&
        v.percent <= 100 &&
        Number.isFinite(v.passedAt) &&
        v.passedAt > 0
      )
        p.completed[id] = { percent: v.percent, passedAt: v.passedAt };
    }
  if (raw.slides && typeof raw.slides === "object")
    for (const [id, v] of Object.entries(raw.slides))
      if (ids.has(id) && Number.isInteger(v) && v >= 0 && v < 200)
        p.slides[id] = v;
  if (raw.reviewed && typeof raw.reviewed === "object")
    for (const [id, v] of Object.entries(raw.reviewed))
      if (ids.has(id) && Number.isFinite(v) && v > 0) p.reviewed[id] = v;
  p.lastLesson = ids.has(raw.lastLesson) ? raw.lastLesson : null;
  return p;
}
export function loadProgress(storage, ids) {
  try {
    const value = storage.getItem(KEY);
    return value ? importProgress(value, ids) : emptyProgress();
  } catch {
    return emptyProgress();
  }
}
export function saveProgress(storage, progress) {
  try {
    storage.setItem(KEY, JSON.stringify(progress));
    return true;
  } catch {
    return false;
  }
}
export function routeLessons(lessons, route = "operator") {
  return lessons.filter(
    (l) =>
      !l.route ||
      l.route === "everyone" ||
      l.route === "operator" ||
      (l.route === "builder" && route !== "operator") ||
      (l.route === "pi" && route === "builder-pi") ||
      (l.route === "x86" && route === "builder-x86"),
  );
}
export function nextLesson(lessons, progress) {
  const path = routeLessons(lessons, progress.route);
  return path.find((l) => !progress.completed[l.id]) || path.at(-1) || null;
}
export function reviewDue(progress, now = Date.now()) {
  return Object.entries(progress.completed)
    .filter(([id, x]) => {
      const last = progress.reviewed[id] || x.passedAt;
      return now - last >= (progress.reviewed[id] ? 6 * DAY : DAY);
    })
    .map(([id]) => id);
}
