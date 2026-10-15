"""A stand-in for Home Assistant's REST API, enough to run the controller app's real image against.

Serves /api/, /api/config, /api/states, /api/services and /api/history from an in-memory table seeded
from the SEED environment variable (JSON: entity id -> state, or [state, attributes]), under /api and,
for the app's own address (http://supervisor/core/api), under /core/api. A switch or input_boolean
service call changes the entity's state as Home Assistant would, and every request is logged as
`REQ <method> <path> <status>` with the time it arrived. Once the entity named by SLOW_AFTER is switched
on, every later answer waits DELAY seconds first: a slow Home Assistant, from the moment a shot's valve
opens.

Refusals, as a test asks for them: REFUSE (401 or 403) answers every request with it (only those carrying
the token REFUSE_TOKEN, when that is set), for the first REFUSE_FOR_S seconds when that is set; every
state written is logged as `STATE <entity> <json>`. ADMIN_ONLY_WRITES=1 answers 401 to a state write, as Home
Assistant does for a token whose user is not an administrator. TIME_ZONE sets /api/config's time zone,
CONFIG_STATUS its status, and NO_TIME_ZONE=1 leaves it out of the answer.
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
REFUSE = int(os.environ.get("REFUSE") or 0)
REFUSE_FOR_S = float(os.environ.get("REFUSE_FOR_S") or 0)
ADMIN_ONLY_WRITES = os.environ.get("ADMIN_ONLY_WRITES") == "1"
STARTED = time.monotonic()
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


def refusing(headers):
    token = os.environ.get("REFUSE_TOKEN")
    if token and headers.get("Authorization") != f"Bearer {token}":
        return False
    return REFUSE and (not REFUSE_FOR_S or time.monotonic() - STARTED < REFUSE_FOR_S)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _path(self):
        url = urlparse(self.path)
        path = url.path[len("/core"):] if url.path.startswith("/core/api") else url.path
        return url, path

    def _send(self, code, body):
        log("REQ", self.command, self._path()[1], code)
        if SLOW.is_set():
            time.sleep(DELAY)
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url, path = self._path()
        if refusing(self.headers):
            return self._send(REFUSE, {"message": "refused"})
        if path in ("/api", "/api/"):
            return self._send(200, {"message": "API running."})
        if path == "/api/config":
            body = {} if os.environ.get("NO_TIME_ZONE") == "1" else {"time_zone": os.environ.get("TIME_ZONE", "UTC")}
            return self._send(int(os.environ.get("CONFIG_STATUS") or 200), body)
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
        _url, path = self._path()
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if refusing(self.headers):
            return self._send(REFUSE, {"message": "refused"})
        if path.startswith("/api/states/"):
            if ADMIN_ONLY_WRITES:
                return self._send(401, {"message": "Unauthorized"})
            entity = path[len("/api/states/"):]
            log("STATE", entity, json.dumps(body))
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
