import { createVisual } from "./visuals.mjs?v=20261020r4";
import { gradeQuiz } from "./practice.mjs";

// One-screen lesson player. A lesson is a sequence of steps:
// intro → each slide (its video section + key points + a check question)
// → practice → one graded question per screen → result.
// The page never scrolls; only the side panel scrolls when its content is long.
// Styling hooks: lp, lp-bar, lp-stage, lp-panel, lp-nav, lp-check, lp-option,
// lp-drawer, quiz-result; state: is-correct, is-incorrect, is-selected.
const el = (tag, className = "", text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
};
const list = (items, ordered = false, className = "") => {
  const node = el(ordered ? "ol" : "ul", className);
  for (const text of items || []) node.append(el("li", "", text));
  return node;
};
function resource(value) {
  try {
    const url = new URL(String(value), document.baseURI);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
function button(text, className = "", onClick) {
  const b = el("button", className, text);
  b.type = "button";
  if (onClick) b.addEventListener("click", onClick);
  return b;
}

// A multiple-choice block. Unlimited tries; the correct answer is revealed after
// two wrong tries so nobody gets stuck. onAnswer(index, correct) runs each time.
function choiceBlock(question, name, { onAnswer = () => {}, initial } = {}) {
  const box = el("fieldset", "lp-check");
  box.append(el("legend", "", question.prompt));
  if (question.safetyCritical) box.append(el("p", "critical-label", "Safety-critical"));
  const feedback = el("p", "lp-feedback");
  feedback.setAttribute("role", "status");
  const rows = [];
  let wrong = 0;
  const show = (oi, announce = true) => {
    const option = question.options[oi];
    rows.forEach((row, i) => {
      row.classList.toggle("is-selected", i === oi);
      row.classList.remove("is-correct", "is-incorrect");
      if (i === oi) row.classList.add(option.correct ? "is-correct" : "is-incorrect");
    });
    if (!option.correct && announce) wrong++;
    const reveal = !option.correct && wrong >= 2
      ? " Correct answer: " + question.options.find((o) => o.correct).text + "."
      : "";
    if (reveal) rows[question.options.findIndex((o) => o.correct)].classList.add("is-correct");
    feedback.className = "lp-feedback " + (option.correct ? "correct" : "incorrect");
    const lead = /^(correct|right|yes|no|not quite|exactly)\b/i.test(option.feedback) ? "" : option.correct ? "Correct. " : "Not quite. ";
    feedback.textContent = lead + option.feedback + reveal;
    onAnswer(oi, option.correct, wrong);
  };
  question.options.forEach((option, oi) => {
    const label = el("label", "lp-option");
    const radio = el("input");
    radio.type = "radio";
    radio.name = name;
    radio.value = String(oi);
    radio.addEventListener("change", () => show(oi));
    label.append(radio, el("span", "", option.text));
    rows.push(label);
  });
  box.append(...rows, feedback);
  if (Number.isInteger(initial) && question.options[initial]) {
    box.querySelectorAll("input")[initial].checked = true;
    show(initial, false);
  }
  return box;
}

export function renderLesson({
  lesson,
  catalogue = [],
  recommended = [],
  progress,
  onSave = () => {},
  onNavigate = () => {},
}) {
  const root = el("article", "lp");
  if (!lesson || !Array.isArray(lesson.slides) || !lesson.slides.length) {
    root.append(el("h1", "", "Lesson unavailable"), el("p", "", "Return to the course and choose another lesson."));
    return root;
  }
  progress = progress && typeof progress === "object" ? progress : {};
  progress.slides ||= {};
  progress.completed ||= {};
  const prefix = `lesson-${String(lesson.id).replace(/[^a-z0-9_-]/gi, "-")}`;
  const questions = Array.isArray(lesson.quiz) ? lesson.quiz : [];
  const hasPractice = Boolean(lesson.practice || lesson.practicalTask);
  const steps = [
    { kind: "intro", label: "Start" },
    ...lesson.slides.map((slide, i) => ({ kind: "slide", slide, i, label: slide.title })),
    ...(hasPractice ? [{ kind: "practice", label: "Practise" }] : []),
    ...questions.map((question, qi) => ({ kind: "quiz", question, qi, label: `Question ${qi + 1}` })),
    { kind: "result", label: "Result" },
  ];
  const saved = progress.slides[lesson.id];
  let index = Number.isInteger(saved) ? Math.max(0, Math.min(saved, steps.length - 1)) : 0;
  if (steps[index].kind === "result") index = 0;
  const checked = Object.create(null); // slide id → passed (correct, or revealed)
  const quizAnswers = Object.create(null); // question id → option index

  const saveStatus = el("p", "lp-save");
  saveStatus.setAttribute("role", "status");
  const persist = () => {
    progress.slides = { ...progress.slides, [lesson.id]: index };
    progress.lastLesson = lesson.id;
    const fail = () => {
      saveStatus.textContent = "Progress could not be saved in this browser. Export it from Progress to keep a copy.";
    };
    try {
      const result = onSave(progress);
      if (result === false) fail();
      else result?.catch?.(fail);
    } catch {
      fail();
    }
  };

  // ---- media (one video for the whole lesson; each slide is a chapter) ----
  const stopMedia = () => root.querySelectorAll("video").forEach((v) => v.pause());
  const go = (target) => {
    stopMedia();
    onNavigate(target);
  };
  const videoSrc = lesson.video?.src && resource(lesson.video.src);
  const chapters = (lesson.video?.chapters || []).filter((c) => Number.isFinite(c.start) && c.start >= 0);
  const useVideo = Boolean(videoSrc) && chapters.length === lesson.slides.length;
  let video, captionLine, sectionEnd = Infinity, autoPause = true;
  const stage = el("section", "lp-stage");
  stage.setAttribute("aria-label", "Lesson video");
  const stageInner = el("div", "lp-stage-inner");
  stage.append(stageInner);
  const sectionStatus = el("p", "lp-section-status");
  sectionStatus.setAttribute("aria-live", "polite");
  if (useVideo) {
    video = el("video", "lp-video");
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;
    video.src = videoSrc;
    video.setAttribute("aria-label", `${lesson.title}: lesson video`);
    captionLine = el("p", "lp-caption");
    const captionSrc = resource(lesson.video.captions?.src || lesson.video.captions || "");
    if (captionSrc) {
      const track = el("track");
      track.kind = "captions";
      track.srclang = "en";
      track.label = "English captions";
      track.src = captionSrc;
      video.append(track);
      track.track.mode = "hidden";
      track.track.addEventListener("cuechange", () => {
        const cues = Array.from(track.track.activeCues || []);
        captionLine.textContent = cues.map((cue) => cue.text).join(" ");
      });
    }
    video.addEventListener("timeupdate", () => {
      if (autoPause && video.currentTime >= sectionEnd - 0.08 && !video.paused) {
        video.pause();
        video.currentTime = Math.max(0, sectionEnd - 0.09);
        sectionStatus.textContent = "Section finished. Answer the check to continue.";
        panelBody.querySelector(".lp-check input")?.focus({ preventScroll: true });
      }
    });
    video.addEventListener("play", () => {
      sectionStatus.textContent = "";
    });
    video.addEventListener("error", () => {
      sectionStatus.textContent = "The video could not load. Read the key points and transcript instead.";
    });
  }
  const mediaBar = el("div", "lp-media-bar");
  const replay = button("↺ Replay section", "lp-chip", () => {
    if (!video || steps[index].kind !== "slide") return;
    video.currentTime = chapters[steps[index].i].start;
    void video.play().catch(() => {});
  });
  const ccToggle = button("CC on", "lp-chip", () => {
    const off = captionLine.hidden = !captionLine.hidden;
    ccToggle.textContent = off ? "CC off" : "CC on";
    ccToggle.setAttribute("aria-pressed", String(!off));
  });
  ccToggle.setAttribute("aria-pressed", "true");
  const speed = el("select", "lp-chip");
  speed.setAttribute("aria-label", "Playback speed");
  for (const rate of [0.75, 1, 1.25, 1.5]) {
    const o = el("option", "", `${rate}×`);
    o.value = String(rate);
    speed.append(o);
  }
  speed.value = "1";
  speed.addEventListener("change", () => {
    if (video) video.playbackRate = video.defaultPlaybackRate = Number(speed.value);
  });
  const pauseLabel = el("label", "lp-chip lp-autopause");
  const pauseBox = el("input");
  pauseBox.type = "checkbox";
  pauseBox.checked = true;
  pauseBox.addEventListener("change", () => (autoPause = pauseBox.checked));
  pauseLabel.append(pauseBox, document.createTextNode(" Pause after each section"));
  if (useVideo) mediaBar.append(replay, ccToggle, speed, pauseLabel);

  // ---- top bar ----
  const bar = el("header", "lp-bar");
  const back = el("a", "lp-back", "←");
  back.href = "#/course";
  back.setAttribute("aria-label", "Back to the course");
  back.addEventListener("click", (e) => {
    if (e.button || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    go("course");
  });
  const titleBox = el("div", "lp-title");
  titleBox.append(el("p", "lp-eyebrow", `Lesson ${lesson.id}`), el("h1", "", lesson.title));
  const menuButton = button("☰", "lp-menu-button");
  menuButton.setAttribute("aria-label", "Lesson menu");
  menuButton.setAttribute("aria-haspopup", "dialog");
  const track = el("ol", "lp-track");
  track.setAttribute("aria-label", "Lesson steps");
  const dots = steps.map((step, si) => {
    const li = el("li");
    const b = button("", "lp-dot", () => goTo(si));
    b.setAttribute("aria-label", `Step ${si + 1}: ${step.label}`);
    b.dataset.kind = step.kind;
    li.append(b);
    track.append(li);
    return b;
  });
  bar.append(back, titleBox, menuButton, track);

  // ---- panel + bottom navigation ----
  const panel = el("section", "lp-panel");
  const panelBody = el("div", "lp-panel-body");
  panel.append(panelBody);
  const nav = el("nav", "lp-nav");
  nav.setAttribute("aria-label", "Step navigation");
  const prevButton = button("Back", "lp-prev", () => goTo(index - 1));
  const counter = el("span", "lp-counter");
  const nextButton = button("Continue", "lp-next primary", () => advance());
  nav.append(prevButton, counter, nextButton);

  // ---- menu drawer ----
  const drawer = el("dialog", "lp-drawer");
  drawer.setAttribute("aria-label", "Lesson menu");
  const buildDrawer = () => {
    const close = button("Close", "lp-drawer-close", () => drawer.close());
    const jump = el("ol", "lp-jump");
    steps.forEach((step, si) => {
      const li = el("li");
      const b = button(step.kind === "slide" ? `${step.i + 1}. ${step.label}` : step.label, si === index ? "is-current" : "", () => {
        drawer.close();
        goTo(si);
      });
      li.append(b);
      jump.append(li);
    });
    const outcomes = el("section");
    outcomes.append(el("h2", "", "You will be able to"), list(lesson.outcomes));
    const lessons = el("section");
    const all = catalogue.length ? catalogue : [lesson];
    const onRoute = recommended.some((x) => x.id === lesson.id);
    const sequence = onRoute ? recommended : all;
    const at = sequence.findIndex((x) => x.id === lesson.id);
    const adjacent = el("div", "lp-adjacent");
    for (const [offset, label] of [[-1, "Previous lesson"], [1, "Next lesson"]]) {
      const t = sequence[at + offset];
      if (t) adjacent.append(button(`${label}: ${t.id} ${t.title}`, "", () => go(t.id)));
    }
    const pick = el("select");
    pick.setAttribute("aria-label", "Jump to any lesson");
    all.forEach((item) => {
      const o = el("option", "", `${item.id} · ${item.title}`);
      o.value = item.id;
      pick.append(o);
    });
    pick.value = lesson.id;
    pick.addEventListener("change", () => go(pick.value));
    lessons.append(el("h2", "", "Other lessons"), adjacent, pick, button("Watch the longer course videos", "", () => go("watch")));
    const tools = el("section");
    const transcript = el("details", "lp-transcript");
    transcript.append(el("summary", "", "Read the full transcript"));
    lesson.slides.forEach((s, i) => transcript.append(el("h3", "", `${i + 1}. ${s.title}`), el("p", "", s.narration)));
    tools.append(el("h2", "", "Read, save or print"), transcript, button("Download transcript", "", downloadTranscript), button("Print lesson notes", "", () => window.print()));
    if (lesson.sources?.length) {
      const sources = el("ul", "lesson-sources");
      for (const source of lesson.sources) {
        const url = resource(source.url);
        if (!url) continue;
        const a = el("a", "", source.title || source.url);
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const li = el("li");
        li.append(a);
        sources.append(li);
      }
      tools.append(el("h3", "", "Sources"), sources);
    }
    drawer.replaceChildren(close, el("h2", "", "Jump to a step"), jump, outcomes, lessons, tools);
  };
  menuButton.addEventListener("click", () => {
    buildDrawer();
    drawer.showModal();
  });
  drawer.addEventListener("click", (e) => {
    if (e.target === drawer) drawer.close();
  });

  function downloadTranscript() {
    const lines = [lesson.id + " · " + lesson.title, lesson.summary, ""];
    lesson.slides.forEach((s, i) => {
      lines.push(`${i + 1}. ${s.title}`, "", s.narration || "", "");
      if (s.workedExample) lines.push("Worked example: " + s.workedExample.prompt, ...s.workedExample.steps, s.workedExample.answer, "");
    });
    if (lesson.practice) lines.push("Practice", lesson.practice.prompt, "");
    if (lesson.sources) lines.push("Sources", ...lesson.sources.map((s) => s.title + ": " + s.url));
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }));
    const a = el("a");
    a.href = url;
    a.download = String(lesson.id).replace(/[^a-z0-9_-]/gi, "-") + "-transcript.txt";
    root.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  // Printed notes: everything in reading order (hidden on screen).
  const printNotes = el("section", "lp-print");
  printNotes.append(el("h2", "", `${lesson.id} · ${lesson.title}`), el("p", "", lesson.summary));
  lesson.slides.forEach((s, i) => {
    printNotes.append(el("h3", "", `${i + 1}. ${s.title}`), list(s.body), el("p", "", s.narration));
    if (s.check) printNotes.append(el("p", "", "Check: " + s.check.prompt));
  });

  // ---- step rendering ----
  function stageFor(step) {
    root.classList.toggle("lp-no-stage", step.kind !== "slide" && step.kind !== "intro");
    if (step.kind !== "slide" && step.kind !== "intro") {
      video?.pause();
      return;
    }
    if (useVideo) {
      if (!stageInner.contains(video)) stageInner.replaceChildren(video, captionLine, mediaBar, sectionStatus);
      const i = step.kind === "slide" ? step.i : 0;
      const start = chapters[i].start;
      sectionEnd = step.kind === "slide" && chapters[i + 1] ? chapters[i + 1].start : Infinity;
      const playing = !video.paused;
      const seek = () => {
        if (Math.abs(video.currentTime - start) > 0.25) video.currentTime = start;
      };
      if (video.readyState >= 1) seek();
      else video.addEventListener("loadedmetadata", seek, { once: true });
      sectionStatus.textContent = "";
      captionLine.textContent = "";
      if (step.kind === "intro") video.pause();
      else if (playing) void video.play().catch(() => {});
    } else {
      const slide = step.kind === "slide" ? step.slide : lesson.slides[0];
      stageInner.replaceChildren(createVisual(slide.visual, { lessonId: lesson.id, slideId: slide.id }));
    }
  }

  function introPanel() {
    const box = el("div", "lp-intro");
    box.append(el("p", "lp-lead", lesson.summary), el("h2", "", "By the end you will be able to"), list(lesson.outcomes, false, "lp-outcomes"));
    if (lesson.prerequisites?.length) {
      const before = el("p", "lp-muted", "Builds on: ");
      lesson.prerequisites.forEach((id, i) => {
        if (i) before.append(document.createTextNode(", "));
        const a = el("a", "", id);
        a.href = `#/lesson/${encodeURIComponent(id)}`;
        a.addEventListener("click", (e) => {
          e.preventDefault();
          go(id);
        });
        before.append(a);
      });
      box.append(before);
    }
    const parts = lesson.slides.length;
    box.append(el("p", "lp-muted", `${parts} short sections, each with a quick check, then ${questions.length} questions to finish. Your place is saved in this browser.`));
    if (progress.completed[lesson.id]) box.append(el("p", "lp-done", `You passed this lesson with ${progress.completed[lesson.id].percent}%. Use it for review any time.`));
    return box;
  }

  function slidePanel(step) {
    const { slide, i } = step;
    const box = el("div", "lp-slide");
    const heading = el("h2", "", slide.title);
    heading.tabIndex = -1;
    box.append(el("p", "lp-eyebrow", `Section ${i + 1} of ${lesson.slides.length}`), heading, list(slide.body, false, "lp-points"));
    if (slide.workedExample) {
      const ex = el("details", "lp-example");
      ex.open = true;
      ex.append(el("summary", "", "Worked example"), el("p", "", slide.workedExample.prompt), list(slide.workedExample.steps, true), el("p", "lp-answer", slide.workedExample.answer));
      box.append(ex);
    }
    if (slide.check) {
      box.append(
        choiceBlock(slide.check, `${prefix}-check-${i}`, {
          initial: checked[slide.id]?.choice,
          onAnswer: (choice, correct, wrong) => {
            const passed = correct || wrong >= 2 || checked[slide.id]?.passed;
            checked[slide.id] = { choice, passed };
            updateNav();
          },
        }),
      );
    }
    const t = el("details", "lp-transcript");
    t.append(el("summary", "", "Read what the narrator says"), el("p", "", slide.narration));
    box.append(t);
    return box;
  }

  function practicePanel() {
    const box = el("div", "lp-practice");
    box.append(el("p", "lp-eyebrow", "Your turn"), el("h2", "", "Practise before the questions"));
    if (lesson.practice) {
      box.append(el("p", "", lesson.practice.prompt));
      const notes = el("textarea", "lp-notes");
      notes.setAttribute("aria-label", "Your working (not saved)");
      notes.placeholder = "Work it out here (not saved)…";
      box.append(notes);
      if (lesson.practice.hints?.length) {
        const h = el("details", "lp-example");
        h.append(el("summary", "", "Need a hint?"), list(lesson.practice.hints));
        box.append(h);
      }
      if (lesson.practice.success) {
        const s = el("details", "lp-example");
        s.append(el("summary", "", "Compare your answer"), el("p", "", lesson.practice.success));
        box.append(s);
      }
      if (["calculation", "dryback", "flow", "threshold"].includes(lesson.practice.kind)) {
        const a = el("a", "", "Open the practice calculators ↗");
        a.href = "#/practice";
        a.target = "_blank";
        box.append(a);
      }
    }
    if (lesson.practicalTask) {
      const task = el("section", "practical-task");
      task.append(el("h3", "", "Practical task"), list(lesson.practicalTask.instructions, true));
      task.append(el("p", "lp-muted", lesson.practicalTask.requiresLocalSupervision
        ? "Do physical work only with competent local supervision and the installation’s approved procedure."
        : "Do this on paper or in the demo. Nothing checks it automatically."));
      box.append(task);
    }
    return box;
  }

  function quizPanel(step) {
    const { question, qi } = step;
    const box = el("div", "lp-quiz");
    box.append(el("p", "lp-eyebrow", `Knowledge check · question ${qi + 1} of ${questions.length}`));
    const block = el("fieldset", "lp-check quiz-question");
    block.append(el("legend", "", question.prompt));
    if (question.safetyCritical) block.append(el("p", "critical-label", "Safety-critical: must be correct to pass"));
    question.options.forEach((option, oi) => {
      const label = el("label", "lp-option");
      const radio = el("input");
      radio.type = "radio";
      radio.name = `${prefix}-question-${qi}`;
      radio.checked = quizAnswers[question.id] === oi;
      radio.addEventListener("change", () => {
        quizAnswers[question.id] = oi;
        block.querySelectorAll(".lp-option").forEach((row) => row.classList.toggle("is-selected", row === label));
        updateNav();
      });
      if (radio.checked) label.classList.add("is-selected");
      label.append(radio, el("span", "", option.text));
      block.append(label);
    });
    box.append(block, el("p", "lp-muted", "Feedback for every answer appears after the last question."));
    return box;
  }

  function resultPanel() {
    const box = el("div", "lp-result");
    const grade = gradeQuiz(questions, quizAnswers);
    if (grade.passed) {
      progress.completed = { ...progress.completed, [lesson.id]: { percent: grade.percent, passedAt: Date.now() } };
    } else {
      const completed = { ...progress.completed };
      delete completed[lesson.id];
      progress.completed = completed;
    }
    const result = el("p", `quiz-result ${grade.passed ? "correct" : "incorrect"}`);
    result.setAttribute("role", "status");
    const critical = grade.feedback.some((x) => x.critical && !x.correct);
    result.textContent = grade.passed
      ? `Passed: ${grade.correct} of ${grade.total} correct (${grade.percent}%). Lesson complete in this browser.`
      : `${grade.correct} of ${grade.total} correct (${grade.percent}%). ${critical ? "A safety-critical answer needs fixing. " : ""}You need 80% and every safety-critical answer right. Read the feedback and try again.`;
    box.append(el("p", "lp-eyebrow", "Result"), el("h2", "", grade.passed ? "Well done" : "Nearly there"), result);
    const review = el("ol", "lp-review");
    grade.feedback.forEach((item, qi) => {
      const li = el("li", item.correct ? "is-correct" : "is-incorrect");
      li.append(el("strong", "", questions[qi].prompt), el("p", "", (item.correct ? "Correct. " : "Review: ") + item.message));
      review.append(li);
    });
    box.append(review);
    if (!grade.passed) box.append(button("Try the questions again", "primary", () => {
      for (const k in quizAnswers) delete quizAnswers[k];
      goTo(steps.findIndex((s) => s.kind === "quiz"));
    }));
    if (lesson.practicalTask?.requiresLocalSupervision)
      box.append(el("p", "lp-muted", "Passing records online practice only. The practical task still needs local, supervised checks."));
    return box;
  }

  function canAdvance() {
    const step = steps[index];
    if (step.kind === "slide" && step.slide.check) return Boolean(checked[step.slide.id]?.passed);
    if (step.kind === "quiz") return Number.isInteger(quizAnswers[step.question.id]);
    return index < steps.length - 1 || false;
  }
  function nextLesson() {
    const sequence = recommended.some((x) => x.id === lesson.id) ? recommended : catalogue;
    const at = sequence.findIndex((x) => x.id === lesson.id);
    return sequence[at + 1];
  }
  function updateNav() {
    const step = steps[index];
    prevButton.disabled = index === 0;
    counter.textContent = `${index + 1} / ${steps.length}`;
    const last = step.kind === "result";
    const upcoming = steps[index + 1];
    nextButton.disabled = !last && !canAdvance();
    nextButton.textContent = last
      ? (nextLesson() && progress.completed[lesson.id] ? `Next lesson: ${nextLesson().id}` : "Back to course")
      : step.kind === "intro" ? "Start lesson"
      : upcoming?.kind === "result" ? "See my result"
      : step.kind === "slide" && step.slide.check && !canAdvance() ? "Answer to continue"
      : "Continue";
    dots.forEach((d, si) => {
      d.classList.toggle("is-current", si === index);
      d.classList.toggle("is-done", si < index);
      if (si === index) d.setAttribute("aria-current", "step");
      else d.removeAttribute("aria-current");
    });
  }
  function advance() {
    if (steps[index].kind === "result") {
      const n = nextLesson();
      go(n && progress.completed[lesson.id] ? n.id : "course");
      return;
    }
    if (!canAdvance()) return;
    // Starting the lesson is a user gesture: begin playback of section 1.
    const starting = steps[index].kind === "intro";
    goTo(index + 1);
    if (starting && video) void video.play().catch(() => {});
  }
  function goTo(value, focus = true) {
    index = Math.max(0, Math.min(value, steps.length - 1));
    const step = steps[index];
    stageFor(step);
    const content = step.kind === "intro" ? introPanel()
      : step.kind === "slide" ? slidePanel(step)
      : step.kind === "practice" ? practicePanel()
      : step.kind === "quiz" ? quizPanel(step)
      : resultPanel();
    panelBody.replaceChildren(content);
    panelBody.scrollTop = 0;
    persist();
    updateNav();
    if (focus) content.querySelector("h2")?.focus?.({ preventScroll: true });
  }

  root.addEventListener("keydown", (e) => {
    if (e.target.closest("input,select,textarea,video,dialog")) return;
    if (e.key === "ArrowRight" && !nextButton.disabled) advance();
    if (e.key === "ArrowLeft" && index > 0) goTo(index - 1);
  });

  const body = el("div", "lp-body");
  body.append(stage, panel);
  root.append(bar, body, nav, saveStatus, drawer, printNotes);
  goTo(index, false);
  buildDrawer();
  return root;
}
