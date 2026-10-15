"""How the controller tells the Home Assistant app from a standalone container, where Home Assistant is,
which token it uses, and the checks it makes before it starts (runtime_env.preflight).

The controller's __main__ runs preflight() before it builds anything; the app gets exactly the address,
token, options and state path it always had. preflight() is called directly here, against a Home
Assistant that answers each request as a test says and a test clock: no Docker, no network. The options
reader (load_options) is tested the same way: the app's file as it is, a container's checked.

Container mode never exits on a refused token (a 401 or 403): exiting hands the retry to the restart
policy, which sends the same refused token again on every start and walks into Home Assistant's IP
ban. It parks. With nothing recorded by the previous run it sends nothing more; with a shot or a dose
recorded it asks again on a schedule, because the refusal may come from a proxy that recovers and
water may still be running. Settings that are wrong before Home Assistant is asked exit 2.
"""
import ast
import json
import os
import pathlib
import signal
import time

import pytest
import requests

import runtime_env

PKG = pathlib.Path(runtime_env.__file__).parent
TOKEN = "s3cr3t-token-value"
BASE = "http://ha:8123/api"
ROOT, CONFIG, PROBE = "/", "/config", "/states/" + runtime_env.RUNTIME_ENTITY
APP = {"F2_RUNTIME": "addon", "SUPERVISOR_TOKEN": "supervisor-token"}
HOUR = 3600.0
KNOWN_ZONES = {"UTC", "Pacific/Auckland"}


class Hour(Exception):
    """The test clock reached its end while the preflight was parked."""


class Clock:
    def __init__(self, until=HOUR):
        self.seconds, self.until, self.on_sleep = 0.0, until, None

    def sleep(self, seconds):
        assert seconds > 0
        self.seconds += seconds
        if self.on_sleep:
            self.on_sleep(self)
        if self.seconds > self.until:
            raise Hour

    def monotonic(self):
        return self.seconds


class Answer:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeHA:
    """Home Assistant's REST API as one test needs it. `answer(method, path, seconds)` returns a status,
    a (status, body) pair or an exception to raise; None keeps the healthy answer."""

    HEALTHY = {("GET", ROOT): (200, {"message": "API running."}), ("GET", CONFIG): (200, {"time_zone": "UTC"}),
               ("POST", PROBE): (201, {})}

    def __init__(self, clock, answer=None):
        self.clock, self.answer, self.sent = clock, answer or (lambda *a: None), []

    def _send(self, method, url, headers, data):
        path = url.split("/api", 1)[1]
        self.headers = headers
        given = self.answer(method, path, self.clock.seconds)
        if given is None:
            given = self.HEALTHY.get((method, path), (404, {"message": "Not found"}))
        status = given if isinstance(given, (int, Exception)) else given[0]
        self.sent.append((self.clock.seconds, method, path, status, data))
        if isinstance(given, Exception):
            raise given
        return Answer(given) if isinstance(given, int) else Answer(*given)

    def get(self, url, headers=None, timeout=None):
        return self._send("GET", url, headers, None)

    def post(self, url, headers=None, json=None, timeout=None):
        return self._send("POST", url, headers, json)

    def refused(self):
        return [s for s in self.sent if s[3] in (401, 403)]


@pytest.fixture(autouse=True)
def _known_zones(monkeypatch):
    """Which time zones this process "follows" is real only in the tests that change the process's own
    zone (test_an_empty_tz_*); here a zone is known when it is in KNOWN_ZONES."""
    monkeypatch.setattr(runtime_env, "_follows", lambda zone: zone in KNOWN_ZONES)
    monkeypatch.setattr(runtime_env, "_adopt", lambda zone: zone in KNOWN_ZONES)


@pytest.fixture
def box(tmp_path):
    """A container's environment, with its data folder in tmp_path."""
    return {"F2_RUNTIME": "container", "HA_URL": "http://ha:8123", "HA_TOKEN": TOKEN, "TZ": "UTC",
            "F2_STATE_PATH": str(tmp_path / "state.json"), "F2_DATA_DIR": str(tmp_path)}


def run(env, answer=None, until=HOUR, close_only=None):
    """preflight() on the test clock: ("returned" | "parked" | exit code, the fake Home Assistant)."""
    clock = Clock(until)
    fake = FakeHA(clock, answer)
    try:
        runtime_env.preflight(close_only, env, version="9.9.9", http=fake, sleep=clock.sleep,
                              clock=clock.monotonic)
    except Hour:
        return "parked", fake
    except SystemExit as e:
        return e.code, fake
    return "returned", fake


def refuse(status, path=ROOT, until=None):
    """Refuse `path` with `status` (every request when path is None), until `until` seconds if given."""
    def answer(method, asked, seconds):
        if (path is None or asked == path) and (until is None or seconds < until):
            return status
        return None
    return answer


# ------------------------------------------------------------------ the runtime, the stop budget, BASE, the token
@pytest.mark.parametrize("env, runtime, named", [
    (APP, "addon", None),
    ({"SUPERVISOR_TOKEN": "t"}, "container", "F2_RUNTIME is unset"),
    ({"F2_RUNTIME": "addon"}, "container", "no SUPERVISOR_TOKEN"),
    ({**APP, "HA_URL": "http://ha:8123"}, "container", "HA_URL is set"),
    ({"F2_RUNTIME": "container", "SUPERVISOR_TOKEN": "t"}, "container", None),
    ({"F2_RUNTIME": "app", "SUPERVISOR_TOKEN": "t"}, "container", "F2_RUNTIME is app"),
    ({}, "container", "F2_RUNTIME is unset"),
])
def test_only_all_three_signs_together_make_the_app(env, runtime, named, box, capsys):
    assert runtime_env.runtime(env) == runtime
    if runtime == "container":
        run({**{k: v for k, v in box.items() if k != "F2_RUNTIME"}, **env})
        first = capsys.readouterr().out.splitlines()[0]
        assert first == "[f2-control] runtime: container" + (f" (not the app: {named})" if named else "")


def test_the_app_keeps_its_25_s_stop_and_a_container_gets_75_s():
    assert runtime_env.stop_budget(APP) == 25.0
    assert runtime_env.stop_budget({"F2_RUNTIME": "container"}) == 75.0
    assert runtime_env.stop_budget({**APP, "HA_URL": "http://ha:8123"}) == 75.0
    assert runtime_env.stop_budget({**APP, "F2_STOP_BUDGET_S": "40"}) == 40.0


@pytest.mark.parametrize("url, base", [
    (None, "http://supervisor/core/api"),
    ("", "http://supervisor/core/api"),
    ("http://ha:8123", "http://ha:8123/api"),
    ("http://ha:8123/", "http://ha:8123/api"),
    ("http://ha:8123/api", "http://ha:8123/api"),
    ("http://ha:8123/api/", "http://ha:8123/api"),
    ("  http://ha:8123 \n", "http://ha:8123/api"),
    ("https://ha.example:8443", "https://ha.example:8443/api"),
    ("ftp://ha", "ftp://ha/api"),  # the preflight refuses it (test_a_container_exits_2_*)
])
def test_the_api_address_gets_api_added_once(url, base):
    assert runtime_env.resolve_base({} if url is None else {"HA_URL": url}) == base


def test_the_apps_token_is_the_supervisors_exactly_as_before():
    env = {**APP, "HA_TOKEN": "other"}
    assert runtime_env.resolve_token(env) == ("supervisor-token", "SUPERVISOR_TOKEN")


def test_a_containers_token_is_ha_token_then_the_file_then_the_supervisors(tmp_path):
    secret = tmp_path / "ha_token.txt"
    secret.write_text("  from-file \n")
    env = {"F2_RUNTIME": "container", "HA_TOKEN": "from-env", "HA_TOKEN_FILE": str(secret),
           "SUPERVISOR_TOKEN": "from-supervisor"}
    assert runtime_env.resolve_token(env) == ("from-env", "HA_TOKEN")
    del env["HA_TOKEN"]
    assert runtime_env.resolve_token(env) == ("from-file", "HA_TOKEN_FILE")
    del env["HA_TOKEN_FILE"]
    assert runtime_env.resolve_token(env) == ("from-supervisor", "SUPERVISOR_TOKEN")
    del env["SUPERVISOR_TOKEN"]
    assert runtime_env.resolve_token(env) == ("", None)


@pytest.mark.parametrize("kind", ["missing", "a directory", "empty", "not text"])
def test_a_bad_token_file_gives_no_token(tmp_path, kind):
    path = tmp_path / "ha_token.txt"
    if kind == "a directory":
        path.mkdir()
    elif kind == "empty":
        path.write_text(" \n")
    elif kind == "not text":
        path.write_bytes(b"\xff\xfe\x00")
    assert runtime_env.resolve_token({"HA_TOKEN_FILE": str(path)}) == ("", None)


def test_importing_it_reads_nothing_and_never_raises(monkeypatch):
    import importlib

    monkeypatch.setenv("HA_TOKEN_FILE", "/nonexistent/token")
    monkeypatch.setenv("HA_URL", "ftp://nowhere")
    monkeypatch.setenv("F2_STOP_BUDGET_S", "soon")
    importlib.reload(runtime_env)


def test_the_controller_checks_before_it_builds_anything():
    """__main__: preflight (with the close-only start for a non-administrator's token), then Controller()."""
    tree = ast.parse((PKG / "controller.py").read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test))
    assert [ast.unparse(s) for s in main.body] == [
        "runtime_env.preflight(close_only_start, version=CONTROLLER_VERSION)",
        "Controller().run()",
    ]


# ------------------------------------------------------------------ the app: one GET, logged, nothing more
@pytest.mark.parametrize("answer", [None, refuse(401), refuse(503), refuse(requests.ConnectionError("refused"))])
def test_the_app_asks_once_logs_and_carries_on_whatever_the_answer(tmp_path, answer, capsys):
    env = {**APP, "TZ": "Not/AZone", "F2_STATE_PATH": str(tmp_path / "missing" / "state.json")}
    outcome, fake = run(env, answer)
    assert outcome == "returned"
    assert fake.headers["Authorization"] == "Bearer supervisor-token"
    assert [(method, path) for _t, method, path, _s, _d in fake.sent] == [("GET", ROOT)]
    out = capsys.readouterr().out
    assert "runtime: addon" in out and "stop budget: 25 s" in out and "base: http://supervisor/core/api" in out
    assert "supervisor-token" not in out
    assert os.environ.get("TZ") != "Not/AZone"


# ------------------------------------------------------------------ a container: settings wrong before HA is asked
def _token_file(tmp_path, kind):
    path = tmp_path / "ha_token.txt"
    if kind == "a directory":
        path.mkdir()
    elif kind == "empty":
        path.write_text("\n")
    return str(path)


@pytest.mark.parametrize("change, said", [
    ({"HA_TOKEN": ""}, "no Home Assistant token"),
    ({"HA_TOKEN": "", "HA_TOKEN_FILE": "missing"}, "does not exist"),
    ({"HA_TOKEN": "", "HA_TOKEN_FILE": "a directory"}, "is a directory"),
    ({"HA_TOKEN": "", "HA_TOKEN_FILE": "empty"}, "is empty"),
    ({"HA_TOKEN": "", "HA_TOKEN_FILE": "missing", "SUPERVISOR_TOKEN": "t"}, "does not exist"),
    ({"HA_URL": ""}, "HA_URL is not set"),
    ({"HA_URL": "ftp://ha:8123"}, "is not an http:// or https:// address"),
    ({"HA_URL": "ha:8123"}, "is not an http:// or https:// address"),
    ({"F2_STATE_PATH": "no-such-folder"}, "is not writable"),
    ({"TZ": "Not/AZone"}, "TZ=Not/AZone is not a time zone this image knows"),
])
def test_a_container_exits_2_on_a_wrong_setting_before_asking_home_assistant(box, tmp_path, change, said, capsys):
    env = {**box, **change}
    if "HA_TOKEN_FILE" in change:
        env["HA_TOKEN_FILE"] = _token_file(tmp_path, change["HA_TOKEN_FILE"])
    if change.get("F2_STATE_PATH"):
        env["F2_STATE_PATH"] = str(tmp_path / "no-such-folder" / "state.json")
    outcome, fake = run(env)
    assert outcome == 2
    assert fake.sent == []
    assert said in capsys.readouterr().out


def test_the_token_never_reaches_the_log_and_neither_does_a_password_in_ha_url(box, capsys):
    outcome, _fake = run({**box, "HA_URL": "http://me:hunter2@ha:8123"}, refuse(401))
    out = capsys.readouterr().out
    assert TOKEN not in out and "hunter2" not in out
    assert "base: http://***@ha:8123/api" in out


# ------------------------------------------------------------------ a container: reaching Home Assistant
def test_an_accepted_administrator_token_returns_after_the_admin_probe(box, tmp_path):
    outcome, fake = run(box)
    assert outcome == "returned"
    assert fake.headers["Authorization"] == f"Bearer {TOKEN}"
    assert [(m, p) for _t, m, p, _s, _d in fake.sent] == [("GET", ROOT), ("POST", PROBE)]
    assert fake.sent[1][4] == {"state": "container", "attributes": {"controller_version": "9.9.9"}}
    assert sorted(os.listdir(tmp_path)) == []  # the data folder check leaves nothing behind


@pytest.mark.parametrize("trouble", [503, requests.ConnectionError("refused"), requests.exceptions.SSLError("x"),
                                     requests.ConnectionError("NameResolutionError: Name does not resolve")])
def test_home_assistant_still_booting_is_asked_every_10_s_and_nothing_is_built(box, trouble, capsys):
    outcome, fake = run(box, refuse(trouble, path=None, until=95))
    assert outcome == "returned"
    gets = [t for t, m, p, _s, _d in fake.sent if (m, p) == ("GET", ROOT)]
    assert gets == [10.0 * n for n in range(11)]  # every 10 s until it answers at 100 s
    out = capsys.readouterr().out
    assert out.count("is not answering yet") == 2  # logged once a minute
    if isinstance(trouble, requests.exceptions.SSLError):
        assert "TLS error" in out
    elif "resolve" in str(trouble):
        assert "does not resolve" in out


@pytest.mark.parametrize("answer", [
    refuse(404),
    refuse(400),
    lambda m, p, s: (200, ValueError("a proxy's landing page")) if p == ROOT else None,
    lambda m, p, s: (200, {"message": "Welcome"}) if p == ROOT else None,
    lambda m, p, s: 404 if p == PROBE else None,
])
def test_an_address_that_is_not_home_assistants_api_exits_2(box, answer, capsys):
    outcome, _fake = run(box, answer)
    assert outcome == 2
    assert "HA_URL does not point at Home Assistant's API" in capsys.readouterr().out


# ------------------------------------------------------------------ a refused token: parked, nothing recorded
NOTHING_RECORDED = {
    "state.json": {"default": {"1": {"phase": "P2"}, "_shot_inflight": None}},
    "dosing_state.json": {"rooms": {"default": {"inflight": None}}},
}


@pytest.mark.parametrize("files", [{}, NOTHING_RECORDED])
@pytest.mark.parametrize("status, path, said", [
    (401, ROOT, "HA rejected the token: GET http://ha:8123/api/ -> HTTP 401"),
    (401, PROBE, "the token's user must be an administrator: POST http://ha:8123/api/states/"),
    (403, ROOT, "probably an IP ban"),
    (403, PROBE, "probably an IP ban"),
])
def test_a_refused_token_with_nothing_recorded_sends_one_request_and_parks(
    box, tmp_path, files, status, path, said, capsys
):
    for name, doc in files.items():
        (tmp_path / name).write_text(json.dumps(doc))
    called = []
    outcome, fake = run(box, refuse(status, path), close_only=lambda: called.append(1))
    assert outcome == "parked"  # a simulated hour, never an exit
    assert len(fake.refused()) == 1
    assert fake.sent[-1][0] == 0.0  # nothing at all after the first minute
    assert called == []
    out = capsys.readouterr().out
    assert said in out and "nothing more is sent" in out


def test_a_new_token_in_the_file_while_parked_exits_0(box, tmp_path):
    secret = tmp_path / "ha_token.txt"
    secret.write_text(TOKEN)
    env = {**box, "HA_TOKEN": "", "HA_TOKEN_FILE": str(secret)}
    clock = Clock()
    clock.on_sleep = lambda c: secret.write_text("a-new-token") if c.seconds >= 300 else None
    fake = FakeHA(clock, refuse(401))
    with pytest.raises(SystemExit) as stopped:
        runtime_env.preflight(None, env, http=fake, sleep=clock.sleep, clock=clock.monotonic)
    assert stopped.value.code == 0
    assert 300 <= clock.seconds <= 330  # seen within 30 s
    assert len(fake.sent) == 1


@pytest.mark.skipif(not hasattr(signal, "raise_signal"), reason="needs signal.raise_signal")
def test_sigterm_while_parked_exits_0_at_once(box):
    before = signal.getsignal(signal.SIGTERM)
    clock = Clock()
    clock.on_sleep = lambda c: signal.raise_signal(signal.SIGTERM) if c.seconds >= 120 else None
    fake = FakeHA(clock, refuse(401))
    with pytest.raises(SystemExit) as stopped:
        runtime_env.preflight(None, box, http=fake, sleep=clock.sleep, clock=clock.monotonic)
    assert stopped.value.code == 0 and clock.seconds == 120
    assert signal.getsignal(signal.SIGTERM) == before  # put back once the preflight is over


# ------------------------------------------------------------------ a refused token with a record the last run left
SHOT = {"default": {"1": {"phase": "P2"}, "_shot_inflight": {"valve": "switch.zone_1_valve", "zone": 1}}}
DOSE = {"rooms": {"default": {"inflight": {"kind": "dose", "off": ["switch.dose_pump"]}}}}
RECORDS = {
    "a shot in flight": {"state.json": json.dumps(SHOT)},
    "a shot in an old single-room file": {"state.json": json.dumps({"1": {}, "_shot_inflight": {"zone": 1}})},
    "a dose in flight": {"dosing_state.json": json.dumps(DOSE)},
    "a corrupt dosing file": {"dosing_state.json": '{"rooms": {"default": '},
    "a corrupt state file": {"state.json": "{not json"},
}


def seed(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize("record", sorted(RECORDS))
def test_with_a_record_a_refusal_that_clears_is_asked_again_each_minute_and_then_carries_on(box, tmp_path, record):
    before = seed(tmp_path, RECORDS[record])
    outcome, fake = run(box, refuse(403, path=None, until=180))
    assert outcome == "returned"
    assert [(t, m, p, s) for t, m, p, s, _d in fake.sent] == [
        (0.0, "GET", ROOT, 403), (60.0, "GET", ROOT, 403), (120.0, "GET", ROOT, 403),
        (180.0, "GET", ROOT, 200), (180.0, "POST", PROBE, 201),
    ]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before  # read only, no .bad file


@pytest.mark.parametrize("record", sorted(RECORDS))
def test_with_a_record_a_token_refused_for_good_is_asked_10_times_in_10_min_then_4_an_hour(box, tmp_path, record):
    before = seed(tmp_path, RECORDS[record])
    outcome, fake = run(box, refuse(401), until=600 + HOUR)
    assert outcome == "parked"
    assert all((m, p, s) == ("GET", ROOT, 401) for _t, m, p, s, _d in fake.sent)
    times = [t for t, *_rest in fake.sent]
    assert len([t for t in times if t <= 600]) == 1 + 10
    assert [t for t in times if t > 600] == [1500.0, 2400.0, 3300.0, 4200.0]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_a_non_admin_token_with_a_record_closes_it_once_and_parks(box, tmp_path, capsys):
    seed(tmp_path, RECORDS["a shot in flight"])
    called = []
    outcome, fake = run(box, refuse(401, PROBE), close_only=lambda: called.append(1))
    assert outcome == "parked"
    assert len(called) == 1
    assert [(m, p, s) for _t, m, p, s, _d in fake.sent] == [("GET", ROOT, 200), ("POST", PROBE, 401)]
    assert "closing it with this token" in capsys.readouterr().out


@pytest.mark.parametrize("status, path, record", [(401, ROOT, True), (403, PROBE, True), (401, PROBE, False)])
def test_close_only_runs_for_a_non_admin_token_with_a_record_and_nothing_else(box, tmp_path, status, path, record):
    if record:
        seed(tmp_path, RECORDS["a shot in flight"])
    called = []
    outcome, _fake = run(box, refuse(status, path), close_only=lambda: called.append(1))
    assert outcome == "parked" and called == []


def test_a_non_admin_token_with_a_record_and_no_close_only_asks_on_the_schedule(box, tmp_path):
    seed(tmp_path, RECORDS["a shot in flight"])
    outcome, fake = run(box, refuse(401, PROBE), until=600)
    assert outcome == "parked"
    probes = [t for t, m, p, s, _d in fake.sent if (m, p, s) == ("POST", PROBE, 401)]
    assert probes == [60.0 * n for n in range(11)]


# ------------------------------------------------------------------ the time zone
@pytest.mark.parametrize("trouble", [
    requests.ConnectionError("refused"), 500, (200, {"version": "x"}), (200, {"time_zone": "Mars/Olympus"}),
])
def test_an_empty_tz_waits_for_home_assistants_zone_and_then_exits_2(box, trouble, capsys):
    env = {**box, "TZ": "", "F2_TZ_WAIT_S": "60"}
    outcome, fake = run(env, lambda m, p, s: trouble if p == CONFIG else None)
    assert outcome == 2
    assert [t for t, m, p, _s, _d in fake.sent if p == CONFIG] == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    assert not [s for s in fake.sent if s[2] == PROBE]  # nothing more once it can't run on the right zone
    assert "set TZ in .env to it" in capsys.readouterr().out


def test_an_empty_tz_adopts_home_assistants_zone_once_it_can_be_read(box):
    env = {**box, "TZ": ""}
    outcome, fake = run(env, lambda m, p, s: 500 if p == CONFIG and s < 30 else
                        ((200, {"time_zone": "Pacific/Auckland"}) if p == CONFIG else None))
    assert outcome == "returned"
    assert [(t, p) for t, _m, p, _s, _d in fake.sent] == [(0.0, ROOT), (0.0, CONFIG), (10.0, CONFIG),
                                                          (20.0, CONFIG), (30.0, CONFIG), (30.0, PROBE)]


def test_a_refused_token_on_the_zone_request_parks_too(box):
    outcome, fake = run({**box, "TZ": ""}, refuse(401, CONFIG))
    assert outcome == "parked" and len(fake.refused()) == 1


@pytest.fixture
def real_zone(monkeypatch):
    """The real zone checks, on the process's own time zone, which is put back afterwards."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX only")
    monkeypatch.setattr(runtime_env, "_follows", REAL_FOLLOWS)
    monkeypatch.setattr(runtime_env, "_adopt", REAL_ADOPT)
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


REAL_FOLLOWS, REAL_ADOPT = runtime_env._follows, runtime_env._adopt


def test_an_empty_tz_really_moves_the_process_onto_home_assistants_zone(box, real_zone, capsys):
    assert time.localtime().tm_gmtoff == 0
    outcome, _fake = run({**box, "TZ": ""}, lambda m, p, s: (200, {"time_zone": "Pacific/Auckland"})
                         if p == CONFIG else None)
    assert outcome == "returned"
    assert time.localtime().tm_gmtoff in (12 * 3600, 13 * 3600)
    assert "adopted Home Assistant's zone Pacific/Auckland" in capsys.readouterr().out


def test_a_tz_the_image_does_not_know_really_exits_2(box, real_zone):
    os.environ["TZ"] = "Not/AZone"
    time.tzset()
    outcome, fake = run({**box, "TZ": "Not/AZone"})
    assert outcome == 2 and fake.sent == []


# ------------------------------------------------------------------ paths
def test_state_and_options_follow_the_data_folder_and_the_test_seam_still_wins():
    assert runtime_env.state_path({}) == "/data/state.json"
    assert runtime_env.options_path({}) == "/data/options.json"
    box = {"F2_DATA_DIR": "/srv/cs"}
    assert runtime_env.state_path(box) == os.path.join("/srv/cs", "state.json")
    assert runtime_env.options_path(box) == os.path.join("/srv/cs", "options.json")
    seam = {**box, "F2_STATE_PATH": "/tmp/t/state.json", "F2_OPTIONS_PATH": "/etc/cs.json"}
    assert runtime_env.state_path(seam) == "/tmp/t/state.json"  # dosing_state.json and jev_* go beside it
    assert runtime_env.options_path(seam) == "/etc/cs.json"


def test_the_controller_keeps_its_state_where_runtime_env_says(monkeypatch, tmp_path):
    import controller

    monkeypatch.delenv("F2_STATE_PATH")
    monkeypatch.setenv("F2_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(controller, "load_options", lambda: {})
    monkeypatch.setattr(controller, "ha_get_all", lambda: [])
    monkeypatch.setattr(controller, "ha_get", lambda entity, timeout=8: controller.HAState())
    monkeypatch.setattr(controller, "ha_set", lambda *a, **k: None)
    monkeypatch.setattr(controller, "ha_call", lambda *a, **k: True)
    c = controller.Controller()
    assert c._state_path == str(tmp_path / "state.json")
    assert c.dosing.path == str(tmp_path / "dosing_state.json")


# ------------------------------------------------------------------ options
FIXTURES = pathlib.Path(__file__).parents[3] / "tests_ha" / "fixtures"
LINEAGE = sorted(FIXTURES.glob("options_*.json"))


def _schema_types():
    import yaml

    config = yaml.safe_load((PKG.parent / "config.yaml").read_text(encoding="utf-8"))
    return {k: "[str]" if v == ["str"] else v for k, v in config["schema"].items()}, config["options"]


def test_option_types_are_the_apps_schema_plus_the_code_only_keys():
    """U3: a new option in config.yaml without its type here (or the other way round) fails."""
    schema, _ = _schema_types()
    code_only = {"feed_grace_min": "float", "blind_fallback_min": "float", "zones": "dict", "hardware": "dict"}
    assert runtime_env.OPTION_TYPES == {**schema, **code_only}
    assert runtime_env.SECRET_KEYS == {k for k, t in schema.items() if t.startswith("password")}


def _options(tmp_path, content, env=None, container=False):
    path = tmp_path / "options.json"
    if content is not None:
        path.write_text(content if isinstance(content, str) else json.dumps(content))
    base = ({"F2_RUNTIME": "container", "HA_URL": "http://ha:8123"} if container else dict(APP))
    lines = []
    opts = runtime_env.load_options({**base, "F2_OPTIONS_PATH": str(path), **(env or {})}, lines.append)
    return opts, "\n".join(lines)


@pytest.mark.parametrize("fixture", LINEAGE, ids=lambda p: p.stem)
def test_an_old_apps_options_load_exactly_as_written_in_both_modes(tmp_path, fixture):
    """U1 and U15 (i): what each old app wrote loads equal, value for value and type for type."""
    written = json.loads(fixture.read_text(encoding="utf-8"))["options"]
    for container in (False, True):
        opts, _ = _options(tmp_path, written, container=container)
        assert opts == written
        assert {k: type(v) for k, v in opts.items()} == {k: type(v) for k, v in written.items()}


def test_this_versions_own_defaults_load_exactly_in_both_modes(tmp_path):
    _, defaults = _schema_types()
    for container in (False, True):
        opts, _ = _options(tmp_path, defaults, container=container)
        assert opts == defaults and {k: type(v) for k, v in opts.items()} == {k: type(v) for k, v in defaults.items()}


@pytest.mark.parametrize("content", [None, "{trunc", "", "[1, 2]"])
def test_the_app_reads_its_file_as_it_always_did(tmp_path, content):
    opts, _ = _options(tmp_path, content)
    assert opts == ({} if content in (None, "{trunc", "") else [1, 2])


@pytest.mark.parametrize("var, value, key, expected", [
    ("F2_OPT_NUM_ZONES", " 4 ", "num_zones", 4),
    ("F2_OPT_LOOP_SECONDS", "30.5", "loop_seconds", 30.5),
    ("F2_OPT_NOTIFY_MIN", "15", "notify_min", 15.0),
    ("F2_OPT_JEV_ENABLED", "Off", "jev_enabled", False),
    ("F2_OPT_JEV_ENABLED", "YES", "jev_enabled", True),
    ("F2_OPT_NOTIFY_SERVICE", " notify.phone ", "notify_service", " notify.phone "),
    ("F2_OPT_HOLD_ENTITIES", "input_boolean.flush, input_boolean.fill,", "hold_entities",
     ["input_boolean.flush", "input_boolean.fill"]),
    ("F2_OPT_HOLD_ENTITIES", '["input_boolean.flush"]', "hold_entities", ["input_boolean.flush"]),
    ("F2_OPT_HOLD_ENTITIES", "", "hold_entities", []),
    ("F2_OPT_BRAIN_PROVIDER", "auto", "brain_provider", "auto"),
    ("F2_OPT_BRAIN_PROVIDER", "jev_legacy", "brain_provider", "jev_legacy"),
    ("F2_OPT_ANTHROPIC_DAILY_BUDGET_USD", "2.5", "anthropic_daily_budget_usd", 2.5),
    ("F2_OPT_BRAIN_DRY_RUN", "true", "brain_dry_run", True),
])
def test_an_environment_value_takes_its_options_type_and_wins_over_the_file(tmp_path, var, value, key, expected):
    """U2, accepted: each schema type from its string form."""
    for container in (False, True):
        opts, log = _options(tmp_path, {"num_zones": 3}, {var: value}, container)
        assert opts[key] == expected and type(opts[key]) is type(expected)
        assert key in log.split("env (", 1)[1]


@pytest.mark.parametrize("var, value, said", [
    ("F2_OPT_NUM_ZONES", "3.5", "expected a whole number"),
    ("F2_OPT_LOOP_SECONDS", "sixty", "expected a number"),
    ("F2_OPT_LOOP_SECONDS", "nan", "expected a number"),
    ("F2_OPT_LOOP_SECONDS", "", "expected a number"),
    ("F2_OPT_JEV_ENABLED", "maybe", "expected true or false"),
    ("F2_OPT_HOLD_ENTITIES", "[1, 2]", "expected a JSON list of entity ids"),
    ("F2_OPT_HOLD_ENTITIES", "input_boolean.flush input_boolean.fill", "is not an entity id"),
    ("F2_OPT_BRAIN_PROVIDER", "claude", "expected one of auto, rules, claude_haiku, jev_legacy"),
    ("F2_OPT_ANTHROPIC_DAILY_BUDGET_USD", "-1", "expected a number from 0 to 1000"),
])
def test_an_environment_value_that_cant_be_used_stops_a_container_and_is_left_out_on_the_app(tmp_path, var, value, said):
    """U2, refused: a container names the variable and stops; the app logs it and keeps the file's value."""
    with pytest.raises(runtime_env.OptionsError, match=f"option {var}: .*{said}"):
        _options(tmp_path, {}, {var: value}, container=True)
    if said == "is not an entity id":
        return  # only a container checks the entity-id form, as only its file is not checked by the Supervisor
    opts, log = _options(tmp_path, {"num_zones": 3}, {var: value})
    assert f"option {var}" in log
    assert opts.get("num_zones") == 3


def test_unknown_and_file_only_variables_are_named_and_ignored(tmp_path):
    opts, log = _options(tmp_path, None, {"F2_OPT_LIGHTS_ON_HOUR_TYPO": "6", "F2_OPT_ZONES": "{}"}, container=True)
    assert opts == {}
    assert "option F2_OPT_LIGHTS_ON_HOUR_TYPO: unknown, ignored" in log
    assert "option F2_OPT_ZONES: set it in the options file" in log


SENTINEL = "sk-SENTINEL-do-not-print"


@pytest.mark.parametrize("container", [False, True])
def test_a_secret_comes_from_its_variable_or_a_file_and_is_only_ever_logged_as_set(tmp_path, container, capsys):
    """U7, the reader half: F2_OPT_<KEY> and F2_OPT_<KEY>_FILE, only for a password, never in the log."""
    secret = tmp_path / "cf_token"
    secret.write_text(SENTINEL + "\n")
    opts, log = _options(tmp_path, None, {"F2_OPT_CF_API_TOKEN_FILE": str(secret)}, container)
    assert opts == {"cf_api_token": SENTINEL}
    assert "cf_api_token=<set>" in log and "typesafe_api_key=<unset>" in log
    opts, log = _options(tmp_path, None, {"F2_OPT_CF_API_TOKEN": SENTINEL, "F2_OPT_CF_API_TOKEN_FILE": "/nope"},
                         container)
    assert opts == {"cf_api_token": SENTINEL}
    opts, log2 = _options(tmp_path, None, {"F2_OPT_INSTANCE_NAME_FILE": str(secret)}, container)
    assert opts == {} and "F2_OPT_INSTANCE_NAME_FILE: unknown" in log2  # _FILE is for secrets only
    assert SENTINEL not in log + log2 + capsys.readouterr().out


@pytest.mark.parametrize("container", [False, True])
def test_the_anthropic_key_comes_from_its_option_variable_or_the_usual_alias(tmp_path, container, capsys):
    """F2_OPT_ANTHROPIC_API_KEY(_FILE) over ANTHROPIC_API_KEY over the options file, only ever logged as set."""
    key = tmp_path / "anthropic"
    key.write_text(SENTINEL + "-file\n")
    opts, log = _options(tmp_path, {"anthropic_api_key": "from-the-file"}, {"ANTHROPIC_API_KEY": SENTINEL}, container)
    assert opts["anthropic_api_key"] == SENTINEL and "anthropic_api_key=<set>" in log
    opts, log2 = _options(tmp_path, None, {"ANTHROPIC_API_KEY": "alias", "F2_OPT_ANTHROPIC_API_KEY_FILE": str(key)},
                          container)
    assert opts["anthropic_api_key"] == SENTINEL + "-file"
    opts, _ = _options(tmp_path, {"anthropic_api_key": "from-the-file"}, {}, container)
    assert opts["anthropic_api_key"] == "from-the-file"
    assert SENTINEL not in log + log2 + capsys.readouterr().out


def test_a_secret_that_cant_be_read_never_shows_in_the_error(tmp_path):
    with pytest.raises(runtime_env.OptionsError) as raised:
        _options(tmp_path, None, {"F2_OPT_CF_API_TOKEN_FILE": str(tmp_path)}, container=True)
    assert str(raised.value) == "option F2_OPT_CF_API_TOKEN_FILE: file not readable"
    with pytest.raises(runtime_env.OptionsError) as raised:
        _options(tmp_path, {"cf_api_token": [SENTINEL]}, container=True)
    assert SENTINEL not in str(raised.value)


# U15: a container's options file is checked against OPTION_TYPES before Home Assistant is asked.
BAD_FILES = {
    "a truncated object": ('{"num_zones": 3, "hold', "not valid JSON (line 1, column"),
    "an empty file": ("", "not valid JSON"),
    "hold_entities as one string": ({"hold_entities": "input_boolean.flush"},
                                    "option hold_entities (options.json): expected a list of entity ids, got a string"),
    "a number as words": ({"loop_seconds": "sixty"}, "option loop_seconds (options.json): expected a number, got a string"),
    "two holds in one item": ({"hold_entities": ["input_boolean.flush input_boolean.fill"]}, "is not an entity id"),
    "a list at the top": ("[]", "expected a JSON object"),
    "true for a number": ({"num_zones": True}, "option num_zones (options.json): expected a whole number, got true or false"),
    "null for a required option": ({"notify_min": None}, "option notify_min (options.json): expected a number, got null"),
    "a secret of the wrong type": ({"cf_api_token": [SENTINEL]}, "option cf_api_token (options.json): expected text"),
}


@pytest.mark.parametrize("case", sorted(BAD_FILES))
def test_a_containers_options_file_with_a_mistake_exits_2_before_home_assistant_is_asked(box, tmp_path, case, capsys):
    content, said = BAD_FILES[case]
    (tmp_path / "options.json").write_text(content if isinstance(content, str) else json.dumps(content))
    outcome, fake = run(box)
    out = capsys.readouterr().out
    assert outcome == 2 and fake.sent == []
    assert said in out
    assert "sixty" not in out and SENTINEL not in out


@pytest.mark.parametrize("kind", ["a directory", "unreadable"])
def test_a_containers_options_file_that_cant_be_read_exits_2(box, tmp_path, kind, capsys):
    path = tmp_path / "options.json"
    if kind == "a directory":
        path.mkdir()
    else:
        path.write_text("{}")
        path.chmod(0)
        if os.access(path, os.R_OK):
            pytest.skip("this user reads any file (root)")
    outcome, fake = run(box)
    assert outcome == 2 and fake.sent == []
    assert f"options file {path}: not readable" in capsys.readouterr().out


def test_a_containers_file_drops_unknown_keys_and_null_optionals_and_none_is_zero_setup(tmp_path):
    opts, log = _options(tmp_path, {"foo": 1, "notify_service": None, "num_zones": 2}, container=True)
    assert opts == {"num_zones": 2}
    assert "option foo (options.json): unknown, ignored" in log
    assert _options(tmp_path / "nothing", None, container=True)[0] == {}


def test_the_hold_entities_env_form_is_checked_in_a_container_too(tmp_path):
    with pytest.raises(runtime_env.OptionsError, match="F2_OPT_HOLD_ENTITIES: 'input_boolean.flush input_boolean.fill'"):
        _options(tmp_path, None, {"F2_OPT_HOLD_ENTITIES": "input_boolean.flush input_boolean.fill"}, container=True)
