/** Shared navigation for specialist tools. Primary workflows live in f2.html. */
(() => {
  const names = {
    'f2-classic.html': 'Classic specialist console',
    'home.html': 'Facility overview', 'overview.html': 'Compact controls',
    'setpoints.html': 'Long-term crop planner', 'crop_steering.html': 'Legacy irrigation console',
    'crop_steering_tune.html': 'Advanced setpoint editor', 'crop_steering_rules.html': 'Controller rules',
    'office.html': 'Office environment', 'system-map.html': 'System map',
    'irrigation-manual.html': 'Irrigation manual', 'install.html': 'Installation guide',
    'SYSTEM_GUIDE.html': 'System guide',
  };
  const filename = location.pathname.split('/').pop();
  if (!names[filename] || document.getElementById('operator-return-nav')) return;
  const context = new URLSearchParams();
  const current = new URLSearchParams(location.search);
  if (current.has('room')) context.set('room', current.get('room'));
  if (current.has('demo') || /(^|\.)github\.io$/i.test(location.hostname)) context.set('demo', '');
  const primaryContext = new URLSearchParams(context);
  // Classic supports only f1 or the empty-prefix default room. Do not return
  // using the ambiguous f2 alias, which can also name a separate modern room.
  if (filename === 'f2-classic.html') {
    primaryContext.set('room', current.get('room') === 'f1' ? 'room:f1_' : 'room:');
  }
  const href = './f2.html' + (primaryContext.size ? '?' + primaryContext.toString() : '');
  const style = document.createElement('style');
  style.textContent = '#operator-return-nav{position:relative;z-index:90;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 16px;padding:10px 20px;background:#f1f7f3;color:#244c3b;border-bottom:1px solid #c7dcd0;font:13px/1.4 system-ui,sans-serif;box-sizing:border-box;width:100%;isolation:isolate}#operator-return-nav a{color:#12603f;font-weight:650;text-decoration:none;padding:4px 0}#operator-return-nav a:hover{text-decoration:underline}#operator-return-nav a:focus-visible{outline:2px solid #167352;outline-offset:4px}#operator-return-nav span{color:#4b6356}';
  document.head.append(style);
  const nav = document.createElement('nav');
  nav.id = 'operator-return-nav';
  nav.setAttribute('aria-label', 'Operator dashboard');
  const back = document.createElement('a'); back.href = href; back.textContent = '← Back to dashboard';
  const name = document.createElement('span'); name.textContent = names[filename];
  const help = document.createElement('a'); help.href = href + '#help'; help.textContent = 'Help & tools';
  nav.append(back, name, help);
  document.body.prepend(nav);
  // Links between tools retain the current room and explicit demo state.
  for (const link of document.querySelectorAll('a[href]')) {
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !/\.html$/.test(url.pathname)) continue;
    const linkContext = url.pathname.endsWith('/f2.html') ? primaryContext : context;
    for (const [key, value] of linkContext) if (!url.searchParams.has(key)) url.searchParams.set(key, value);
    link.href = url.pathname + url.search + url.hash;
  }
})();
