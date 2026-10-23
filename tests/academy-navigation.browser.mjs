// Focused regression checks for continuous lesson and grouped-video navigation.
// Serve www, then node tests/academy-navigation.browser.mjs. Media fixture uses a real local lesson video.
import assert from 'node:assert/strict';
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
const base = process.env.BASE_URL || 'http://127.0.0.1:8794/learn/';
const key = 'crop-steering-academy:progress:v1';
const browser = await chromium.launch({channel: process.env.BROWSER_CHANNEL || 'msedge', headless:true});
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const course = await (await context.request.get(new URL('course/course.json', base).href)).json();
  const a1 = course.lessons.find(lesson => lesson.id === 'A1');
  assert.ok(a1.video?.src, 'A1 must have an actual video');
  // Deterministic section times (one per slide) prove seeking without depending on narration edits.
  a1.video.chapters = a1.slides.map((slide, i) => ({id:slide.id, title:`Test section ${i+1}`, start:i*2}));
  await page.route('**/course/course.json?*', route => route.fulfill({json:course}));
  const common = {src:a1.video.src, captions:a1.video.captions?.src || a1.video.captions, duration:6,
    chapters: [0,2,4].map((start,i) => ({id:`A1-0${i+1}`, lesson:'A1', title:`A1 · Test section ${i+1}`, start})), lessons:['A1']};
  const all = ['operator','builder-pi','builder-x86'];
  const groups = [
    {...common,id:'foundations',title:'Foundations',routes:all},
    {...common,id:'setup-pi',title:'Pi setup',routes:['builder-pi']},
    {...common,id:'setup-x86',title:'x86 setup',routes:['builder-x86']},
    {...common,id:'operations',title:'Operations',routes:all},
  ];
  await page.route('**/course/video-groups.json?*', route => route.fulfill({json:{edition:'test',groups}}));
  const waitLesson = id => page.waitForFunction(title => document.querySelector('.lp-title h1')?.textContent === title, course.lessons.find(lesson => lesson.id === id).title);
  const menu = async () => { await page.locator('.lp-menu-button').click(); await page.locator('.lp-drawer[open]').waitFor(); };
  const drawerButton = name => page.locator('.lp-drawer').getByRole('button', {name});
  await page.goto(base + '#/lesson/A1');
  await waitLesson('A1');
  await page.locator('.lp-drawer select option').first().waitFor({state:'attached'});
  assert.equal(await page.locator('.lp-drawer select option').count(),24,'All lessons remain directly available');
  await menu();
  assert.equal(await drawerButton(/^Previous lesson:/).count(),0,'First lesson has no previous lesson');
  await page.locator('.lp-drawer-close').click();
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1);
  await page.locator('.lp-dot').nth(2).click();
  await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime - 2) < .25);
  await page.locator('.lp-dot').nth(3).click();
  await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime - 4) < .25);
  // Playing past a section end pauses at that boundary.
  await page.locator('video').evaluate(async video => {video.muted = true; video.currentTime = 5.6; await video.play();});
  await page.waitForFunction(() => document.querySelector('video').paused && document.querySelector('video').currentTime < 6);
  const counter = await page.locator('.lp-counter').textContent();
  await menu();
  await drawerButton(/^Next lesson:/).click();
  await page.waitForURL('**/#/lesson/A2');
  await waitLesson('A2');
  await menu();
  await drawerButton(/^Previous lesson:/).click();
  await page.waitForURL('**/#/lesson/A1');
  await waitLesson('A1');
  assert.equal(await page.locator('.lp-counter').textContent(), counter, 'Step position resumes');
  await menu();
  await page.locator('.lp-drawer select').selectOption('C1');
  await page.waitForURL('**/#/lesson/C1');
  await waitLesson('C1');
  await menu();
  await drawerButton(/^Next lesson: D1/).waitFor();
  await drawerButton(/^Next lesson: D1/).click();
  await page.waitForURL('**/#/lesson/D1');
  await waitLesson('D1');
  await page.goto(base+'#/course');
  await page.locator('#learning-route').selectOption('builder-pi');
  await page.goto(base+'#/lesson/C2a');
  await waitLesson('C2a');
  await menu();
  assert.equal(await drawerButton(/^Next lesson: C3/).count(),1,'Pi route skips alternative x86 lesson');
  await page.locator('.lp-drawer select').selectOption('C2b');
  await page.waitForURL('**/#/lesson/C2b');
  await waitLesson('C2b');
  let progress = await page.evaluate(key=>JSON.parse(localStorage.getItem(key)),key);
  assert.deepEqual(progress.completed,{},'Watching, seeking and navigating must not complete lessons');
  const beforeWatch = JSON.stringify(progress);
  await menu();
  await drawerButton('Watch the longer course videos').click();
  await page.locator('.watch-player video').waitFor();
  assert.equal(await page.getByRole('combobox',{name:'Choose a video group',exact:true}).inputValue(),'foundations');
  const nextGroup = page.getByRole('button',{name:'Next video: Pi setup',exact:true});
  await nextGroup.click();
  await page.waitForURL('**/#/watch/setup-pi');
  await page.locator('.watch-player video').waitFor();
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1);
  const chapter = page.getByRole('combobox',{name:'Choose grouped video section',exact:true});
  await chapter.selectOption('2');
  await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime-4)<.25);
  await page.getByRole('button',{name:'Previous section',exact:true}).click();
  await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime-2)<.25);
  await page.locator('.watch-chapter-list button').first().click();
  await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime)<.25);
  await page.locator('video').evaluate(video=>{video.currentTime=4.5;});
  await page.waitForFunction(() => document.querySelector('[aria-label="Choose grouped video section"]').value==='2');
  assert.match(await page.getByRole('link',{name:/Read and practise:/}).getAttribute('href'),/lesson\/A1$/);
  const picture = await page.locator('video').boundingBox(), caption = await page.locator('.group-captions').boundingBox();
  assert.ok(caption.y >= picture.y+picture.height,'Grouped captions remain below the picture');
  await page.getByRole('checkbox',{name:'Show captions below video',exact:true}).uncheck();
  assert.equal(await page.locator('.group-captions').isVisible(),false);
  await page.getByRole('checkbox',{name:'Show captions below video',exact:true}).check();
  await page.getByRole('checkbox',{name:/Continue to the next video/}).check();
  await page.locator('video').evaluate(video=>video.dispatchEvent(new Event('ended')));
  await page.waitForURL('**/#/watch/operations');
  await page.locator('.watch-player video').waitFor();
  assert.equal(await page.evaluate(key=>localStorage.getItem(key),key),beforeWatch,'Grouped viewing leaves learning progress untouched');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Watch controls fit mobile');
  assert.deepEqual(errors,[],'No browser runtime errors');
  // A missing metadata file cannot prevent regular lessons from opening.
  const missing = await context.newPage();
  await missing.route('**/course/video-groups.json?*',route=>route.fulfill({status:404,body:'Not yet generated'}));
  await missing.goto(base+'#/watch');
  await missing.getByRole('heading',{name:'Grouped videos are unavailable',exact:true}).waitFor();
  await missing.getByRole('link',{name:'Choose an individual lesson',exact:true}).click();
  await missing.locator('.course-lesson').first().waitFor();
  assert.equal(await missing.locator('.course-lesson').count(),24);
  console.log('PASS direct lesson navigation, route order, all-lesson jump, real video chapter seeks, grouped viewing, below-video captions, mobile layout, metadata fallback and unchanged completion');
} finally {await browser.close();}
