// Repeatable academy checks. Uses a fresh isolated browser context, never a user's profile.
// Serve www first, then: node tests/academy.browser.mjs
// Optional: BASE_URL=https://host/project/learn/ BROWSER_CHANNEL=msedge RUN_MEDIA=1
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import AxeBuilder from "../frontend/node_modules/@axe-core/playwright/dist/index.mjs";
import { readmeImage } from "../frontend/scripts/readme-images.mjs";
const base = (process.env.BASE_URL || "http://127.0.0.1:8794/learn/").replace(
  /\/?$/,
  "/",
);
const channel =
  process.env.BROWSER_CHANNEL ||
  (process.platform === "win32" ? "msedge" : undefined);
const browser = await chromium.launch({
  headless: true,
  ...(channel ? { channel } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const key = "crop-steering-academy:progress:v1";
const output = {
  base,
  lessons: 0,
  sources: 0,
  viewports: [],
  accessibility: [],
  checks: [],
  media: 0,
};
async function open(route = "") {
  await page.goto(base + route);
  await page.locator("#main h1").waitFor();
  if (route.startsWith("#/watch/")) await page.locator(".watch-player video").waitFor();
}
async function record() {
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key)), key);
}
async function assertFocus(selector) {
  await page.waitForFunction(
    (selector) =>
      document.activeElement !== document.body &&
      document.activeElement?.matches(selector),
    selector,
  );
}
async function noOverflow(label) {
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Horizontal overflow: " + label,
  );
}
try {
  const response = await context.request.get(
    new URL("course/course.json", base).href,
  );
  assert.equal(response.status(), 200, "Course JSON must be served");
  const course = await response.json();
  assert.equal(course.lessons.length, 24);
  assert.equal(course.lessons[0].id, "A1");
  await open();
  await page.locator(".hero img").waitFor();
  await page.locator(".hero img").evaluate(async (image) => {
    await image.decode();
    if (!image.naturalWidth)
      throw Error("Hero image did not decode: " + image.src);
  });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({
    path: readmeImage("academy-home.png"),
    fullPage: true,
  });
  await page.getByRole("link", { name: "Course", exact: true }).click();
  await page.locator(".course-lesson").first().waitFor();
  assert.equal(await page.locator(".course-lesson").count(), 24);
  for (const route of ["operator", "builder-pi", "builder-x86"]) {
    await page.locator("#learning-route").selectOption(route);
    await assertFocus("#learning-route");
    assert.equal(
      await page.evaluate(() => document.activeElement.id),
      "learning-route",
    );
    assert.equal((await record()).route, route);
    await page.locator(".course-lesson").first().waitFor();
    assert.equal(await page.locator(".course-lesson").count(), 24);
  }
  const transcriptLink = page.getByRole("link", {
    name: "Download all lesson transcripts",
    exact: true,
  });
  assert.equal(
    await transcriptLink.getAttribute("href"),
    "course/all-lesson-transcripts.txt",
  );
  assert.equal(
    await transcriptLink.getAttribute("download"),
    "all-lesson-transcripts.txt",
  );
  assert.equal(
    (
      await context.request.head(
        new URL("course/all-lesson-transcripts.txt", base).href,
      )
    ).status(),
    200,
  );
  output.checks.push(
    "catalogue, all three learning routes and full transcript download link",
  );
  for (const lesson of course.lessons) {
    await open("#/lesson/" + lesson.id);
    await page
      .getByRole("heading", { name: lesson.title, exact: true })
      .waitFor();
    const sourceLinks = await page
      .locator(".lesson-sources a")
      .evaluateAll((xs) => xs.map((x) => x.href));
    assert.equal(
      sourceLinks.length,
      lesson.sources.length,
      "Source count " + lesson.id,
    );
    for (let i = 0; i < sourceLinks.length; i++) {
      assert.match(sourceLinks[i], /^https?:/);
      assert.equal(sourceLinks[i], new URL(lesson.sources[i].url, base).href);
    }
    output.sources += sourceLinks.length;
    output.lessons++;
  }
  console.log(
    "Rendered all " +
      output.lessons +
      " lessons and " +
      output.sources +
      " source links.",
  );
  const lesson = course.lessons.find((x) => x.id === "D3");
  await open("#/lesson/D3");
  // Questions are one per screen after the sections; the step track jumps there.
  const firstQuestion = 1 + lesson.slides.length + (lesson.practice || lesson.practicalTask ? 1 : 0);
  const answerAll = async (pick) => {
    await page.locator(".lp-dot").nth(firstQuestion).click();
    for (let i = 0; i < lesson.quiz.length; i++) {
      await page.locator(".quiz-question input[type=radio]").nth(pick(lesson.quiz[i])).check();
      await page.locator(".lp-next").click();
    }
  };
  let criticalMiss = false;
  await answerAll((q) =>
    q.safetyCritical && !criticalMiss
      ? ((criticalMiss = true), q.options.findIndex((x) => !x.correct))
      : q.options.findIndex((x) => x.correct),
  );
  await page.getByText(/A safety-critical answer needs fixing/).waitFor();
  assert.equal(
    (await record()).completed.D3,
    undefined,
    "Safety-critical miss must block even with 80%",
  );
  await page.getByRole("button", { name: "Try the questions again", exact: true }).click();
  for (let i = 0; i < lesson.quiz.length; i++) {
    await page.locator(".quiz-question input[type=radio]").nth(lesson.quiz[i].options.findIndex((x) => x.correct)).check();
    await page.locator(".lp-next").click();
  }
  await page.getByText(/^Passed: 5 of 5/).waitFor();
  assert.equal((await record()).completed.D3.percent, 100);
  // Visiting Result again without a new attempt must keep the saved pass.
  await page.reload();
  await page.locator(".lp-dot").last().click();
  await page.getByText(/earlier pass \(100%\) is still recorded/).waitFor();
  assert.equal((await record()).completed.D3.percent, 100, "Opening Result must not erase a pass");
  output.checks.push(
    "80% safety-critical failure blocks, correct retry passes",
  );
  await page.locator(".lp-dot").nth(2).click();
  const position = await page.locator(".lp-counter").textContent();
  await page.reload();
  await page.locator(".lp-counter").waitFor();
  assert.equal(await page.locator(".lp-counter").textContent(), position);
  output.checks.push("slide resume after reload");
  await open("#/progress");
  const pending = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export progress", exact: true })
    .click();
  const download = await pending;
  const exportPath = path.join(
    os.tmpdir(),
    "academy-progress-test-" + Date.now() + ".json",
  );
  await download.saveAs(exportPath);
  const exported = JSON.parse(fs.readFileSync(exportPath, "utf8"));
  fs.unlinkSync(exportPath);
  assert.equal(exported.completed.D3.percent, 100);
  assert.ok(exported.slides.D3 >= 1);
  exported.route = "builder-x86";
  exported.completed.D3.passedAt = Date.now() - 2 * 86400000;
  exported.reviewed = {};
  await page.locator("#progress-file").setInputFiles({
    name: "progress.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(exported)),
  });
  await page
    .getByRole("button", { name: "Record a recall check", exact: true })
    .waitFor();
  assert.equal(
    await page.locator("#learning-route").inputValue(),
    "builder-x86",
  );
  await assertFocus(".progress-page h1");
  await page
    .getByRole("button", { name: "Record a recall check", exact: true })
    .click();
  await assertFocus(".review-panel h2");
  assert.ok((await record()).reviewed.D3);
  assert.equal(
    await page
      .getByRole("button", { name: "Record a recall check", exact: true })
      .count(),
    0,
  );
  await page.locator("#progress-file").setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from("{bad"),
  });
  await page.getByText("The file does not contain valid JSON.").waitFor();
  assert.ok((await record()).completed.D3);
  await page.locator(".reset-progress summary").click();
  await page
    .getByRole("button", { name: "Reset progress now", exact: true })
    .click();
  await assertFocus(".progress-page h1");
  assert.equal(Object.keys((await record()).completed).length, 0);
  output.checks.push(
    "export, valid import, malformed import preservation, spaced recall, reset and logical focus restoration",
  );
  await open("#/glossary");
  const term = course.glossary[0].term;
  await page.locator("#glossary-search").fill(term);
  await page.locator(".glossary-list dt").first().waitFor();
  assert.ok(await page.locator(".glossary-list dt").count());
  await page.locator("#glossary-search").fill("<script>not a term</script>");
  assert.equal(await page.locator(".glossary-list dt").count(), 0);
  output.checks.push("glossary search and literal input");
  const routes = [
    "#/",
    "#/course",
    "#/lesson/D3",
    "#/watch/foundations",
    "#/practice",
    "#/glossary",
    "#/progress",
  ];
  for (const width of [320, 360, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of routes) {
      await open(route);
      await noOverflow(width + " " + route);
    }
    output.viewports.push(width);
    console.log("No overflow on " + routes.length + " routes at " + width + "px.");
  }
  await page.setViewportSize({ width: 320, height: 800 });
  for (const lesson of course.lessons) {
    await open("#/lesson/" + lesson.id);
    await noOverflow("320px " + lesson.id);
  }
  output.checks.push("all 24 lessons at 320px");
  await page.setViewportSize({ width: 360, height: 800 });
  for (const route of routes) {
    await open(route);
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    output.accessibility.push({
      route,
      violations: result.violations.map((x) => ({
        id: x.id,
        targets: x.nodes.map((n) => n.target),
      })),
    });
    assert.deepEqual(
      result.violations.map((x) => x.id),
      [],
      "Accessibility " + route,
    );
    console.log("Axe clean: " + route);
  }
  await open();
  await page.keyboard.press("Tab");
  assert.ok(
    await page
      .locator(".skip-link")
      .evaluate((x) => x === document.activeElement),
  );
  await page.keyboard.press("Enter");
  assert.ok(
    await page.locator("#main").evaluate((x) => x === document.activeElement),
  );
  await page.locator("[data-nav=course]").focus();
  await page.keyboard.press("Enter");
  await page
    .getByRole("heading", { name: "Your learning path", exact: true })
    .waitFor();
  output.checks.push("keyboard skip link and primary navigation");
  await page.setViewportSize({ width: 1280, height: 1000 });
  await open("#/lesson/A3");
  await page.waitForFunction(() => document.querySelector("video")?.readyState >= 2);
  await page.locator(".lp-dot").nth(2).click();
  const capacityChapter = course.lessons.find(lesson => lesson.id === "A3").video.chapters[1].start;
  await page.waitForFunction(start => {
    const video = document.querySelector("video");
    return !video.seeking && Math.abs(video.currentTime - start) < .25;
  }, capacityChapter);
  await page.locator("video").evaluate(async video => {
    video.muted = true;
    await video.play();
  });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(3500);
  await page.locator(".lp").screenshot({
    path: readmeImage("academy-lesson.png"),
  });
  await page.locator("video").evaluate(video => video.pause());
  const blocked = await browser.newContext();
  await blocked.addInitScript(() =>
    Object.defineProperty(window, "localStorage", {
      get() {
        throw Error("Storage denied for test");
      },
    }),
  );
  const blockedPage = await blocked.newPage();
  await blockedPage.goto(base + "#/lesson/D2");
  await blockedPage.locator(".lp").waitFor();
  await blockedPage.locator(".lp-next").click();
  assert.ok(await blockedPage.locator(".lp-save").isVisible(), "Lesson shows its own save warning");
  assert.ok(await blockedPage.locator(".lp-nav").evaluate((n) => n.getBoundingClientRect().bottom <= innerHeight), "Warning must not push lesson navigation off screen");
  await blockedPage.goto(base + "#/progress");
  await blockedPage
    .getByRole("button", { name: "Export progress", exact: true })
    .waitFor();
  await blocked.close();
  output.checks.push(
    "storage denied: lesson navigation and export remain available",
  );
  if (process.env.RUN_MEDIA === "1") {
    const media = [];
    for (const lesson of course.lessons) {
      if (lesson.video?.src) {
        media.push({
          src: lesson.video.src,
          caption: lesson.video.captions?.src || lesson.video.captions,
          kind: "video",
        });
      } else
        for (const slide of lesson.slides) {
          const stem =
            "media/narration/" +
            encodeURIComponent(lesson.id) +
            "/" +
            encodeURIComponent(slide.id);
          media.push({
            src: stem + ".mp3",
            caption: stem + ".vtt",
            kind: "audio",
          });
        }
    }
    for (const item of media) {
      const url = new URL(item.src, base).href;
      const head = await context.request.head(url);
      assert.equal(head.status(), 200, "Media response " + url);
      let captions = "";
      if (item.caption) {
        const response = await context.request.get(
          new URL(item.caption, base).href,
        );
        assert.equal(
          response.status(),
          200,
          "Caption response " + item.caption,
        );
        captions = await response.text();
        assert.match(captions, /^WEBVTT/);
        assert.match(captions, /-->/);
      }
      await open("#/practice");
      const result = await page.evaluate(
        async ({ url, kind }) => {
          const element = document.createElement(kind);
          element.muted = true;
          element.preload = "auto";
          document.body.append(element);
          try {
            return await new Promise((resolve, reject) => {
              const timer = setTimeout(
                () => reject(Error("Media timeout at " + url)),
                20000,
              );
              element.addEventListener(
                "error",
                () => {
                  clearTimeout(timer);
                  reject(
                    Error(
                      "Decode failure " +
                        element.error?.code +
                        " at " +
                        url +
                        ": " +
                        (element.error?.message || "No decoder details"),
                    ),
                  );
                },
                { once: true },
              );
              element.addEventListener(
                "loadedmetadata",
                async () => {
                  try {
                    const duration = element.duration;
                    await element.play();
                    setTimeout(() => {
                      element.pause();
                      clearTimeout(timer);
                      resolve({ duration, time: element.currentTime });
                    }, 250);
                  } catch (error) {
                    clearTimeout(timer);
                    reject(
                      Error("Playback failed at " + url + ": " + error.message),
                    );
                  }
                },
                { once: true },
              );
              element.src = url;
            });
          } finally {
            element.pause();
            element.removeAttribute("src");
            element.load();
            element.remove();
          }
        },
        { url, kind: item.kind },
      );
      assert.ok(
        result.duration > 0 && Number.isFinite(result.duration),
        "Media duration " + url,
      );
      assert.ok(result.time > 0, "Media playback " + url);
      output.media++;
      console.log(
        "Played " + output.media + "/" + media.length + ": " + item.src,
      );
    }
  }
  assert.deepEqual(errors, [], "Browser JavaScript errors");
  output.checks.push("zero page errors");
  console.log(JSON.stringify(output, null, 2));
} finally {
  await browser.close();
}
