#!/usr/bin/env python3
"""Headless-CDP verification of the new AROYA-style overlay chart on the Steering Trace view.
Loads the live dashboard, injects the token, waits for history, then probes drawOverlay()
for runtime errors, exercises the scrubber + the 1W toggle, and writes screenshots to /tmp."""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import websocket

TOK = os.environ.get("HA_TOKEN", "")
BASE = os.environ.get("HA_BASE", "http://homeassistant.local:8123")
DESK = BASE + "/local/f2.html?v=ovlverify"

chrome = next((p for p in [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
] if os.path.exists(p)), None)
if not chrome:
    sys.exit("No Chrome/Edge found")

udir = os.path.join(os.environ.get("TEMP", "/tmp"), "cs_ovl_verify_profile")
proc = subprocess.Popen([chrome, "--headless=new", "--remote-debugging-port=9223",
    "--remote-allow-origins=*", f"--user-data-dir={udir}", "--window-size=1500,1050",
    "--hide-scrollbars", "--no-first-run", "--disable-gpu", "about:blank"])
time.sleep(3)

ws_url = None
for _ in range(12):
    try:
        for t in json.load(urllib.request.urlopen("http://localhost:9223/json", timeout=5)):
            if t.get("type") == "page":
                ws_url = t["webSocketDebuggerUrl"]; break
        if ws_url: break
    except Exception: pass
    time.sleep(1)
if not ws_url:
    proc.terminate(); sys.exit("no CDP page target")

ws = websocket.create_connection(ws_url, timeout=30, max_size=None)
_id = 0
def cdp(method, params=None):
    global _id; _id += 1; mid = _id
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == mid:
            return m.get("result", {})
cdp("Page.enable"); cdp("Runtime.enable")
def goto(url): cdp("Page.navigate", {"url": url}); time.sleep(5)
def js(expr): return cdp("Runtime.evaluate", {"expression": expr}).get("result", {}).get("value")
def shot(path):
    d = cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
    open(path, "wb").write(base64.b64decode(d)); print("wrote", path, file=sys.stderr)

# install a global error trap, load, inject token, reload
goto(DESK)
js("window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));'ok'")
js(f"localStorage.setItem('cs_base','{BASE}');localStorage.setItem('cs_token','{TOK}');'ok'")
goto(DESK)
js("window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));'ok'")

# wait for history to populate (overlay needs HIST)
for _ in range(15):
    n = js("typeof HIST!=='undefined'?(HIST['sensor.crop_steering_zone_1_vwc']||[]).length:0")
    if n and int(n) > 1: break
    time.sleep(2)

# go to the Trace tab where the overlay lives
js("document.querySelector('[data-t=\\'trace\\']').click()")
time.sleep(2)

print("DIAG1:", js("""JSON.stringify({
  histKeys:Object.keys(HIST||{}).length,
  z1vwc:(HIST['sensor.crop_steering_zone_1_vwc']||[]).length,
  z3ec:(HIST['sensor.crop_steering_zone_3_ec']||[]).length,
  ovlCanvas:!!document.getElementById('ovlCanvas'),
  histWindowH:typeof histWindowH!=='undefined'?histWindowH:null
})"""), file=sys.stderr)
print("DRAW:", js("(function(){try{drawOverlay();return 'ok ovl='+(typeof _ovl!=='undefined'&&_ovl?'set':'null')}catch(e){return 'ERR: '+e.message}})()"), file=sys.stderr)
shot("/tmp/ovl_3d.png")

# exercise the scrubber (simulate hover near right third)
print("HOVER:", js("""(function(){try{drawOverlay(900);var t=document.getElementById('ovlTip');
  return 'disp='+(t?t.style.display:'?')+' | '+(t?t.innerText.replace(/\\n/g,' ').slice(0,120):'no-tip')}catch(e){return 'ERR: '+e.message}})()"""), file=sys.stderr)
shot("/tmp/ovl_scrub.png")

# 1W toggle
js("setHistWindow(168)")
time.sleep(4)
js("document.querySelector('[data-t=\\'trace\\']').click()")
time.sleep(2)
print("DRAW_1W:", js("(function(){try{drawOverlay();return 'ok win='+histWindowH}catch(e){return 'ERR: '+e.message}})()"), file=sys.stderr)
shot("/tmp/ovl_1w.png")

print("ERRORS:", js("JSON.stringify(window.__errs||[])"), file=sys.stderr)
ws.close(); proc.terminate()
print("DONE", file=sys.stderr)
