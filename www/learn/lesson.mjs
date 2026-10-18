import { createVisual } from "./visuals.mjs?v=20261019r3";
import { gradeQuiz } from "./practice.mjs";

// Styling hooks: lesson-player/header/section/slide, slide-heading/navigation/counter,
// lesson-media/transcript, media-controls/captions, worked-example, lesson-practice,
// lesson-quiz, quiz-question/options/option/feedback/result, practical-task/sources.
// State hooks: is-selected, is-correct, is-incorrect; feedback: correct, incorrect.
const el = (tag, className = "", text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
};
const list = (items, ordered = false) => {
  const node = el(ordered ? "ol" : "ul");
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
function disclosure(title, content, className = "") {
  const details = el("details", className);
  details.append(el("summary", "", title));
  details.append(typeof content === "string" ? el("p", "", content) : content);
  return details;
}

/** Render one lesson. Mutates this progress object and calls onSave(progress).
 * onNavigate receives 'course', 'practice', or a lesson ID. No live-system calls.
 */
export function renderLesson({
  lesson,
  catalogue = [],
  recommended = [],
  progress,
  onSave = () => {},
  onNavigate = () => {},
}) {
  const root = el("article", "lesson-player");
  if (!lesson || !Array.isArray(lesson.slides) || !lesson.slides.length) {
    root.append(
      el("h1", "", "Lesson unavailable"),
      el("p", "", "Return to the course and choose another lesson."),
    );
    return root;
  }
  progress = progress && typeof progress === "object" ? progress : {};
  progress.slides ||= {};
  progress.completed ||= {};
  const prefix = `lesson-${String(lesson.id).replace(/[^a-z0-9_-]/gi, "-")}`;
  const savedIndex = progress.slides[lesson.id];
  let index = Number.isInteger(savedIndex)
    ? Math.max(0, Math.min(savedIndex, lesson.slides.length - 1))
    : 0;
  let speed = 1;
  let currentMedia;
  let captionsEnabled = true;
  const voice = lesson.video?.voice || "Kokoro af_heart";
  const stopCurrentMedia = () => {
    if (!currentMedia) return;
    currentMedia.pause();
    currentMedia.removeAttribute("src");
    currentMedia
      .querySelectorAll("track")
      .forEach((track) => track.removeAttribute("src"));
    currentMedia.load();
    currentMedia = null;
  };
  const saveStatus = el("p", "muted save-status");
  saveStatus.setAttribute("role", "status");
  const persist = () => {
    progress.slides = { ...progress.slides, [lesson.id]: index };
    progress.lastLesson = lesson.id;
    try {
      const result = onSave(progress);
      if (result === false)
        saveStatus.textContent =
          "Progress is available in this session, but browser storage could not save it. Use the course export option to keep a copy.";
      else if (result?.catch)
        result.catch(() => {
          saveStatus.textContent =
            "Browser progress could not be saved. Use the course export option to keep a copy.";
        });
    } catch {
      saveStatus.textContent =
        "Browser progress could not be saved. Use the course export option to keep a copy.";
    }
  };
  const navigateLink = (text, target) => {
    const a = el("a", "button", text);
    a.href =
      target === "course" || target === "practice" || target === "watch"
        ? `#/${target}`
        : `#/lesson/${encodeURIComponent(target)}`;
    a.addEventListener("click", (event) => {
      if (
        event.button !== 0 ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
      stopCurrentMedia();
      root.querySelectorAll("video").forEach((video) => video.pause());
      onNavigate(target);
    });
    return a;
  };
  const lessonNavigation = (position) => {
    const nav = el("nav", "lesson-navigation panel");
    nav.setAttribute("aria-label", `${position} lesson navigation`);
    const all = catalogue.length ? catalogue : [lesson];
    const onRoute = recommended.some(item => item.id === lesson.id);
    const sequence = onRoute ? recommended : all;
    const at = sequence.findIndex(item => item.id === lesson.id);
    nav.append(el("p", "muted lesson-sequence", onRoute ? "Continue along your recommended route" : "Continue in course order"));
    const adjacent = el("div", "lesson-adjacent");
    for (const [offset, label] of [[-1, "Previous lesson"], [1, "Next lesson"]]) {
      const target = sequence[at + offset];
      if (target) adjacent.append(navigateLink(`${label}: ${target.id} · ${target.title}`, target.id));
      else {
        const disabled = el("button", "", label);
        disabled.type = "button";
        disabled.disabled = true;
        adjacent.append(disabled);
      }
    }
    const label = el("label", "lesson-jump", "Jump to any lesson ");
    const select = el("select");
    select.setAttribute("aria-label", `${position}: jump to any lesson`);
    all.forEach(item => {
      const option = el("option", "", `${item.id} · ${item.title}`);
      option.value = item.id;
      select.append(option);
    });
    select.value = lesson.id;
    select.addEventListener("change", () => {
      stopCurrentMedia();
      root.querySelectorAll("video").forEach(video => video.pause());
      onNavigate(select.value);
    });
    label.append(select);
    nav.append(adjacent, label, navigateLink("Watch the grouped videos", "watch"));
    return nav;
  };
  const header = el("header", "lesson-header");
  header.append(
    navigateLink("Back to course", "course"),
    el("p", "eyebrow", `${lesson.module || ""} · ${lesson.id}`),
    el("h1", "", lesson.title),
    el("p", "", lesson.summary),
  );
  const outcomes = el("section", "lesson-section");
  outcomes.append(
    el("h2", "", "What you will practise"),
    list(lesson.outcomes),
  );
  if (lesson.prerequisites?.length) {
    const before = el("p", "lesson-prerequisites", "Useful earlier lessons: ");
    lesson.prerequisites.forEach((id, i) => {
      if (i) before.append(document.createTextNode(" · "));
      before.append(navigateLink(id, id));
    });
    outcomes.append(before);
  }
  const tools = el("div", "lesson-tools");
  const download = el("button", "", "Download transcript");
  download.type = "button";
  download.addEventListener("click", () => {
    const lines = [
      lesson.id + " · " + lesson.title,
      lesson.summary,
      "Synthetic narration: " + voice,
      "",
    ];
    lesson.slides.forEach((slide, i) => {
      lines.push(
        String(i + 1) + ". " + slide.title,
        "",
        slide.narration || "",
        "",
      );
      if (slide.visual?.caption) lines.push("Diagram: " + slide.visual.caption);
      if (slide.visual?.labels?.length)
        lines.push("Diagram labels: " + slide.visual.labels.join("; "));
      if (slide.workedExample)
        lines.push(
          "Worked example: " + slide.workedExample.prompt,
          ...slide.workedExample.steps,
          slide.workedExample.answer,
        );
      lines.push("");
    });
    if (lesson.practice) lines.push("Practice", lesson.practice.prompt, "");
    if (lesson.practicalTask)
      lines.push(
        "Practical task",
        ...lesson.practicalTask.instructions,
        "A knowledge quiz does not verify a practical task.",
        "",
      );
    if (lesson.sources)
      lines.push(
        "Sources",
        ...lesson.sources.map((source) => source.title + ": " + source.url),
      );
    const url = URL.createObjectURL(
      new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" }),
    );
    const link = el("a");
    link.href = url;
    link.download =
      String(lesson.id).replace(/[^a-z0-9_-]/gi, "-") + "-transcript.txt";
    root.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  });
  const print = el("button", "", "Print lesson notes");
  print.type = "button";
  print.addEventListener("click", () => {
    const states = Array.from(root.querySelectorAll("details")).map((node) => [
      node,
      node.open,
    ]);
    states.forEach(([node]) => {
      node.open = true;
    });
    const restore = () =>
      states.forEach(([node, open]) => {
        node.open = open;
      });
    window.addEventListener("afterprint", restore, { once: true });
    try {
      window.print();
    } catch {
      window.removeEventListener("afterprint", restore);
      restore();
    }
  });
  tools.append(download, print);
  header.append(
    tools,
    el(
      "p",
      "muted",
      "Synthetic narration: " +
        voice +
        ". Print includes the current slide, full transcript and exercises.",
    ),
    outcomes,
  );
  root.append(header, lessonNavigation("Top"), saveStatus);

  if (lesson.video?.src) {
    const source = resource(lesson.video.src);
    if (source) {
      const area = el("section", "lesson-media panel");
      area.append(el("h2", "", "Watch this lesson"));
      const video = el("video");
      video.controls = true;
      video.preload = "metadata";
      video.playsInline = true;
      video.src = source;
      video.setAttribute("aria-label", `${lesson.title}: lesson video`);
      const captionSource = resource(
        lesson.video.captions?.src || lesson.video.captions || "",
      );
      const captionArea = el("div");
      if (lesson.video.captions && captionSource) {
        const track = el("track");
        track.kind = "captions";
        track.srclang = "en";
        track.label = "English captions";
        track.src = captionSource;
        video.append(track);
        const toggle = el("input");
        toggle.type = "checkbox";
        toggle.checked = true;
        const label = el("label");
        label.append(toggle, document.createTextNode(" Show captions below video"));
        const captions = el("p", "media-captions pilot-captions",
          "Captions appear here during narration. The full transcript is below.");
        const textTrack = track.track;
        const updateCaptions = () => {
          captions.hidden = !toggle.checked || textTrack.mode === "showing";
          const cues = Array.from(textTrack.activeCues || []);
          captions.textContent = cues.length
            ? cues.map(cue => cue.text).join(" ")
            : "Narration paused or between caption cues. Read the transcript below at any time.";
        };
        // Keep cues loaded without drawing them over the teaching diagram.
        textTrack.mode = "hidden";
        textTrack.addEventListener("cuechange", updateCaptions);
        video.textTracks.addEventListener("change", updateCaptions);
        toggle.addEventListener("change", () => {
          textTrack.mode = "hidden";
          updateCaptions();
        });
        track.addEventListener("error", () => {
          captions.textContent = "Timed captions could not load. Read the complete transcript below.";
        });
        captionArea.append(label, captions);
      }
      const unavailable = el("p", "muted");
      unavailable.setAttribute("role", "status");
      video.addEventListener("error", () => {
        unavailable.textContent =
          "The video could not load. Continue with the lesson slides and text below.";
      });
      video.addEventListener("play", () => currentMedia?.pause());
      const chapters = (lesson.video.chapters || []).filter(chapter =>
        Number.isFinite(chapter.start) && chapter.start >= 0);
      const chapterControls = el("nav", "video-chapters");
      chapterControls.setAttribute("aria-label", "Video sections");
      if (chapters.length) {
        const previousSection = el("button", "", "Previous section");
        const nextSection = el("button", "", "Next section");
        previousSection.type = nextSection.type = "button";
        const sectionLabel = el("label", "chapter-jump", "Choose video section ");
        const sectionSelect = el("select");
        sectionSelect.setAttribute("aria-label", "Choose video section");
        chapters.forEach((chapter, i) => {
          const option = el("option", "", `${i + 1}. ${chapter.title}`);
          option.value = String(i);
          sectionSelect.append(option);
        });
        let currentSection = 0;
        let pendingSeek = null;
        const syncSection = () => {
          currentSection = Math.max(0, chapters.findLastIndex(chapter => video.currentTime >= chapter.start));
          sectionSelect.value = String(currentSection);
          previousSection.disabled = currentSection === 0;
          nextSection.disabled = currentSection === chapters.length - 1;
        };
        const seekSection = value => {
          const at = Math.max(0, Math.min(value, chapters.length - 1));
          pendingSeek = chapters[at].start;
          if (video.readyState >= 1) {
            video.currentTime = pendingSeek;
            pendingSeek = null;
          }
          currentSection = at;
          sectionSelect.value = String(at);
          previousSection.disabled = at === 0;
          nextSection.disabled = at === chapters.length - 1;
        };
        video.addEventListener("loadedmetadata", () => {
          if (pendingSeek !== null) {
            video.currentTime = pendingSeek;
            pendingSeek = null;
          }
        });
        video.addEventListener("timeupdate", syncSection);
        previousSection.addEventListener("click", () => seekSection(currentSection - 1));
        nextSection.addEventListener("click", () => seekSection(currentSection + 1));
        sectionSelect.addEventListener("change", () => seekSection(Number(sectionSelect.value)));
        sectionLabel.append(sectionSelect);
        chapterControls.append(previousSection, sectionLabel, nextSection);
        syncSection();
      }
      area.append(
        video,
        captionArea,
        chapterControls,
        unavailable,
        el(
          "p",
          "muted",
          "Synthetic narration. Watching a lesson does not complete its knowledge check or practical task.",
        ),
      );
      root.append(area);
    }
  }

  const deck = el("section", "lesson-section lesson-deck");
  deck.setAttribute("aria-label", "Lesson slides");
  const controls = el("nav", "slide-navigation");
  controls.setAttribute("aria-label", "Slide navigation");
  const previous = el("button", "", "Previous slide");
  previous.type = "button";
  const next = el("button", "", "Next slide");
  next.type = "button";
  const counter = el("span", "slide-counter");
  counter.setAttribute("aria-live", "polite");
  const jumpLabel = el("label", "slide-jump", "Choose slide ");
  const jump = el("select");
  jump.setAttribute("aria-label", "Choose a slide");
  lesson.slides.forEach((slide, i) => {
    const option = el("option", "", `${i + 1}. ${slide.title}`);
    option.value = String(i);
    jump.append(option);
  });
  jumpLabel.append(jump);
  controls.append(previous, counter, next, jumpLabel);
  const slideMount = el("div", "slide-mount");
  deck.append(controls, slideMount);
  root.append(deck);

  function showSlide(focusHeading = false) {
    stopCurrentMedia();
    const slide = lesson.slides[index];
    const card = el("section", "lesson-slide panel");
    const heading = el("h2", "slide-heading", slide.title);
    heading.tabIndex = -1;
    card.append(
      heading,
      list(slide.body),
      createVisual(slide.visual, { lessonId: lesson.id, slideId: slide.id }),
    );
    if (slide.workedExample) {
      const example = el("section", "worked-example");
      example.append(
        el("h3", "", "Worked example"),
        el("p", "", slide.workedExample.prompt),
        list(slide.workedExample.steps, true),
        el("p", "example-answer", slide.workedExample.answer),
      );
      card.append(example);
    }
    if (!lesson.video?.src) {
      const media = el("section", "lesson-media");
      media.append(el("h3", "", "Listen to this slide"));
      const audio = el("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.defaultPlaybackRate = speed;
      audio.playbackRate = speed;
      audio.setAttribute("aria-label", `${slide.title}: synthetic narration`);
      const folder = `media/narration/${encodeURIComponent(lesson.id)}/${encodeURIComponent(slide.id)}`;
      audio.src = resource(`${folder}.mp3`);
      const track = el("track");
      track.kind = "captions";
      track.srclang = "en";
      track.label = "English";
      track.src = resource(`${folder}.vtt`);
      audio.append(track);
      audio.addEventListener("loadedmetadata", () => {
        audio.playbackRate = speed;
      });
      const mediaControls = el("div", "media-controls");
      const speedLabel = el("label", "", "Playback speed ");
      const speedSelect = el("select");
      speedSelect.setAttribute("aria-label", "Narration playback speed");
      [0.75, 1, 1.25, 1.5].forEach((rate) => {
        const option = el("option", "", `${rate}×`);
        option.value = String(rate);
        speedSelect.append(option);
      });
      speedSelect.value = String(speed);
      speedSelect.addEventListener("change", () => {
        speed = Number(speedSelect.value);
        audio.defaultPlaybackRate = speed;
        audio.playbackRate = speed;
      });
      speedLabel.append(speedSelect);
      const toggleLabel = el("label", "", "");
      const toggle = el("input");
      toggle.type = "checkbox";
      toggle.checked = captionsEnabled;
      toggleLabel.append(toggle, document.createTextNode(" Show captions"));
      mediaControls.append(speedLabel, toggleLabel);
      const captions = el(
        "p",
        "media-captions",
        "Captions appear here during narration. The full transcript is available below.",
      );
      captions.hidden = !captionsEnabled;
      const textTrack = track.track;
      if (textTrack) {
        textTrack.mode = "hidden";
        textTrack.addEventListener("cuechange", () => {
          const cues = Array.from(textTrack.activeCues || []);
          captions.textContent = cues.length
            ? cues.map((cue) => cue.text).join(" ")
            : "Narration paused or between caption cues. Read the transcript below at any time.";
        });
      }
      toggle.addEventListener("change", () => {
        captionsEnabled = toggle.checked;
        captions.hidden = !captionsEnabled;
      });
      const mediaError = el("p", "muted");
      mediaError.setAttribute("role", "status");
      audio.addEventListener("error", () => {
        mediaError.textContent =
          "Narration could not load. Read the complete slide transcript below.";
      });
      track.addEventListener("error", () => {
        captions.textContent =
          "Timed captions could not load. Read the complete transcript below.";
      });
      audio.addEventListener("play", () =>
        root.querySelectorAll("video").forEach((video) => video.pause()),
      );
      currentMedia = audio;
      media.append(
        audio,
        mediaControls,
        captions,
        mediaError,
        el(
          "p",
          "muted",
          "Synthetic narration. You can pause, change the speed, or read instead.",
        ),
      );
      card.append(media);
    }
    card.append(
      disclosure(
        "Read the slide transcript",
        slide.narration || "",
        "lesson-transcript",
      ),
    );
    slideMount.replaceChildren(card);
    previous.disabled = index === 0;
    next.disabled = index === lesson.slides.length - 1;
    counter.textContent = `Slide ${index + 1} of ${lesson.slides.length}`;
    jump.value = String(index);
    if (focusHeading) heading.focus();
  }
  function goToSlide(value) {
    index = Math.max(0, Math.min(value, lesson.slides.length - 1));
    persist();
    showSlide(true);
  }
  previous.addEventListener("click", () => goToSlide(index - 1));
  next.addEventListener("click", () => goToSlide(index + 1));
  jump.addEventListener("change", () => goToSlide(Number(jump.value)));
  showSlide();
  persist();

  const practice = el("section", "lesson-practice lesson-section panel");
  practice.append(el("h2", "", "Pause and practise"));
  if (lesson.practice) {
    practice.append(el("p", "", lesson.practice.prompt));
    if (lesson.practice.hints?.length)
      practice.append(disclosure("Show hints", list(lesson.practice.hints)));
    if (lesson.practice.success)
      practice.append(
        disclosure("Compare your reasoning", lesson.practice.success),
      );
    if (
      ["calculation", "dryback", "flow", "threshold"].includes(
        lesson.practice.kind,
      )
    )
      practice.append(
        navigateLink("Open the practice calculators", "practice"),
      );
  }
  const practical = lesson.practicalTask;
  if (practical) {
    const task = el("section", "practical-task");
    task.append(
      el("h3", "", "Practical task"),
      list(practical.instructions, true),
    );
    task.append(
      el(
        "p",
        "muted",
        practical.requiresLocalSupervision
          ? "Complete physical work only with competent local supervision and the installation’s approved procedure. A quiz cannot verify hardware safety."
          : "Explain or practise as instructed. There is no automatic verification of this task.",
      ),
    );
    practice.append(task);
  }
  root.append(practice);

  const quizSection = el("section", "lesson-quiz lesson-section panel");
  const quizHeading = el("h2", "", "Check your understanding");
  quizSection.append(
    quizHeading,
    el(
      "p",
      "muted",
      "This knowledge quiz does not verify a practical task. Choose one answer for each question. Pass with at least 80% and every safety-critical answer correct. You can review the explanations and try again.",
    ),
  );
  const form = el("form");
  const selected = Object.create(null);
  const feedbackNodes = new Map();
  const optionNodes = new Map();
  const questions = Array.isArray(lesson.quiz) ? lesson.quiz : [];
  questions.forEach((question, qi) => {
    const group = el("fieldset", "quiz-question");
    const legend = el("legend", "", `${qi + 1}. ${question.prompt}`);
    if (question.safetyCritical)
      legend.append(el("span", "critical-label", " Safety-critical"));
    group.append(legend);
    const options = el("div", "quiz-options");
    const rows = [];
    question.options.forEach((option, oi) => {
      const label = el("label", "quiz-option");
      const radio = el("input");
      radio.type = "radio";
      radio.name = `${prefix}-question-${qi}`;
      radio.value = String(oi);
      const messageId = `${prefix}-feedback-${qi}`;
      radio.setAttribute("aria-describedby", messageId);
      radio.addEventListener("change", () => {
        selected[question.id] = oi;
        rows.forEach((row) => {
          row.classList.remove("is-correct", "is-incorrect");
          row.classList.toggle("is-selected", row === label);
        });
        const note = feedbackNodes.get(question.id);
        note.textContent = "";
        note.className = "quiz-feedback";
        result.textContent =
          "Answers changed. Select Check answers to assess this attempt.";
        result.className = "quiz-result";
      });
      label.append(radio, el("span", "", option.text));
      rows.push(label);
      options.append(label);
    });
    const note = el("p", "quiz-feedback");
    note.id = `${prefix}-feedback-${qi}`;
    feedbackNodes.set(question.id, note);
    optionNodes.set(question.id, rows);
    group.append(options, note);
    form.append(group);
  });
  const submit = el("button", "", "Check answers");
  submit.type = "submit";
  submit.disabled = !questions.length;
  const result = el("p", "quiz-result");
  result.tabIndex = -1;
  result.setAttribute("role", "status");
  if (progress.completed[lesson.id])
    result.textContent = `Previously passed: ${progress.completed[lesson.id].percent}%. You can use this quiz for review.`;
  form.append(submit, result);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const grade = gradeQuiz(questions, selected);
    for (const item of grade.feedback) {
      const note = feedbackNodes.get(item.id);
      note.className = `quiz-feedback ${item.correct ? "correct" : "incorrect"}`;
      note.textContent = `${item.correct ? "Correct. " : "Review. "}${item.message}${item.critical && !item.correct ? " This safety-critical answer must be correct to pass." : ""}`;
      optionNodes.get(item.id).forEach((row, oi) => {
        row.classList.remove("is-correct", "is-incorrect");
        if (selected[item.id] === oi)
          row.classList.add(item.correct ? "is-correct" : "is-incorrect");
      });
    }
    if (grade.passed) {
      progress.completed = {
        ...progress.completed,
        [lesson.id]: { percent: grade.percent, passedAt: Date.now() },
      };
      result.textContent = `Passed: ${grade.correct} of ${grade.total} correct (${grade.percent}%). Lesson recorded as complete in this browser. Practical tasks still need the stated local checks.`;
    } else {
      const completed = { ...progress.completed };
      delete completed[lesson.id];
      progress.completed = completed;
      const criticalMiss = grade.feedback.some(
        (item) => item.critical && !item.correct,
      );
      result.textContent = `${grade.correct} of ${grade.total} correct (${grade.percent}%). ${criticalMiss ? "A safety-critical answer needs correction. " : ""}The lesson is not complete. Read the feedback, change your answers, and check again.`;
    }
    result.className = `quiz-result ${grade.passed ? "correct" : "incorrect"}`;
    persist();
    result.focus();
  });
  quizSection.append(form);
  root.append(quizSection);

  const transcript = el("div");
  lesson.slides.forEach((slide, i) =>
    transcript.append(
      el("h3", "", `${i + 1}. ${slide.title}`),
      el("p", "", slide.narration),
    ),
  );
  root.append(
    disclosure(
      "Read the complete lesson transcript",
      transcript,
      "lesson-transcript lesson-section",
    ),
  );
  if (lesson.sources?.length) {
    const sources = el("section", "lesson-sources lesson-section");
    sources.append(el("h2", "", "Sources and further reading"));
    const items = el("ul");
    lesson.sources.forEach((source) => {
      const url = resource(source.url);
      if (!url) return;
      const item = el("li");
      const link = el("a", "", source.title || source.url);
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(link);
      if (source.accessed)
        item.append(document.createTextNode(` · checked ${source.accessed}`));
      items.append(item);
    });
    sources.append(items);
    root.append(sources);
  }
  root.append(lessonNavigation("Bottom"));
  return root;
}
