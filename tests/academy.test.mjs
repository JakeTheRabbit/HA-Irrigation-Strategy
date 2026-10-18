import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  calculateDryback,
  calculateFlow,
  planningPreview,
  gradeQuiz,
} from "../www/learn/practice.mjs";
import {
  emptyProgress,
  loadProgress,
  saveProgress,
  importProgress,
  routeLessons,
  nextLesson,
  reviewDue,
} from "../www/learn/state.mjs";

test("published catalogue preserves the complete course, alternative hosts and binding paths", () => {
  const course = JSON.parse(
    readFileSync(
      new URL("../www/learn/course/course.json", import.meta.url),
      "utf8",
    ),
  );
  const ids = course.lessons.map((l) => l.id);
  assert.equal(
    ids.join(" "),
    "A1 A2 A3 A4 A5 A6 B1 B2 B3 B4 C1 C2a C2b C3 C4 C5 C6 C7 D1 D2 D3 D4 D5 D6",
  );
  assert.equal(routeLessons(course.lessons, "operator").length, 17);
  assert.equal(routeLessons(course.lessons, "builder-pi").length, 23);
  assert.equal(routeLessons(course.lessons, "builder-x86").length, 23);
  assert.equal(course.lessons.filter((l) => l.video).length, 24);
  assert.equal(
    course.lessons.flatMap((l) => l.slides).length,
    153,
  );
  for (const lesson of course.lessons) {
    assert.ok(lesson.sources.length > 0);
    assert.equal(
      new Set(lesson.slides.map((s) => s.id)).size,
      lesson.slides.length,
    );
    for (const id of lesson.prerequisites)
      assert.ok(ids.indexOf(id) < ids.indexOf(lesson.id));
    for (const s of lesson.slides) {
      assert.ok(s.narration.length > 40);
      assert.ok(s.body.length);
      assert.ok(s.visual.type);
      assert.match(s.id, /^[A-Za-z0-9-]+$/);
    }
    for (const q of lesson.quiz) {
      assert.equal(q.options.filter((o) => o.correct).length, 1);
      assert.ok(q.options.every((o) => o.feedback.length > 15));
    }
  }
});

test("dryback distinguishes percentage points and relative percentage", () => {
  assert.deepEqual(calculateDryback(60, 45), { points: 15, relative: 25 });
  assert.deepEqual(calculateDryback(50, 40), { points: 10, relative: 20 });
  assert.throws(() => calculateDryback(0, 0));
  assert.throws(() => calculateDryback(45, 60));
});
test("one timed delivery uses all drippers and all plants without claiming uptake", () => {
  const x = calculateFlow({
    litersPerHour: 4,
    drippersPerPlant: 2,
    seconds: 30,
    plants: 42,
  });
  assert.ok(Math.abs(x.perPlant - 1 / 15) < 1e-10);
  assert.ok(Math.abs(x.zone - 2.8) < 1e-10);
  assert.equal(x.basis, "Runtime estimate; not measured plant uptake.");
  assert.throws(() =>
    calculateFlow({
      litersPerHour: -1,
      drippersPerPlant: 2,
      seconds: 30,
      plants: 42,
    }),
  );
  assert.throws(
    () =>
      calculateFlow({
        litersPerHour: 1e308,
        drippersPerPlant: 2,
        seconds: 30,
        plants: 42,
      }),
    /too large/i,
  );
});
test("moving the protective threshold cannot mutate measured observations", () => {
  const actual = Object.freeze([
    Object.freeze({ hour: 0, vwc: 60, ec: 3 }),
    Object.freeze({ hour: 12, vwc: 45, ec: 4 }),
  ]);
  const a = planningPreview(35, actual),
    b = planningPreview(39, actual);
  assert.equal(a.actual, b.actual);
  assert.equal(b.actual, actual);
  assert.equal(b.floor, 39);
  assert.equal(actual[1].vwc, 45);
  assert.throws(() => planningPreview(101, actual));
});
test("a high score cannot pass a wrong critical isolation answer", () => {
  const quiz = Array.from({ length: 5 }, (_, i) => ({
    id: "q" + i,
    safetyCritical: i === 0,
    options: [
      { text: "yes", correct: true, feedback: "Correct." },
      { text: "no", correct: false, feedback: "Use physical isolation." },
    ],
  }));
  const score = gradeQuiz(quiz, { q0: 1, q1: 0, q2: 0, q3: 0, q4: 0 });
  assert.equal(score.percent, 80);
  assert.equal(score.passed, false);
  assert.equal(score.feedback[0].message, "Use physical isolation.");
  assert.equal(
    gradeQuiz(quiz, Object.fromEntries(quiz.map((q) => [q.id, 0]))).passed,
    true,
  );
});
test("learner routes include one host alternative and operators can study without installation", () => {
  const lessons = [
    { id: "A1", route: "everyone" },
    { id: "C1", route: "everyone" },
    { id: "C2a", route: "pi" },
    { id: "C2b", route: "x86" },
    { id: "C3", route: "builder" },
    { id: "D1", route: "everyone" },
  ];
  assert.deepEqual(
    routeLessons(lessons, "builder-pi").map((x) => x.id),
    ["A1", "C1", "C2a", "C3", "D1"],
  );
  assert.deepEqual(
    routeLessons(lessons, "builder-x86").map((x) => x.id),
    ["A1", "C1", "C2b", "C3", "D1"],
  );
  assert.deepEqual(
    routeLessons(lessons, "operator").map((x) => x.id),
    ["A1", "C1", "D1"],
  );
  assert.equal(
    nextLesson(lessons, {
      ...emptyProgress(),
      completed: { A1: { percent: 100, passedAt: 1 } },
    }).id,
    "C1",
  );
});
test("storage denial and corrupt input leave the course readable", () => {
  const storage = {
    getItem() {
      throw Error("blocked");
    },
    setItem() {
      throw Error("blocked");
    },
  };
  assert.deepEqual(loadProgress(storage, ["A1"]), emptyProgress());
  assert.equal(saveProgress(storage, emptyProgress()), false);
  assert.throws(() => importProgress("{broken", ["A1"]), /valid|format|JSON/i);
  assert.throws(
    () => importProgress(JSON.stringify({ schema: 99 }), ["A1"]),
    /version|format/i,
  );
});
test("imports ignore unknown IDs and unsafe object properties", () => {
  const x = importProgress(
    '{"schema":1,"route":"builder-x86","completed":{"A1":{"percent":100,"passedAt":123},"bogus":{"percent":100,"passedAt":1},"__proto__":{"polluted":true}},"lastLesson":"<script>"}',
    ["A1"],
  );
  assert.deepEqual(Object.keys(x.completed), ["A1"]);
  assert.equal(x.lastLesson, null);
  assert.equal({}.polluted, undefined);
  assert.equal(x.route, "builder-x86");
});
test("review prompts use elapsed practice time, not video watch time", () => {
  const day = 86400000,
    p = emptyProgress();
  p.completed.A1 = { percent: 100, passedAt: day };
  assert.deepEqual(reviewDue(p, day + 100), []);
  assert.deepEqual(reviewDue(p, 3 * day), ["A1"]);
  p.reviewed.A1 = 3 * day;
  assert.deepEqual(reviewDue(p, 3 * day + 10), []);
});
