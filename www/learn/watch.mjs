const el = (tag, cls = '', text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const button = (text, action) => {
  const node = el('button', '', text);
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
};
const link = (text, href, cls = 'text-link') => {
  const node = el('a', cls, text);
  node.href = href;
  return node;
};
const time = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
let metadata;
async function loadGroups() {
  if (!metadata) metadata = fetch('course/video-groups.json?v=20261021r5').then(async response => {
    if (!response.ok) throw Error('Video list returned ' + response.status);
    const data = await response.json();
    if (!Array.isArray(data.groups) || !data.groups.length) throw Error('No grouped videos are available yet.');
    return data.groups;
  }).catch(error => { metadata = null; throw error; });
  return metadata;
}

/** Group viewing is separate from quiz progress. No completion or HA state is changed. */
export async function renderWatch({groupId = '', route = 'operator', lessons = [], onNavigate = () => {}} = {}) {
  const root = el('article', 'watch-page');
  root.append(el('p', 'eyebrow', 'Watch and follow along'), el('h1', '', 'Course videos'),
    el('p', 'lede', 'Choose a part, jump to an explanation, or open its lesson to read and practise.'),
    link('Open all lessons', '#/course'));
  let groups;
  try { groups = await loadGroups(); }
  catch {
    const fallback = el('section', 'panel watch-unavailable');
    fallback.setAttribute('role', 'status');
    fallback.append(el('h2', '', 'Grouped videos are unavailable'),
      el('p', '', 'The video list could not load. Individual lesson videos, transcripts and exercises are still available.'),
      link('Choose an individual lesson', '#/course', 'button'),
      button('Try loading the videos again', () => onNavigate('/watch/' + encodeURIComponent(groupId))));
    root.append(fallback);
    return root;
  }
  groups = groups.filter(group => group.id && group.src && Array.isArray(group.chapters) && group.chapters.length);
  if (!groups.length) {
    root.append(el('p', 'panel', 'Grouped videos are being prepared. Open an individual lesson to continue.'));
    return root;
  }
  const recommended = groups.filter(group => !group.routes?.length || group.routes.includes(route));
  let group = groups.find(item => item.id === groupId) || recommended[0] || groups[0];
  const sequence = groups.filter(item => item.id === group.id || recommended.some(candidate => candidate.id === item.id));
  const groupIndex = sequence.findIndex(item => item.id === group.id);
  const picker = el('label', 'watch-group-picker', 'Choose a video ');
  const groupSelect = el('select');
  groupSelect.setAttribute('aria-label', 'Choose a video group');
  groups.forEach(item => {
    const option = el('option', '', item.title + (item.duration ? ` · ${time(item.duration)}` : ''));
    option.value = item.id;
    groupSelect.append(option);
  });
  groupSelect.value = group.id;
  groupSelect.addEventListener('change', () => onNavigate('/watch/' + encodeURIComponent(groupSelect.value)));
  picker.append(groupSelect);
  root.append(picker);
  const panel = el('section', 'panel watch-player');
  panel.append(el('h2', '', group.title), el('p', '', group.description || ''));
  const video = el('video');
  video.controls = true;
  video.preload = 'metadata';
  video.playsInline = true;
  video.setAttribute('aria-label', group.title + ': grouped course video');
  video.src = group.src;
  const status = el('p', 'watch-media-status muted', 'Loading video. You can choose any section while it loads.');
  status.setAttribute('role', 'status');
  const captions = el('p', 'media-captions group-captions', 'Captions appear here during narration.');
  const captionLabel = el('label', 'watch-caption-toggle');
  const toggle = el('input');
  toggle.type = 'checkbox';
  toggle.checked = true;
  captionLabel.append(toggle, document.createTextNode(' Show captions below video'));
  if (group.captions) {
    const track = el('track');
    track.kind = 'captions';
    track.srclang = 'en';
    track.label = 'English captions';
    track.src = typeof group.captions === 'string' ? group.captions : group.captions.src;
    video.append(track);
    const textTrack = track.track;
    textTrack.mode = 'hidden';
    const update = () => {
      captions.hidden = !toggle.checked || textTrack.mode === 'showing';
      const cues = Array.from(textTrack.activeCues || []);
      captions.textContent = cues.length ? cues.map(cue => cue.text).join(' ') : 'Narration paused or between caption cues. Open the relevant lesson to read the transcript.';
    };
    textTrack.addEventListener('cuechange', update);
    video.textTracks.addEventListener('change', update);
    toggle.addEventListener('change', () => {textTrack.mode = 'hidden'; update();});
    track.addEventListener('error', () => { captions.textContent = 'Timed captions could not load. Open the relevant lesson for its full transcript.'; });
  } else {
    captions.textContent = 'Timed captions are unavailable. Open the relevant lesson for its full transcript.';
    toggle.addEventListener('change', () => { captions.hidden = !toggle.checked; });
  }
  const chapters = group.chapters.filter(chapter => Number.isFinite(chapter.start) && chapter.start >= 0);
  const controls = el('nav', 'video-chapters');
  controls.setAttribute('aria-label', 'Grouped video sections');
  const chapterLabel = el('label', 'chapter-jump', 'Choose a section ');
  const chapterSelect = el('select');
  chapterSelect.setAttribute('aria-label', 'Choose grouped video section');
  const chapterList = el('ol', 'watch-chapter-list');
  const lessonLink = link('Open the lesson', '#/course', 'button');
  const chapterHeading = el('h3', 'watch-current-section');
  let chapterIndex = 0, pendingSeek = null;
  const chapterButtons = [];
  const update = at => {
    chapterIndex = Math.max(0, at);
    chapterSelect.value = String(chapterIndex);
    previousChapter.disabled = chapterIndex === 0;
    nextChapter.disabled = chapterIndex >= chapters.length - 1;
    const chapter = chapters[chapterIndex];
    if (!chapter) return;
    chapterHeading.textContent = chapter.title;
    const lesson = lessons.find(item => item.id === chapter.lesson);
    lessonLink.textContent = `Read and practise: ${chapter.lesson}${lesson ? ' · ' + lesson.title : ''}`;
    lessonLink.href = '#/lesson/' + encodeURIComponent(chapter.lesson);
    chapterButtons.forEach((node, i) => {
      if (i === chapterIndex) node.setAttribute('aria-current', 'true');
      else node.removeAttribute('aria-current');
    });
  };
  const seek = at => {
    at = Math.max(0, Math.min(at, chapters.length - 1));
    if (!chapters[at]) return;
    pendingSeek = chapters[at].start;
    if (video.readyState >= 1) {video.currentTime = pendingSeek; pendingSeek = null;}
    update(at);
  };
  const previousChapter = button('Previous section', () => seek(chapterIndex - 1));
  const nextChapter = button('Next section', () => seek(chapterIndex + 1));
  chapters.forEach((chapter, i) => {
    const option = el('option', '', `${time(chapter.start)} · ${chapter.title}`);
    option.value = String(i);
    chapterSelect.append(option);
    const item = el('li');
    const jump = button(`${time(chapter.start)} · ${chapter.title}`, () => seek(i));
    chapterButtons.push(jump);
    item.append(jump);
    chapterList.append(item);
  });
  chapterSelect.addEventListener('change', () => seek(Number(chapterSelect.value)));
  chapterLabel.append(chapterSelect);
  controls.append(previousChapter, chapterLabel, nextChapter);
  video.addEventListener('loadedmetadata', () => {
    if (pendingSeek !== null) {video.currentTime = pendingSeek; pendingSeek = null;}
    status.textContent = 'Ready. Press play to watch, or choose a section.';
  });
  video.addEventListener('waiting', () => { status.textContent = 'Video is buffering. Your place is held.'; });
  video.addEventListener('playing', () => { status.textContent = 'Playing ' + group.title + '.'; });
  video.addEventListener('error', () => {
    status.textContent = 'This video could not load. Open the relevant lesson below for its individual video, transcript and exercises.';
    status.classList.add('watch-media-error');
  });
  video.addEventListener('timeupdate', () => update(Math.max(0, chapters.findLastIndex(chapter => video.currentTime >= chapter.start))));
  panel.append(video, captionLabel, captions, status, controls, chapterHeading, lessonLink);
  root.append(panel);
  const groupNav = el('nav', 'watch-group-navigation');
  groupNav.setAttribute('aria-label', 'Video group navigation');
  for (const [offset, label] of [[-1, 'Previous video'], [1, 'Next video']]) {
    const target = sequence[groupIndex + offset];
    const control = button(target ? `${label}: ${target.title}` : label, () => {
      video.pause();
      if (target) onNavigate('/watch/' + encodeURIComponent(target.id));
    });
    control.disabled = !target;
    groupNav.append(control);
  }
  const autoLabel = el('label', 'watch-auto-continue');
  const auto = el('input');
  auto.type = 'checkbox';
  try { auto.checked = sessionStorage.getItem('academy-watch-continue') === 'true'; } catch {}
  auto.addEventListener('change', () => {
    try { sessionStorage.setItem('academy-watch-continue', String(auto.checked)); } catch {}
  });
  autoLabel.append(auto, document.createTextNode(' Continue to the next video when this one ends'));
  const continuation = el('p', 'muted', 'Next and previous videos follow your learning route. Watching does not record a quiz pass.');
  // Autoplay remains subject to browser media permissions; controls stay available.
  video.addEventListener('ended', () => {
    const target = sequence[groupIndex + 1];
    if (auto.checked && target) {
      try { sessionStorage.setItem('academy-watch-play', target.id); } catch {}
      onNavigate('/watch/' + encodeURIComponent(target.id));
    }
  });
  video.addEventListener('canplay', () => {
    try {
      if (sessionStorage.getItem('academy-watch-play') === group.id) {
        sessionStorage.removeItem('academy-watch-play');
        video.play().catch(() => {status.textContent = 'Next video is ready. Press play to continue.';});
      }
    } catch {}
  }, {once: true});
  root.append(groupNav, autoLabel, continuation);
  const contents = el('section', 'watch-contents');
  contents.append(el('h2', '', 'Sections in this video'), chapterList);
  root.append(contents);
  update(0);
  return root;
}
