#!/usr/bin/env python3
"""Capture PNG screenshots of the standalone dashboards via headless Chrome + CDP.

Injects the HA token into localStorage (so the dashboard connects), waits for live
data, clicks through the views, and writes PNGs into img/. Token comes from HA_TOKEN.
"""
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
OUT = os.path.join(os.path.dirname(__file__), "..", "img")
DESK = BASE + "/local/crop_steering_dashboard.html"
MOB = BASE + "/local/crop_steering_mobile.html"

chrome = next((p for p in [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
] if os.path.exists(p)), None)
if not chrome:
    sys.exit("No Chrome/Edge found")
print("browser:", chrome, file=sys.stderr)

udir = os.path.join(os.environ.get("TEMP", "/tmp"), "cs_shot_profile")
proc = subprocess.Popen([chrome, "--headless=new", "--remote-debugging-port=9222",
    "--remote-allow-origins=*", f"--user-data-dir={udir}", "--window-size=1500,1000",
    "--hide-scrollbars", "--no-first-run", "--disable-gpu", "about:blank"])
time.sleep(3)

def targets():
    return json.load(urllib.request.urlopen("http://localhost:9222/json", timeout=5))

ws_url = None
for _ in range(10):
    try:
        for t in targets():
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
def goto(url): cdp("Page.navigate", {"url": url}); time.sleep(4.5)
def js(expr): return cdp("Runtime.evaluate", {"expression": expr}).get("result", {}).get("value")
def shot(path):
    d = cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["data"]
    open(path, "wb").write(base64.b64decode(d)); print("wrote", path, file=sys.stderr)

os.makedirs(OUT, exist_ok=True)
# --- desktop: load, inject token, reload ---
goto(DESK)
js(f"localStorage.setItem('cs_base','{BASE}');localStorage.setItem('cs_token','{TOK}');'ok'")
goto(DESK)
time.sleep(3)
desk_shots = [("triage", "Dashboard 1.png"), ("zones", "Dashboard 2.png"),
              ("trace", "Dashboard 3.png"), ("control", "Dashboard 4.png"), ("trust", "Dashboard 5.png")]
for view, fn in desk_shots:
    js(f"document.querySelector('[data-t=\\'{view}\\']').click()")
    time.sleep(2)
    shot(os.path.join(OUT, fn))

# --- mobile: emulate phone, load, screenshot Now ---
cdp("Emulation.setDeviceMetricsOverride", {"width": 412, "height": 900, "deviceScaleFactor": 2, "mobile": True})
goto(MOB)
time.sleep(3)
js("document.querySelector('[data-t=\\'now\\']') && document.querySelector('[data-t=\\'now\\']').click()")
time.sleep(2)
shot(os.path.join(OUT, "Mobile 1.png"))
js("document.querySelector('[data-t=\\'zones\\']') && document.querySelector('[data-t=\\'zones\\']').click()")
time.sleep(2)
shot(os.path.join(OUT, "Mobile 2.png"))

ws.close(); proc.terminate()
print("DONE", file=sys.stderr)
