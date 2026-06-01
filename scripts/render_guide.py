#!/usr/bin/env python3
"""Render SYSTEM_GUIDE.md → styled standalone HTML (root + www copies).

Single source of truth is the Markdown. Re-run this after editing the .md so the
HTML guides never drift again:  python scripts/render_guide.py
"""
import re, markdown

SRC = "SYSTEM_GUIDE.md"
md = open(SRC, encoding="utf-8").read()

# Drop the inline "Table of Contents" section — the sidebar replaces it (no double nav).
md = re.sub(r"^## Table of Contents\n.*?(?=^## )", "", md, flags=re.M | re.S)

# python-markdown's tables extension needs a blank line before a table. Several tables
# in the source sit directly under a "**Label:**" line — insert the blank where missing.
_lines, _fixed = md.split("\n"), []
for _ln in _lines:
    if re.match(r"\s*\|.*\|\s*$", _ln) and _fixed and _fixed[-1].strip() and not re.match(r"\s*\|", _fixed[-1]):
        _fixed.append("")
    _fixed.append(_ln)
md = "\n".join(_fixed)

body = markdown.markdown(
    md,
    extensions=["tables", "fenced_code", "attr_list", "sane_lists", "toc"],
    extension_configs={"toc": {"permalink": False, "toc_depth": "2-3"}},
)

# Sidebar nav built from the actual <h2 id="…"> ids so links always resolve.
nav = "".join(
    f'<a href="#{i}">{re.sub("<.*?>", "", x).strip()}</a>'
    for i, x in re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', body, re.S)
)

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Crop Steering — System Guide</title>
<!-- Auto-generated from SYSTEM_GUIDE.md by scripts/render_guide.py — do not edit by hand. -->
<style>
  :root{--bg:#0b1020;--bg2:#0f1730;--card:#121d3a;--br:#23304f;--ink:#e7edf9;--dim:#9aa8c4;--faint:#67769a;
        --green:#34d399;--cyan:#22d3ee;--amber:#fbbf24;--accent:#34d399;--code:#0a1120;}
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;-webkit-font-smoothing:antialiased}
  a{color:var(--cyan);text-decoration:none}a:hover{text-decoration:underline}
  .wrap{display:flex;align-items:flex-start;max-width:1280px;margin:0 auto}
  /* sidebar */
  nav.toc{position:sticky;top:0;height:100vh;width:280px;flex:none;overflow-y:auto;padding:24px 14px 40px;border-right:1px solid var(--br);background:linear-gradient(180deg,var(--bg2),var(--bg))}
  nav.toc .brand{font-weight:800;letter-spacing:.4px;font-size:15px;display:flex;align-items:center;gap:9px;margin:4px 8px 16px;color:var(--ink)}
  nav.toc .brand .leaf{font-size:20px;filter:drop-shadow(0 0 8px #34d39988)}
  nav.toc a{display:block;color:var(--dim);font-size:13px;padding:6px 10px;border-radius:8px;border-left:2px solid transparent;line-height:1.35}
  nav.toc a:hover{color:var(--ink);background:rgba(255,255,255,.04);text-decoration:none}
  nav.toc a.active{color:var(--ink);background:rgba(52,211,153,.10);border-left-color:var(--accent)}
  /* content */
  main{flex:1;min-width:0;padding:40px 48px 96px;max-width:920px}
  main>h1:first-child{margin-top:0}
  h1{font-size:30px;font-weight:800;letter-spacing:-.4px;line-height:1.2;padding-bottom:14px;border-bottom:1px solid var(--br)}
  h1+p{color:var(--dim);font-size:14px;margin-top:10px}
  h2{font-size:21px;font-weight:750;margin:42px 0 14px;padding-top:22px;border-top:1px solid var(--br);scroll-margin-top:14px;color:#fff}
  h3{font-size:16px;font-weight:700;margin:26px 0 10px;color:var(--green);scroll-margin-top:14px}
  h4{font-size:14px;font-weight:700;margin:20px 0 8px;color:var(--cyan)}
  p,li{color:#d6deee}
  strong{color:#fff}
  ul,ol{padding-left:22px}li{margin:4px 0}
  code{background:var(--code);border:1px solid var(--br);border-radius:6px;padding:1.5px 6px;font:13px/1.4 "SF Mono",ui-monospace,"Cascadia Code",Consolas,monospace;color:#a5f3df}
  pre{background:var(--code);border:1px solid var(--br);border-radius:12px;padding:16px 18px;overflow-x:auto;line-height:1.5}
  pre code{background:none;border:none;padding:0;color:#cdd9f0}
  blockquote{margin:16px 0;padding:10px 16px;border-left:3px solid var(--accent);background:rgba(52,211,153,.06);border-radius:0 10px 10px 0;color:var(--dim)}
  table{width:100%;border-collapse:collapse;margin:16px 0;font-size:13.5px;display:block;overflow-x:auto}
  th,td{padding:9px 12px;border:1px solid var(--br);text-align:left;vertical-align:top}
  th{background:#16213f;color:var(--dim);text-transform:uppercase;font-size:11.5px;letter-spacing:.5px;font-weight:700}
  tr:nth-child(even) td{background:rgba(255,255,255,.018)}
  td code{white-space:nowrap}
  hr{border:none;border-top:1px solid var(--br);margin:34px 0}
  .topbar{display:none}
  @media(max-width:860px){
    nav.toc{display:none}
    main{padding:20px 18px 60px}
    .topbar{display:flex;align-items:center;gap:9px;position:sticky;top:0;z-index:5;padding:12px 16px;background:var(--bg2);border-bottom:1px solid var(--br);font-weight:800}
  }
  ::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:#27365a;border-radius:10px}
</style>
</head>
<body>
<div class="topbar"><span class="leaf">🌿</span> Crop Steering — System Guide</div>
<div class="wrap">
  <nav class="toc">
    <div class="brand"><span class="leaf">🌿</span> System Guide</div>
    {{NAV}}
  </nav>
  <main id="doc">
    {{BODY}}
  </main>
</div>
<script>
  // highlight the section currently in view
  var links=[...document.querySelectorAll('nav.toc a')];
  var map={};links.forEach(a=>map[a.getAttribute('href').slice(1)]=a);
  var obs=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){links.forEach(l=>l.classList.remove('active'));var a=map[e.target.id];if(a)a.classList.add('active');}})},{rootMargin:'0px 0px -75% 0px'});
  document.querySelectorAll('main h2[id]').forEach(h=>obs.observe(h));
</script>
</body>
</html>"""

out = TEMPLATE.replace("{{NAV}}", nav).replace("{{BODY}}", body)
for dest in ("SYSTEM_GUIDE.html", "www/SYSTEM_GUIDE.html"):
    open(dest, "w", encoding="utf-8", newline="\n").write(out)
    print(f"wrote {dest} ({len(out)} bytes)")
print(f"sidebar sections: {nav.count('<a ')}")
