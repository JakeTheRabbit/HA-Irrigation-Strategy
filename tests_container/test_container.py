"""The controller's real image, run with Docker against fake_ha_server.py: as a standalone container (C1-C4,
C8) and as the Supervisor runs the app (C5). One image, both modes.

    docker build -t crop-steering-controller:test addons/f2_control
    CONTROLLER_IMAGE=crop-steering-controller:test python -m pytest tests_container -q

Skipped without Docker or CONTROLLER_IMAGE. C2 watches a parked container for C2_WATCH_S seconds (120 by
default) and its record case refuses for RECORD_REFUSE_S (150).
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone

import pytest

IMAGE = os.environ.get("CONTROLLER_IMAGE")
HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
WATCH_S = float(os.environ.get("C2_WATCH_S", "120"))
RECORD_REFUSE_S = float(os.environ.get("RECORD_REFUSE_S", "150"))
pytestmark = pytest.mark.skipif(not IMAGE or not shutil.which("docker"),
                                reason="needs Docker and CONTROLLER_IMAGE, an image built from addons/f2_control")
os.environ["MSYS_NO_PATHCONV"] = "1"
# The fake's log lines, matched whole: `[fake-ha <time>] REQ <method> <path> <status>` and `... CALL <rest>`.
REQ_LINE = re.compile(r"^\[fake-ha [0-9.]+\] REQ (\S+) (\S+) (\d{3})$")
CALL_LINE = re.compile(r"^\[fake-ha [0-9.]+\] CALL (.+)$")

VALVE = "switch.zone_1_valve"
OPTIONS = {"num_zones": 1, "lights_on_hour": 0, "lights_off_hour": 24, "enable_flag": "input_boolean.engine",
           "loop_seconds": 5, "hardware": {"pump": "switch.pump", "mainline": "switch.main_line",
                                           "valves": {"1": VALVE}}}
SEED = {"input_boolean.engine": "on", "switch.crop_steering_room_active": "on",
        "switch.crop_steering_zone_1_enabled": "on",
        "sensor.crop_steering_vwc_zone_1": ["60", {"unit_of_measurement": "%"}],
        "sensor.crop_steering_ec_zone_1": ["3.0", {"unit_of_measurement": "mS/cm"}],
        "switch.pump": "off", "switch.main_line": "off", VALVE: "off"}


def docker(*args, check=True, input=None):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, input=input, timeout=600)
    if check and result.returncode:
        raise AssertionError(f"docker {' '.join(args)}: {result.stderr}")
    return result.stdout.strip()


class Rig:
    def __init__(self):
        self.run = f"cs-test-{uuid.uuid4().hex[:8]}"
        self.net, self.vol, self.names = self.run, self.run + "-data", []
        self.vols = [self.vol]
        docker("network", "create", self.net)
        docker("volume", "create", self.vol)

    def volume(self):
        """Another data volume: another install, with its own instance_id."""
        vol = f"{self.run}-data{len(self.vols)}"
        docker("volume", "create", vol)
        self.vols.append(vol)
        return vol

    def close(self):
        for name in self.names:
            docker("rm", "-f", name, check=False)
        for vol in self.vols:
            docker("volume", "rm", vol, check=False)
        docker("network", "rm", self.net, check=False)

    def write(self, files, vol=None):
        """Files into the data volume: {name: text}."""
        for name, text in files.items():
            docker("run", "--rm", "-i", "-v", f"{vol or self.vol}:/data", "--entrypoint", "sh", IMAGE, "-c",
                   f"cat > /data/{name}", input=text)

    def read(self, name):
        return docker("run", "--rm", "-v", f"{self.vol}:/data", "--entrypoint", "cat", IMAGE, f"/data/{name}",
                      check=False)

    def fake(self, alias="fakeha", seed=None, **env):
        name = f"{self.run}-ha"
        self.names.append(name)
        settings = {"SEED": json.dumps(SEED if seed is None else seed), **env}
        docker("create", "--name", name, "--network", self.net, "--network-alias", alias,
               *[a for k, v in settings.items() for a in ("-e", f"{k}={v}")],
               "--entrypoint", "python3", IMAGE, "-u", "/fake_ha_server.py")
        docker("cp", str(HERE / "fake_ha_server.py"), f"{name}:/fake_ha_server.py")
        docker("start", name)
        self.ha = name
        return name

    def controller(self, *extra, options=OPTIONS, vol=None, **env):
        name = f"{self.run}-ctl-{len(self.names)}"
        self.names.append(name)
        if options is not None:
            self.write({"options.json": json.dumps(options)}, vol)
        docker("run", "-d", "--name", name, "--network", self.net, "-v", f"{vol or self.vol}:/data", *extra,
               *[a for k, v in env.items() for a in ("-e", f"{k}={v}")], IMAGE)
        return name

    def logs(self, name):
        result = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=60)
        return result.stdout + result.stderr

    def requests(self):
        """Every request the fake answered: (method, path, status)."""
        found = [REQ_LINE.match(line) for line in self.logs(self.ha).splitlines()]
        return [(m[1], m[2], int(m[3])) for m in found if m]

    def calls(self):
        found = [CALL_LINE.match(line) for line in self.logs(self.ha).splitlines()]
        return [m[1] for m in found if m]

    def wait(self, name, text, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if text in self.logs(name):
                return True
            time.sleep(1)
        raise AssertionError(f"{text!r} not in the log of {name}:\n{self.logs(name)[-3000:]}")

    def exit_code(self, name, timeout=60):
        docker("wait", name)
        return int(docker("inspect", name, "--format", "{{.State.ExitCode}}"))

    def running(self, name):
        return docker("inspect", name, "--format", "{{.State.Running}}") == "true"


def serves_8420(name):
    return subprocess.run(["docker", "exec", name, "wget", "-q", "-T", "2", "-O", "/dev/null",
                           "http://127.0.0.1:8420/dashboard.html"], capture_output=True).returncode == 0


@pytest.fixture
def rig():
    made = Rig()
    yield made
    made.close()


def container_env(rig, **extra):
    return {"F2_RUNTIME": "container", "HA_URL": "http://fakeha:8123", "HA_TOKEN": "good-token", "TZ": "UTC",
            **extra}


# ------------------------------------------------------------------ the fake itself
def test_the_fake_logs_whole_lines_when_requests_arrive_together(rig):
    """The controller's loop and its dosing thread ask the fake at once: every line it logs stays whole."""
    rig.fake()
    rig.wait(rig.ha, "serving")
    docker("exec", rig.ha, "python3", "-c", "\n".join([
        "import threading, urllib.request",
        "def ask():",
        "    for _ in range(25):",
        "        urllib.request.urlopen('http://127.0.0.1:8123/api/').read()",
        "threads = [threading.Thread(target=ask) for _ in range(16)]",
        "[t.start() for t in threads]",
        "[t.join() for t in threads]"]))
    assert rig.requests() == [("GET", "/api/", 200)] * 400
    assert len([line for line in rig.logs(rig.ha).splitlines() if " REQ " in line]) == 400


# ------------------------------------------------------------------ C1
def test_c1_a_bare_address_gets_api_and_the_heartbeat_carries_the_version(rig):
    rig.fake()
    ctl = rig.controller(**container_env(rig))
    rig.wait(ctl, "base: http://fakeha:8123/api")
    rig.wait(rig.ha, "STATE sensor.crop_steering_ai_heartbeat")
    beat = next(line for line in rig.logs(rig.ha).splitlines() if "STATE sensor.crop_steering_ai_heartbeat" in line)
    version = next(line.split('"')[1] for line in (ROOT / "addons/f2_control/config.yaml").read_text().splitlines()
                   if line.startswith("version:"))
    attributes = json.loads(beat.split("ai_heartbeat ", 1)[1])["attributes"]
    assert attributes["controller_version"] == version and attributes["controller_runtime"] == "container"
    assert "runtime: container" in rig.logs(ctl)
    assert not serves_8420(ctl)


# ------------------------------------------------------------------ C2
def test_c2_a_bad_token_parks_with_one_request_and_a_restart_sends_one_more(rig):
    rig.fake(REFUSE="401")
    ctl = rig.controller(**container_env(rig, HA_TOKEN="bad-token", F2_OPT_CF_API_TOKEN="cf-SENTINEL"))
    rig.wait(ctl, "HA rejected the token: GET http://fakeha:8123/api/ -> HTTP 401")
    time.sleep(WATCH_S)
    assert rig.running(ctl)
    assert rig.requests() == [("GET", "/api/", 401)]
    log = rig.logs(ctl)
    assert "bad-token" not in log and "cf-SENTINEL" not in log
    docker("restart", ctl)
    rig.wait(ctl, "parked", timeout=60)
    time.sleep(5)
    assert rig.requests() == [("GET", "/api/", 401)] * 2 and rig.calls() == []
    started = time.monotonic()
    docker("stop", ctl)
    assert time.monotonic() - started < 5 and rig.exit_code(ctl) == 0


@pytest.mark.parametrize("env, said", [
    ({"ADMIN_ONLY_WRITES": "1"}, "the token's user must be an administrator"),
    ({"REFUSE": "403"}, "Home Assistant refuses this machine, probably an IP ban"),
])
def test_c2_a_non_admin_or_banned_token_parks_with_its_own_message(rig, env, said):
    rig.fake(**env)
    ctl = rig.controller(**container_env(rig))
    rig.wait(ctl, said)
    time.sleep(10)
    assert rig.running(ctl) and rig.calls() == []
    assert len([r for r in rig.requests() if r[2] in (401, 403)]) == 1


def test_c2_a_new_token_in_the_file_starts_it_again(rig, tmp_path):
    rig.fake(REFUSE="401", REFUSE_TOKEN="bad-token")
    token = tmp_path / "ha_token.txt"
    token.write_text("bad-token\n")
    env = container_env(rig, HA_TOKEN_FILE="/run/secrets/ha_token.txt")
    env.pop("HA_TOKEN")
    ctl = rig.controller("--restart", "unless-stopped", "-v", f"{tmp_path}:/run/secrets:ro", **env)
    rig.wait(ctl, "parked")
    token.write_text("good-token\n")
    rig.wait(ctl, "HA_TOKEN_FILE has a new token", timeout=90)
    rig.wait(rig.ha, "STATE sensor.crop_steering_ai_heartbeat", timeout=90)


def test_c2_a_record_behind_a_refusal_is_asked_each_minute_and_then_closed(rig):
    rig.write({"state.json": json.dumps({"default": {"_shot_inflight": {
        "zone": 1, "valve": VALVE, "mainline": None, "pump": None,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}}})})
    rig.fake(seed={**SEED, VALVE: "on"}, REFUSE="403", REFUSE_FOR_S=str(RECORD_REFUSE_S))
    ctl = rig.controller(**container_env(rig))
    rig.wait(ctl, "asked again every 60 s")
    rig.wait(ctl, "closed and read back OFF - record closed", timeout=RECORD_REFUSE_S + 120)
    refused = [r for r in rig.requests() if r[2] == 403]
    assert {r[:2] for r in refused} == {("GET", "/api/")}
    assert len(refused) == int(RECORD_REFUSE_S // 60) + 1
    assert any(f'turn_off {{"entity_id": "{VALVE}"}}' in call for call in rig.calls())
    assert "_shot_inflight" not in rig.read("state.json")


# ------------------------------------------------------------------ C3
@pytest.mark.parametrize("case", ["no token", "missing token file", "token file is a directory", "unknown TZ",
                                  "corrupt options", "hold_entities as a string", "read-only data"])
def test_c3_a_wrong_setting_exits_2_before_home_assistant_is_asked(rig, case):
    rig.fake()
    env, options, extra, said = container_env(rig), OPTIONS, (), None
    if case == "no token":
        env.pop("HA_TOKEN")
        said = "no Home Assistant token"
    elif case == "missing token file":
        env.pop("HA_TOKEN")
        env["HA_TOKEN_FILE"] = "/run/secrets/ha_token"
        said = "HA_TOKEN_FILE /run/secrets/ha_token does not exist"
    elif case == "token file is a directory":
        env.pop("HA_TOKEN")
        env["HA_TOKEN_FILE"] = "/data"
        said = "HA_TOKEN_FILE /data is a directory"
    elif case == "unknown TZ":
        env["TZ"] = "Not/AZone"
        said = "TZ=Not/AZone is not a time zone this image knows"
    elif case == "corrupt options":
        rig.write({"options.json": '{"num_zones": 1, '})
        options, said = None, "options file /data/options.json: not valid JSON"
    elif case == "hold_entities as a string":
        options = {**OPTIONS, "hold_entities": "input_boolean.flush"}
        said = "option hold_entities (options.json): expected a list of entity ids, got a string"
    else:
        rig.write({"options.json": json.dumps(OPTIONS)})
        options, extra, said = None, ("--mount", f"type=volume,src={rig.vol},dst=/data,readonly"), "is not writable"
    if extra:  # the data volume mounted read-only
        ctl = f"{rig.run}-ctl-ro"
        rig.names.append(ctl)
        docker("run", "-d", "--name", ctl, "--network", rig.net, *extra,
               *[a for k, v in env.items() for a in ("-e", f"{k}={v}")], IMAGE)
    else:
        ctl = rig.controller(options=options, **env)
    assert rig.exit_code(ctl) == 2
    assert said in rig.logs(ctl)
    assert rig.requests() == []


# ------------------------------------------------------------------ C4
def test_c4_an_unset_tz_adopts_home_assistants_zone(rig):
    rig.fake(TIME_ZONE="Pacific/Auckland")
    ctl = rig.controller(**container_env(rig, TZ=""))
    rig.wait(ctl, "timezone: adopted Home Assistant's zone Pacific/Auckland")
    rig.wait(ctl, "timezone: matches Home Assistant (Pacific/Auckland)")
    assert not [c for c in rig.calls() if "CS-405" in c]


def test_c4_a_tz_that_differs_from_home_assistants_raises_cs_405_with_the_container_advice(rig):
    rig.fake(TIME_ZONE="Pacific/Auckland")
    ctl = rig.controller(**container_env(rig, TZ="UTC"))
    rig.wait(rig.ha, "CS-405", timeout=60)
    assert "compose file" in next(c for c in rig.calls() if "CS-405" in c)
    assert rig.running(ctl)


@pytest.mark.parametrize("config", [{"CONFIG_STATUS": "500"}, {"NO_TIME_ZONE": "1"}])
def test_c4_home_assistants_zone_unreadable_exits_2_after_the_wait(rig, config):
    rig.fake(**config)
    ctl = rig.controller(**container_env(rig, TZ="", F2_TZ_WAIT_S="20"))
    assert rig.exit_code(ctl) == 2
    assert "could not read Home Assistant's time zone" in rig.logs(ctl)
    assert rig.calls() == [] and not [r for r in rig.requests() if r[0] == "POST"]


# ------------------------------------------------------------------ C5
def test_c5_the_app_as_the_supervisor_runs_it(rig):
    options = json.loads((ROOT / "tests_ha/fixtures/options_3_8_0_jev_typesafe.json").read_text())["options"]
    rig.fake(alias="supervisor")
    ctl = rig.controller(options=options, F2_RUNTIME="addon", SUPERVISOR_TOKEN="x")
    rig.wait(ctl, "runtime: addon")
    rig.wait(ctl, "base: http://supervisor/core/api")
    rig.wait(ctl, "starting")
    assert serves_8420(ctl)
    frozen = docker("exec", ctl, "pip3", "freeze").lower().split()
    pinned = [line.split()[0].lower() for line in (ROOT / "addons/f2_control/requirements.txt").read_text().splitlines()
              if "==" in line and not line.startswith("#")]
    assert sorted(frozen) == sorted(pinned)


@pytest.mark.parametrize("env, refused", [
    ({"SUPERVISOR_TOKEN": "x"}, "F2_RUNTIME is unset"),
    ({"F2_RUNTIME": "addon", "SUPERVISOR_TOKEN": "x", "HA_URL": "http://supervisor:8123"}, "HA_URL is set"),
])
def test_c5_anything_short_of_what_the_supervisor_gives_is_a_container(rig, env, refused):
    rig.fake(alias="supervisor")
    ctl = rig.controller(**env)
    rig.wait(ctl, f"runtime: container (not the app: {refused})")
    # Gated as a container, but what would harm an app that lost its F2_RUNTIME keys on
    # F2_RUNTIME=container only: the app's 25 s stop budget and its dashboard stay.
    rig.wait(ctl, "stop budget: 25 s")
    if "HA_URL" not in env:
        # A container's gate: with no HA_URL it stops before Home Assistant is asked.
        assert rig.exit_code(ctl) == 2 and "HA_URL is not set" in rig.logs(ctl)
        return
    rig.wait(ctl, "starting")
    assert serves_8420(ctl)


def test_c5_the_app_is_built_at_once_while_home_assistant_is_unreachable(rig):
    ctl = rig.controller(F2_RUNTIME="addon", SUPERVISOR_TOKEN="x")
    rig.wait(ctl, "Home Assistant: GET http://supervisor/core/api/ -> the host name does not resolve here")
    rig.wait(ctl, "starting")


# ------------------------------------------------------------------ C7
HOLDING = "another controller wrote this room's heartbeat"
RESUMED = "no other controller seen for 3 min: carrying on"
REFUSED = "refused: another controller is driving this room"
DOSING_CONFIG = "sensor.crop_steering_dosing_config"
PUMP = {"id": "balance", "name": "Balance", "volume_entity": "number.balance_volume",
        "start_entity": "button.balance_start", "dosing_entity": "binary_sensor.balance_dosing",
        "dosing_prefix": "Dosing", "power_entity": "switch.balance_power", "flow_entity": "number.balance_flow",
        "max_ml": 2000, "restore_volume": True}
BATCH = {"fill_valve": "switch.tank_fill", "full_entity": "binary_sensor.tank_full", "full_state": "on",
         "fill_timeout_min": 20, "mix_pump": "switch.tank_mixer", "mix_valves": [], "mix_power_sensor": None,
         "mix_min_w": 0, "premix_min": 0, "postmix_min": 0, "close_entities": [], "hold_entity": None,
         "filled_at_entity": None, "recipe": []}
DOSING_DEVICES = {"number.balance_volume": "25", "button.balance_start": "unknown",
                  "binary_sensor.balance_dosing": "off", "switch.balance_power": "off", "number.balance_flow": "10",
                  "switch.tank_fill": "off", "binary_sensor.tank_full": "off", "switch.tank_mixer": "off"}


def turned_on(rig, entities):
    """The calls that switched on, pressed or set one of `entities`."""
    return [call for call in rig.calls()
            if call.split()[1] in ("turn_on", "press", "set_value")
            and any(json.dumps(entity) in call for entity in entities)]


def dosing_seed(action):
    request = {"id": f"req-{action}", "action": action, "pump": "balance" if action == "dose" else None,
               "ml": 50 if action == "dose" else None, "at": datetime.now(timezone.utc).isoformat(), "by": "test"}
    return {**SEED, **DOSING_DEVICES,
            DOSING_CONFIG: ["1", {"pumps": [PUMP], "batch": BATCH, "request": request}]}


@pytest.mark.parametrize("zones", [("UTC", "UTC"), ("Pacific/Auckland", "UTC")], ids=["(a)", "(d) mixed zones"])
def test_c7_two_controllers_on_one_room_both_hold(rig, zones):
    """(a) Two installs (two data volumes, two instance_ids) on one room: both hold and raise CS-609; (d)
    with the two in different time zones they still hold, and the one left resumes about 3 min after the
    other stops, not hours later."""
    rig.fake()
    first = rig.controller(**container_env(rig, TZ=zones[0]))
    rig.wait(rig.ha, "STATE sensor.crop_steering_ai_heartbeat")
    second = rig.controller(vol=rig.volume(), **container_env(rig, TZ=zones[1]))
    for ctl in (first, second):
        rig.wait(ctl, HOLDING, timeout=90)
        rig.wait(ctl, "(CS-609)", timeout=90)
    assert not turned_on(rig, [VALVE, "switch.pump", "switch.main_line"])
    docker("stop", second)
    stopped = time.monotonic()
    rig.wait(first, RESUMED, timeout=300)
    assert time.monotonic() - stopped <= 260


def test_c7_an_older_app_still_writing_holds_the_container_until_it_stops(rig):
    """(b) A controller from before the guard (no id, last_beat 12 h off) writes the heartbeat every 60 s:
    the container holds, raises CS-609 and switches nothing on. The older one is not stopped by it: that is
    the documented limit. (c) Once it stops, the container resumes about 3 min after its last write."""
    rig.fake(OLD_BEAT_FOR_S="200", OLD_BEAT_OFFSET_H="-12")
    ctl = rig.controller(**container_env(rig))
    rig.wait(ctl, HOLDING, timeout=90)
    rig.wait(ctl, "(CS-609)", timeout=90)
    rig.wait(rig.ha, "OLD BEAT STOPPED", timeout=260)
    assert not turned_on(rig, [VALVE, "switch.pump", "switch.main_line"])
    stopped = time.monotonic()
    rig.wait(ctl, RESUMED, timeout=300)
    assert time.monotonic() - stopped <= 260


@pytest.mark.parametrize("action", ["dose", "batch"])
def test_c7_dosing_is_refused_by_both_controllers(rig, action):
    """(e) While two controllers hold the room, a dose or a batch request already waiting in its
    dosing_config when they start is refused by both, and nothing on the dosing side is switched on."""
    rig.fake(seed=dosing_seed(action), OLD_BEAT_FOR_S="200")
    first = rig.controller(**container_env(rig))
    second = rig.controller(vol=rig.volume(), **container_env(rig))
    for ctl in (first, second):
        rig.wait(ctl, f"dosing: {action} request: {REFUSED}", timeout=90)
    assert not turned_on(rig, DOSING_DEVICES)


def test_c8_home_assistant_restarting_never_parks_the_controller(rig):
    rig.fake()
    ctl = rig.controller(**container_env(rig))
    rig.wait(rig.ha, "STATE sensor.crop_steering_ai_heartbeat")
    docker("stop", rig.ha)
    time.sleep(60)
    beats = rig.logs(rig.ha).count("STATE sensor.crop_steering_ai_heartbeat")
    docker("start", rig.ha)  # back with nothing but its seed: no heartbeat until the controller writes one
    end = time.monotonic() + 90
    while rig.logs(rig.ha).count("STATE sensor.crop_steering_ai_heartbeat") == beats and time.monotonic() < end:
        time.sleep(2)
    assert rig.logs(rig.ha).count("STATE sensor.crop_steering_ai_heartbeat") > beats
    assert rig.running(ctl) and "parked" not in rig.logs(ctl)
