"""A stand-in for Home Assistant's REST API, enough to run the controller app's real image against.

Serves /api/, /api/config, /api/states, /api/services and /api/history from an in-memory table seeded
from the SEED environment variable (JSON: entity id -> state, or [state, attributes]). A switch or
input_boolean service call changes the entity's state as Home Assistant would, and every service call
is logged with the time it arrived. Once the entity named by SLOW_AFTER is switched on, every later
answer waits DELAY seconds first: a slow Home Assistant, from the moment a shot's valve opens.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DELAY = float(os.environ.get("DELAY", "2"))
SLOW_AFTER = os.environ.get("SLOW_AFTER", "")
SLOW = threading.Event()
LOCK = threading.Lock()
STATES = {}


def log(*parts):
    print(f"[fake-ha {time.time():.3f}]", *parts, flush=True)


def put(entity, state, attributes=None):
    old = STATES.get(entity)
    now = datetime.now(timezone.utc).isoformat()
    STATES[entity] = {
        "entity_id": entity,
        "state": str(state),
        "attributes": attributes if attributes is not None else (old or {}).get("attributes", {}),
        "last_changed": old["last_changed"] if old and old["state"] == str(state) else now,
        "last_updated": now,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, code, body):
        if SLOW.is_set():
            time.sleep(DELAY)
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path in ("/api", "/api/"):
            return self._send(200, {"message": "API running."})
        if path == "/api/config":
            return self._send(200, {"time_zone": os.environ.get("HA_TIME_ZONE", "UTC")})
        # The answer is taken under the lock and sent after it, so one slow answer never holds up another.
        with LOCK:
            if path == "/api/states":
                code, answer = 200, list(STATES.values())
            elif path.startswith("/api/states/"):
                found = STATES.get(path[len("/api/states/"):])
                code, answer = (200, found) if found else (404, {"message": "Entity not found."})
            elif path.startswith("/api/history/period/"):
                found = STATES.get(parse_qs(url.query).get("filter_entity_id", [""])[0])
                rows = [{"state": found["state"], "last_changed": found["last_changed"]}] if found else []
                code, answer = 200, [rows] if rows else []
            else:
                code, answer = 404, {"message": "Not found."}
        return self._send(code, answer)

    def do_POST(self):
        path = urlparse(self.path).path
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if path.startswith("/api/states/"):
            entity = path[len("/api/states/"):]
            with LOCK:
                put(entity, body.get("state"), body.get("attributes") or {})
                answer = STATES[entity]
            return self._send(200, answer)
        if path.startswith("/api/services/"):
            domain, service = path[len("/api/services/"):].split("/", 1)
            entity = body.get("entity_id")
            log("CALL", domain, service, json.dumps(body))
            if domain in ("switch", "input_boolean") and service in ("turn_on", "turn_off") and isinstance(entity, str):
                with LOCK:
                    put(entity, "on" if service == "turn_on" else "off")
                if service == "turn_on" and entity == SLOW_AFTER:
                    SLOW.set()
                    log(f"{entity} on: every answer from now waits {DELAY} s")
            return self._send(200, [])
        return self._send(404, {"message": "Not found."})


if __name__ == "__main__":
    for entity, value in json.loads(os.environ.get("SEED", "{}")).items():
        state, attributes = value if isinstance(value, list) else (value, {})
        put(entity, state, attributes)
    log(f"serving {len(STATES)} entities on :8123")
    ThreadingHTTPServer(("0.0.0.0", 8123), Handler).serve_forever()
