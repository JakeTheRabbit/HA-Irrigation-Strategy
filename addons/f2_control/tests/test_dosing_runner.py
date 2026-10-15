"""Batch-tank dosing in the controller app (docs/DOSING.md): a dose and how it can end, a whole batch
step by step, a stop at any point, the irrigation hold, recovery after a restart, and an install with
no dosing that runs exactly as before.

Driven through the real Controller and the in-memory Home Assistant (fake_ha), on a fake clock: the
dosing pumps are scripted here the way their firmware behaves (a volume number, a start button and a
dosing sensor that turns on for the dose's length), so no test waits in real time.
"""
from __future__ import annotations

import itertools
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import controller
import dosing_runner
from test_controller import _build, _desc

BASE = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
CONFIG = "sensor.crop_steering_dosing_config"
STATUS = "sensor.crop_steering_dosing"
KILL = "input_boolean.kill"
BALANCE = {
    "id": "balance",
    "name": "Balance",
    "volume_entity": "number.balance_volume",
    "start_entity": "button.balance_start",
    "dosing_entity": "binary_sensor.balance_dosing",
    "dosing_prefix": "Dosing",
    "power_entity": "switch.balance_power",
    "flow_entity": "number.balance_flow",
    "max_ml": 2000,
    "restore_volume": True,
}
BLOOM = {
    "id": "bloom",
    "name": "Bloom",
    "volume_entity": "input_number.bloom_volume",
    "start_entity": "script.bloom_start",
    "dosing_entity": "sensor.bloom_status",  # a text sensor: "Dosing 150 mL" / "Idle"
    "dosing_prefix": "Dosing",
    "power_entity": "switch.bloom_power",
    "flow_entity": "sensor.bloom_flow",
    "max_ml": 2000,
    "restore_volume": False,
}
BATCH = {
    "fill_valve": "switch.tank_fill",
    "full_entity": "binary_sensor.tank_full",
    "full_state": "on",
    "fill_timeout_min": 20,
    "mix_pump": "switch.tank_mixer",
    "mix_valves": ["switch.mix_valve"],
    "mix_power_sensor": "sensor.mixer_power",
    "mix_min_w": 200,
    "premix_min": 2,
    "postmix_min": 5,
    "close_entities": ["switch.f1_feed"],
    "hold_entity": "input_boolean.tank_hold",
    "filled_at_entity": "input_datetime.tank_filled",
    "recipe": [
        {"pump": "balance", "ml": 300, "ml_entity": None},
        {"pump": "bloom", "ml": 100, "ml_entity": "number.recipe_bloom"},
    ],
}
DEVICES = {
    "number.balance_volume": "25",
    "button.balance_start": "unknown",
    "binary_sensor.balance_dosing": "off",
    "switch.balance_power": "off",
    "number.balance_flow": "10",
    "input_number.bloom_volume": "50",
    "script.bloom_start": "off",
    "sensor.bloom_status": "Idle",
    "switch.bloom_power": "off",
    "sensor.bloom_flow": "5",
    "switch.tank_fill": "off",
    "binary_sensor.tank_full": "off",
    "switch.tank_mixer": "off",
    "switch.mix_valve": "off",
    "sensor.mixer_power": "0",
    "switch.f1_feed": "on",
    "input_boolean.tank_hold": "off",
    "input_datetime.tank_filled": "2026-09-27 19:00:00",
    "number.recipe_bloom": "150",
}
ROOM = _desc(pump="switch.main_pump", mainline="switch.main_line", valves={"1": "switch.row1"})


class Clock:
    """Monotonic seconds from 0 and a wall clock from BASE; sleeping runs whatever is scheduled."""

    def __init__(self):
        self.t, self._events, self._seq = 0.0, [], itertools.count()

    def monotonic(self):
        return self.t

    def now(self):
        return BASE + timedelta(seconds=self.t)

    def at(self, delay, action):
        self._events.append((self.t + delay, next(self._seq), action))

    def sleep(self, seconds):
        end = self.t + max(seconds, 0)
        while True:
            due = sorted(event for event in self._events if event[0] <= end)
            if not due:
                break
            self._events.remove(due[0])
            self.t = max(self.t, due[0][0])
            due[0][2]()
        self.t = end


class Rig:
    """The Home Assistant side: fake_ha's states and calls, with the dosing pumps, the tank's full
    sensor and the mix pump's power scripted as the real devices behave, and a recorder that keeps
    every state an entity has had (ha_history)."""

    def __init__(self, c, fake, clock, tmp_path):
        self.c, self.fake, self.clock = c, fake, clock
        self.pumps = {p["start_entity"]: p for p in (BALANCE, BLOOM)}
        # start entity -> "normal" (default) | "overrun" | "silent" | "quick" | "early" | "reboot"
        self.behaviour = {}
        self.stuck = {}  # switch -> how many turn_offs it ignores
        self.deaf = {}  # switch -> how many turn_ons it ignores
        self.full_after = 60.0  # seconds after the fill valve opens that the tank reads full (None: never)
        self.watts = 350.0  # what the mix pump draws once running (0: it never starts)
        self.draw_ok = True  # whether crop_steering.stock_draw answers (Home Assistant up)
        self.draw_answer = (200, {"counted": True, "duplicate": False, "skipped": []})
        self.created = True  # whether a notification can be created (Home Assistant up)
        self.recorder = True  # whether the recorder can say (ha_history)
        self.recorder_lag = 0.0  # how long a state change takes to reach the recorder
        self.times = []  # (clock seconds, service, entity) of every call
        self.logs = []
        # Everything seeded was last changed an hour before the clock starts (a dosing sensor that
        # changed after a press is how a dose too short to see is told apart).
        past = (BASE - timedelta(hours=1)).isoformat()
        self.recorded = {}  # entity -> [(state, last_changed)], oldest first
        for entity, (state, attributes, _updated) in list(fake.states.items()):
            fake.states[entity], fake.changed[entity] = (state, attributes, past), past
            self.recorded[entity] = [(state, past)]
        fake.calls.clear()
        self.runner = self.build(tmp_path / "dosing_state.json")
        c.dosing = self.runner

    def build(self, path):
        """A runner on this rig (a second one is the controller app started again)."""
        return dosing_runner.DosingRunner(
            self.c,
            get=self.fake.ha_get,
            call=self.call,
            publish=self.fake.ha_set,
            alert=self.c._dosing_alert,
            state_path=str(path),
            log=lambda *a: self.logs.append(" ".join(str(x) for x in a)),
            sleep=self.clock.sleep,
            monotonic=self.clock.monotonic,
            now=self.clock.now,
            history=self.history,
            respond=self.respond,
        )

    def set(self, entity, state):
        now = self.clock.now().isoformat()
        rows = self.recorded.setdefault(entity, [])
        if not rows or rows[-1][0] != str(state):
            rows.append((str(state), now))
        self.fake.set_state(entity, state, {}, last_updated=now)

    def history(self, entity, since):
        """What the recorder holds from `since`: the state at `since`, then every change after it."""
        if not self.recorder or entity not in self.recorded:
            return None
        cutoff = self.clock.now() - timedelta(seconds=self.recorder_lag)
        rows = [row for row in self.recorded[entity] if datetime.fromisoformat(row[1]) <= cutoff]
        before = [row for row in rows if datetime.fromisoformat(row[1]) <= since]
        return before[-1:] + [row for row in rows if datetime.fromisoformat(row[1]) > since]

    def call(self, domain, service, timeout=None, **data):
        entity = data.get("entity_id")
        self.times.append((self.clock.t, service, entity))
        if (domain, service) == ("persistent_notification", "create") and not self.created:
            return False  # Home Assistant did not take it
        self.fake.calls.append((domain, service, data))
        if domain in ("switch", "input_boolean") and service in ("turn_on", "turn_off"):
            if self.fake.states.get(entity, ("",))[0] == "unavailable":
                pass  # its device is offline: Home Assistant answers all the same, and nothing switches
            elif service == "turn_off" and self.stuck.get(entity):
                self.stuck[entity] -= 1  # the command is lost: the switch stays as it was
            elif service == "turn_on" and self.deaf.get(entity):
                self.deaf[entity] -= 1
            else:
                self.set(entity, "on" if service == "turn_on" else "off")
                self._switched(entity, service)
        elif service == "set_value":
            self.set(entity, f"{float(data['value']):g}")
        elif (domain, service) in (("button", "press"), ("input_button", "press"), ("script", "turn_on")):
            self._press(entity)
        elif (domain, service) == ("input_datetime", "set_datetime"):
            stamp = datetime.fromtimestamp(data["timestamp"], timezone.utc)
            self.set(entity, stamp.strftime("%Y-%m-%d %H:%M:%S"))
        return True

    def respond(self, domain, service, data, timeout):
        """A service asked for its answer: stock_draw answers draw_answer while Home Assistant is up."""
        self.times.append((self.clock.t, service, None))
        self.fake.calls.append((domain, service, dict(data)))
        if (domain, service) == ("crop_steering", "stock_draw"):
            return self.draw_answer if self.draw_ok else (None, None)
        return 200, None

    def draws(self):
        """Every stock_draw sent, in order."""
        return [data for domain, service, data in self.fake.calls if (domain, service) == ("crop_steering", "stock_draw")]

    def _switched(self, entity, service):
        if entity == BATCH["fill_valve"] and service == "turn_on" and self.full_after is not None:
            self.clock.at(self.full_after, lambda: self.set(BATCH["full_entity"], "on"))
        if entity == BATCH["mix_pump"]:
            watts = self.watts if service == "turn_on" else 0
            self.clock.at(2, lambda: self.set(BATCH["mix_power_sensor"], f"{watts:g}"))
        for pump in self.pumps.values():  # power off stops the motor
            if entity == pump["power_entity"] and service == "turn_off":
                self.set(pump["dosing_entity"], self._idle(pump))

    @staticmethod
    def _idle(pump):
        return "off" if pump["dosing_entity"].startswith("binary_sensor.") else "Idle"

    def _run(self, pump, dosing):
        """The motor starts: the pump reads dosing, and its power (the motor's own switch) on."""
        self.set(pump["dosing_entity"], dosing)
        self.set(pump["power_entity"], "on")

    def _halt(self, pump):
        self.set(pump["dosing_entity"], self._idle(pump))
        self.set(pump["power_entity"], "off")

    def _press(self, entity):
        pump = self.pumps[entity]
        volume = float(self.fake.states[pump["volume_entity"]][0])
        seconds = volume / float(self.fake.states[pump["flow_entity"]][0])
        dosing = "on" if pump["dosing_entity"].startswith("binary_sensor.") else f"Dosing {volume:g} mL"
        how = self.behaviour.get(entity, "normal")
        if how == "silent":
            return
        if how == "blink":  # no dose at all: its sensor drops out and comes back idle between reads
            self.clock.at(0.2, lambda: self.set(pump["dosing_entity"], "unavailable"))
            self.clock.at(0.4, lambda: self.set(pump["dosing_entity"], self._idle(pump)))
            return
        if how == "quick":  # on and off again between two of the runner's reads
            self.clock.at(0.2, lambda: self._run(pump, dosing))
            self.clock.at(0.4, lambda: self._halt(pump))
            return
        self.clock.at(0.4, lambda: self._run(pump, dosing))
        if how == "normal":
            self.clock.at(seconds, lambda: self._halt(pump))
        elif how == "early":  # the firmware stops at a fifth of it
            self.clock.at(seconds / 5, lambda: self._halt(pump))
        elif how == "reboot":  # the pump restarts mid-dose, and comes back idle
            self.clock.at(2.3, lambda: self.set(pump["dosing_entity"], "unavailable"))
            self.clock.at(4.6, lambda: self._halt(pump))
        elif how == "flicker":  # the same, between two of the runner's reads
            self.clock.at(2.2, lambda: self.set(pump["dosing_entity"], "unavailable"))
            self.clock.at(2.4, lambda: self._halt(pump))

    # ---- what the integration publishes, and what came back
    def config(self, pumps=(BALANCE,), batch=None, request=None, revision="1"):
        batch = dict(BATCH, recipe=[]) if batch is None else batch
        self.fake.set_state(CONFIG, revision, json.loads(json.dumps(
            {"pumps": list(pumps), "batch": batch, "request": request})))

    def ask(self, action="dose", age=0.0, by="Ben", **data):
        if action == "dose":
            data = {"pump": "balance", "ml": 50, **data}
        request = {"id": uuid.uuid4().hex, "action": action, "pump": data.get("pump"),
                   "ml": data.get("ml"), "at": (self.clock.now() - timedelta(seconds=age)).isoformat(),
                   "by": by}
        state, attributes = self.fake.states[CONFIG][:2]
        self.fake.set_state(CONFIG, state, {**attributes, "request": request})
        return request

    def status(self):
        return self.fake.sets[STATUS]

    def alerts(self):
        return {data["notification_id"]: data for domain, service, data in self.fake.calls
                if (domain, service) == ("persistent_notification", "create")}

    def codes(self):
        """The code of each notification, one per event, in the order each was first raised."""
        return [data["title"].rsplit("(", 1)[1].rstrip(")") for data in self.alerts().values()]

    def creates(self, code=None):
        """Every notification created, repeats included, in order."""
        return [data for domain, service, data in self.fake.calls
                if (domain, service) == ("persistent_notification", "create")
                and (code is None or data["title"].endswith(f"({code})"))]

    def alert(self, code):
        """The last notification created with this code."""
        return self.creates(code)[-1]

    def actions(self, *entities):
        """The commands sent, in order: (service, entity) for every call that is not a notification."""
        return [(service, data.get("entity_id")) for domain, service, data in self.fake.calls
                if domain != "persistent_notification" and (not entities or data.get("entity_id") in entities)]

    def saved(self):
        with open(self.runner.path, encoding="utf-8") as fh:
            return json.load(fh)["rooms"]["default"]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def make_rig(tmp_path, monkeypatch):
    """What the `rig` fixture gives: build(states=None, options=None) -> a Rig (test_dosing_safety.py
    makes its own fixture from it)."""

    def build(states=None, options=None):
        c, fake = _build(
            options or {"num_zones": 1, "enable_flag": KILL},
            states={"sensor.crop_steering_engine_config": ("ok", ROOM), KILL: ("on", {}),
                    **{e: (s, {}) for e, s in DEVICES.items()}, **(states or {})},
        )
        clock = Clock()
        made = Rig(c, fake, clock, tmp_path)
        monkeypatch.setattr(controller, "ha_call", made.call)  # the controller's alerts and shots too
        return made

    return build


# ------------------------------------------------------------------ one dose
def test_a_dose_sets_the_volume_presses_start_waits_for_it_and_puts_the_volume_back(rig):
    r = rig()
    r.config()
    request = r.ask(ml=50)
    r.runner.poll()
    assert r.actions() == [
        ("set_value", "number.balance_volume"),
        ("press", "button.balance_start"),
        ("set_value", "number.balance_volume"),  # put back: firmware may keep its recipe in it
    ]
    sets = [d["value"] for dom, svc, d in r.fake.calls if svc == "set_value"]
    assert sets == [50, 25.0]
    assert 5 <= r.clock.t < 5 + 20  # 50 mL at 10 mL/s, read every second
    state, status = r.status()
    assert state == "idle"
    assert (status["handled"], status["handled_result"]) == (request["id"], "finished")
    assert status["pumps"]["balance"]["last"] == {"ml": 50, "at": BASE.isoformat(), "result": "finished"}
    assert status["pumps"]["balance"]["flow_ml_s"] == 10.0
    assert status["history"][0] == {"kind": "dose", "at": BASE.isoformat(), "ended_at": r.clock.now().isoformat(),
                                    "result": "finished", "doses": {"balance": 50}, "by": "Ben"}
    assert r.saved()["inflight"] is None and r.saved()["handled"] == request["id"]
    assert r.codes() == [] and ("turn_off", "switch.balance_power") not in r.actions()
    # Taken once: the same request read again does nothing.
    r.fake.calls.clear()
    r.runner.poll()
    assert r.actions() == []


def test_a_pump_with_no_volume_to_put_back_and_a_text_status_sensor(rig):
    r = rig()
    r.config(pumps=(BALANCE, BLOOM))
    r.ask(pump="bloom", ml=100)
    r.runner.poll()
    assert r.actions() == [("set_value", "input_number.bloom_volume"), ("turn_on", "script.bloom_start")]
    assert r.status()[1]["handled_result"] == "finished"


def test_the_dose_is_recorded_before_anything_moves(rig):
    r = rig()
    r.config()
    seen = []
    original = r.call

    def watch(domain, service, **data):
        if service == "set_value" and not seen:
            seen.append(r.saved()["inflight"])
        return original(domain, service, **data)

    r.runner._call = watch
    r.runner.poll()  # no request yet: nothing
    request = r.ask(ml=20)
    r.runner.poll()
    assert seen[0]["kind"] == "dose" and seen[0]["request"] == request["id"]
    # The volume it is about to change is recorded too, so even a restart puts it back.
    assert seen[0]["dose"] == {
        "pump": "balance", "ml": 20, "at": BASE.isoformat(), "old_volume": 25.0, "name": "Balance",
        "volume_entity": "number.balance_volume", "dosing_entity": "binary_sensor.balance_dosing",
        "dosing_prefix": "Dosing", "power_entity": "switch.balance_power",
    }
    assert "switch.balance_power" in seen[0]["off"] and "switch.tank_fill" in seen[0]["off"]
    # A single dose never records a batch's hold: a restart or a stop must never switch someone
    # else's hold off.
    assert "hold" not in seen[0] and "input_boolean.tank_hold" not in seen[0]["off"]


@pytest.mark.parametrize("flow", ["0", "-3", "unavailable", "fast", "0.01", "0.049", "nan", "inf"])
def test_a_pump_whose_flow_is_not_above_zero_is_refused(rig, flow):
    """A firmware that divides by a zero flow runs its motor for ever, and a tiny one (0.01 mL/s)
    would put every time limit hours away: below 0.05 mL/s, or not a finite number, is no flow."""
    r = rig({"number.balance_flow": (flow, {})})
    r.config()
    r.ask()
    r.runner.poll()
    assert r.actions() == []
    assert r.status()[1]["handled_result"] == f"refused: Balance is not calibrated (flow {flow})"
    assert r.status()[1]["history"] == [] and r.status()[1]["pumps"]["balance"]["last"] is None


def test_a_dose_over_the_maximum_or_onto_a_pump_already_dosing_is_refused(rig):
    r = rig()
    r.config()
    r.ask(ml=2500)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: 2500 mL is not more than 0 and at most 2000 mL"
    r.set("binary_sensor.balance_dosing", "on")
    r.ask(ml=10)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: Balance already reads dosing"
    r.ask(pump="bloom")
    r.runner.poll()
    assert "there is no pump bloom" in r.status()[1]["handled_result"]
    assert r.actions() == []


def test_a_dose_that_runs_past_its_time_is_switched_off_and_read_back(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "overrun"
    r.stuck["switch.balance_power"] = 1  # the first off is lost: it is sent again once
    r.ask(ml=120)  # 12 s expected: a deadline of 12 x 1.25 + 20 = 35 s after the press
    r.runner.poll()
    offs = [a for a in r.actions() if a == ("turn_off", "switch.balance_power")]
    assert len(offs) == 2 and r.fake.states["switch.balance_power"][0] == "off"
    assert 1 + 35 <= r.clock.t < 1 + 35 + 1 + 6 + 6 + 2  # pressed once the volume read back (1 s)
    status = r.status()[1]
    assert status["handled_result"] == "ran past its time"
    assert status["pumps"]["balance"]["last"]["result"] == "ran past its time"
    alert = r.alert("CS-801")
    assert alert["title"] == "A dosing pump ran past its time and was switched off (CS-801)"
    assert "was still dosing after 35 seconds" in alert["message"]
    assert "switch it off by hand" not in alert["message"]  # it reads off: the re-send worked
    assert r.actions()[-1] == ("set_value", "number.balance_volume")  # still put back


def test_a_dose_never_seen_dosing_is_not_confirmed(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "silent"
    r.ask(ml=50)  # 5 s expected: seen dosing by 5 + 15 s or not confirmed
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "not confirmed"
    assert 20 <= r.clock.t < 22 + 1 + 6
    assert r.codes() == ["CS-802"]
    assert ("turn_off", "switch.balance_power") not in r.actions()  # it may not have run at all


def test_a_dose_too_short_to_catch_between_two_reads_still_counts(rig):
    r = rig()
    r.config()
    r.behaviour["button.balance_start"] = "quick"
    r.ask(ml=2)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished" and r.codes() == []


def test_a_volume_that_does_not_read_back_is_never_started(rig):
    r = rig()
    r.config()
    original = r.call

    def deaf(domain, service, **data):  # the number ignores the first set
        if service == "set_value" and data["value"] == 40:
            r.fake.calls.append((domain, service, data))
            return True
        return original(domain, service, **data)

    r.runner._call = deaf
    r.ask(ml=40)
    r.runner.poll()
    assert ("press", "button.balance_start") not in r.actions()
    assert r.status()[1]["handled_result"].startswith("refused: number.balance_volume did not read back 40")
    assert r.saved()["inflight"] is None


def test_a_request_older_than_two_minutes_is_marked_handled_and_never_acted_on(rig):
    r = rig()
    r.config()
    request = r.ask(age=121)
    r.runner.poll()
    assert r.actions() == []
    assert (r.status()[1]["handled"], r.status()[1]["handled_result"]) == (request["id"], "too old to act on")
    r.clock.t += 1  # and read again: still nothing
    r.runner.poll()
    assert r.actions() == []


def test_a_request_is_taken_once_across_a_restart(rig, tmp_path):
    r = rig()
    r.config()
    r.ask(ml=10)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    again = dosing_runner.DosingRunner(  # the controller restarted a few seconds later
        r.c, get=r.fake.ha_get, call=r.call, publish=r.fake.ha_set, alert=r.c._dosing_alert,
        state_path=r.runner.path, sleep=r.clock.sleep, monotonic=r.clock.monotonic, now=r.clock.now)
    r.fake.calls.clear()
    assert again.recover()
    again.poll()
    assert r.actions() == []


def test_a_stop_during_a_dose_switches_the_pumps_off(rig):
    r = rig()
    r.config(pumps=(BALANCE, BLOOM))
    r.ask(ml=500)  # 50 s
    stop = {}
    r.clock.at(10, lambda: stop.update(r.ask("stop", by="Sam")))
    r.runner.poll()
    assert 10 <= r.clock.t < 20
    # Every pump's power in the room, whatever it reads: a stale OFF is never why one was not told.
    assert ("turn_off", "switch.balance_power") in r.actions()
    assert ("turn_off", "switch.bloom_power") in r.actions()
    status = r.status()[1]
    assert (status["handled"], status["handled_result"]) == (stop["id"], "stopped")
    assert status["pumps"]["balance"]["last"]["result"] == "stopped"
    assert status["history"][0]["result"] == "stopped" and r.codes() == []


def test_a_request_while_a_dose_runs_is_refused(rig):
    r = rig()
    r.config()
    r.ask(ml=500)
    second = {}
    r.clock.at(10, lambda: second.update(r.ask("batch")))
    seen = []
    r.clock.at(13, lambda: seen.append(r.status()[1]["handled_result"]))
    r.clock.at(5, lambda: seen.append(r.status()[1]["handled_result"]))
    r.runner.poll()
    assert seen == ["dosing", "refused: a dose is running"]
    assert r.status()[1]["handled"] == second["id"]


# ------------------------------------------------------------------ stock tanks
LINKED = dict(BALANCE, stock_tank="balance_stock")


@pytest.mark.parametrize("how, ml, drawn, result", [
    ("normal", 50, (50, 50), "finished"),
    ("overrun", 120, (120, 120), "ran past its time"),  # cut at 35 s: 350 mL at 10 mL/s, capped
    ("silent", 50, None, "not confirmed; nothing drawn from its stock tank"),
])
def test_each_dose_draws_from_its_stock_tank_what_it_dosed(rig, how, ml, drawn, result):
    r = rig()
    r.config(pumps=(LINKED,))
    r.behaviour["button.balance_start"] = how
    r.ask(ml=ml)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == result
    assert r.status()[1]["pumps"]["balance"]["last"]["result"] == result
    if drawn is None:
        assert r.draws() == []
        return
    [draw] = r.draws()
    assert draw == {"room_id": "room:", "key": f":balance:{BASE.isoformat()}", "source": "dose",
                    "draws": {"balance_stock": draw["draws"]["balance_stock"]}, "note": f"Balance: {result}"}
    assert drawn[0] <= draw["draws"]["balance_stock"] <= drawn[1]
    assert r.saved()["draws"] == []  # answered: nothing left to send


def test_a_stopped_dose_draws_only_what_ran_before_the_stop(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.ask(ml=500)  # 50 s at 10 mL/s, pressed once the volume read back (t = 1 s)
    r.clock.at(10, lambda: r.ask("stop"))
    r.runner.poll()
    [draw] = r.draws()
    assert draw["note"] == "Balance: stopped"
    # Timed to the moment the stop's off was sent, not to when its read-back ended.
    [pressed] = [t for t, service, _e in r.times if service == "press"]
    cut = min(t for t, service, e in r.times if (service, e) == ("turn_off", "switch.balance_power"))
    assert draw["draws"]["balance_stock"] == round((cut - pressed) * 10, 1)
    assert 90 <= draw["draws"]["balance_stock"] <= 110  # about 10 s of flow, not the 500 asked for


def test_an_undelivered_draw_is_kept_and_sent_again_until_answered_and_never_twice(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.draw_ok = False  # Home Assistant is not answering
    r.ask(ml=50)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    [pending] = r.saved()["draws"]
    assert pending["draws"] == {"balance_stock": 50}
    r.runner.poll()  # every tick, the same draw with the same key
    assert len(r.draws()) == 2 and {d["key"] for d in r.draws()} == {pending["key"]}
    r.draw_ok = True
    r.runner.poll()
    assert r.saved()["draws"] == [] and len(r.draws()) == 3
    r.runner.poll()
    assert len(r.draws()) == 3  # answered once: never sent again


def test_a_draw_not_yet_delivered_survives_a_restart(rig):
    r = rig()
    r.config(pumps=(LINKED,))
    r.draw_ok = False
    r.ask(ml=50)
    r.runner.poll()
    key = r.saved()["draws"][0]["key"]
    r.draw_ok = True
    again = dosing_runner.DosingRunner(  # the controller app restarted
        r.c, get=r.fake.ha_get, call=r.call, publish=r.fake.ha_set, alert=r.c._dosing_alert,
        state_path=r.runner.path, sleep=r.clock.sleep, monotonic=r.clock.monotonic, now=r.clock.now)
    assert again.recover()
    again.poll()
    assert r.draws()[-1]["key"] == key and r.saved()["draws"] == []


def test_the_doses_of_a_batch_draw_one_by_one(rig):
    r = rig()
    r.config(pumps=(LINKED, dict(BLOOM, stock_tank="bloom_stock")), batch=BATCH)
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert [(d["draws"], d["source"]) for d in r.draws()] == [
        ({"balance_stock": 300}, "batch"),
        ({"bloom_stock": 150.0}, "batch"),
    ]
    assert len({d["key"] for d in r.draws()}) == 2


# ------------------------------------------------------------------ a batch
def _full_batch(r):
    r.config(pumps=(BALANCE, BLOOM), batch=BATCH)
    for switch in ("switch.row1", "switch.main_line", "switch.main_pump"):
        r.set(switch, "on")  # watering by hand, say: the batch closes it


def test_a_whole_batch_in_order(rig):
    r = rig()
    _full_batch(r)
    during = []
    r.clock.at(30, lambda: during.append((r.c._blocked(r.c.rooms[0], 1), r.status()[0])))
    request = r.ask("batch")
    r.runner.poll()
    assert r.actions() == [
        ("turn_on", "input_boolean.tank_hold"),  # hold
        ("turn_off", "switch.row1"),  # close: the room's valve, main line and pump, then close_entities
        ("turn_off", "switch.main_line"),
        ("turn_off", "switch.main_pump"),
        ("turn_off", "switch.f1_feed"),
        ("turn_on", "switch.tank_fill"),  # fill until full, then closed
        ("turn_off", "switch.tank_fill"),
        ("turn_on", "switch.mix_valve"),  # mix: the valves first, then the pump
        ("turn_on", "switch.tank_mixer"),
        ("set_value", "number.balance_volume"),  # doses in recipe order
        ("press", "button.balance_start"),
        ("set_value", "number.balance_volume"),
        ("set_value", "input_number.bloom_volume"),
        ("turn_on", "script.bloom_start"),
        ("turn_off", "switch.tank_mixer"),  # finish: the pump, then the valves
        ("turn_off", "switch.mix_valve"),
        ("set_datetime", "input_datetime.tank_filled"),
        ("turn_off", "input_boolean.tank_hold"),
    ]
    volumes = [d["value"] for dom, svc, d in r.fake.calls if svc == "set_value"]
    assert volumes == [300, 25.0, 150.0]  # the recipe entity wins over the recipe's 100 mL
    state, status = r.status()
    assert state == "idle"
    assert (status["handled"], status["handled_result"]) == (request["id"], "finished")
    batch = status["batch"]
    assert (batch["step"], batch["result"]) == ("idle", "finished")
    assert [(s["step"], s["state"]) for s in batch["steps"]] == [
        (step, "done") for step in ("hold", "close", "fill", "mix", "premix", "dose", "postmix", "finish")
    ]
    [stamped] = [t for t, service, _e in r.times if service == "set_datetime"]
    stamp = (BASE + timedelta(seconds=stamped)).strftime("%Y-%m-%d %H:%M:%S")
    assert r.fake.states["input_datetime.tank_filled"][0] == stamp  # the time the batch finished
    assert r.fake.states["input_boolean.tank_hold"][0] == "off"
    assert status["history"][0]["doses"] == {"balance": 300, "bloom": 150.0}
    assert during == [("making a batch", "batch")]
    assert r.c._blocked(r.c.rooms[0], 1) != "making a batch" and r.runner.holds(r.c.rooms[0]) is None
    assert r.codes() == [] and r.saved()["inflight"] is None
    # 60 s filling, 2 min premix, 30 + 30 s of doses, 5 min postmix, and the read-backs.
    assert 60 + 120 + 60 + 300 < r.clock.t < 60 + 120 + 60 + 300 + 120


def test_a_batch_with_no_fill_valve_or_a_full_tank_skips_the_fill(rig):
    r = rig()
    r.config(pumps=(BALANCE,), batch=dict(BATCH, recipe=[], fill_valve=None, full_entity=None))
    r.ask("batch")
    r.runner.poll()
    steps = {s["step"]: (s["state"], s["note"]) for s in r.status()[1]["batch"]["steps"]}
    assert steps["fill"] == ("skipped", "no fill valve: the tank is filled already")
    assert steps["dose"] == ("skipped", "nothing to dose")
    r.set("binary_sensor.tank_full", "on")
    r.config(pumps=(BALANCE,), batch=dict(BATCH, recipe=[]))
    r.ask("batch")
    r.runner.poll()
    steps = {s["step"]: s["note"] for s in r.status()[1]["batch"]["steps"]}
    assert steps["fill"] == "the tank reads full already"
    assert ("turn_on", "switch.tank_fill") not in r.actions()


def test_a_tank_that_does_not_fill_closes_the_valve_and_ends_the_batch(rig):
    r = rig()
    _full_batch(r)
    r.full_after = None
    r.ask("batch")
    r.runner.poll()
    assert r.fake.states["switch.tank_fill"][0] == "off"
    assert r.codes() == ["CS-804", "CS-806"]  # its own code first
    status = r.status()[1]
    assert status["handled_result"] == "stopped: fill: the tank did not read full within 20 min"
    assert [(s["step"], s["state"]) for s in status["batch"]["steps"]][-1] == ("fill", "failed")
    assert r.fake.states["input_boolean.tank_hold"][0] == "off"
    assert r.fake.states["input_datetime.tank_filled"][0] == "2026-09-27 19:00:00"  # not stamped
    assert r.runner.holds(r.c.rooms[0]) is None  # the room waters again
    assert "the fill valve was switched off" in r.alert("CS-804")["message"].lower()
    assert r.alert("CS-804")["title"] == "The batch tank did not fill in time (CS-804)"


def test_a_mix_pump_that_does_not_draw_its_power_ends_the_batch(rig):
    r = rig()
    _full_batch(r)
    r.watts = 0
    r.ask("batch")
    r.runner.poll()
    assert r.codes() == ["CS-805", "CS-806"]
    assert r.status()[1]["handled_result"] == "stopped: mix: the mix pump did not draw 200 W within 20 s"
    assert r.fake.states["switch.tank_mixer"][0] == "off" and r.fake.states["switch.mix_valve"][0] == "off"
    assert not any(svc == "set_value" for _d, svc, _data in r.fake.calls)  # nothing dosed


def test_a_mix_pump_that_does_not_start_is_switched_off_before_its_alert(rig):
    """The alert's phone push can take a while: the pump goes off first, and the batch's end reads it back."""
    r = rig()
    _full_batch(r)
    r.watts = 0
    r.ask("batch")
    r.runner.poll()
    steps = [(service, data.get("entity_id") or data.get("title", "")[-7:-1])
             for _domain, service, data in r.fake.calls if service in ("turn_on", "turn_off", "create")]
    on, card = steps.index(("turn_on", "switch.tank_mixer")), steps.index(("create", "CS-805"))
    assert ("turn_off", "switch.tank_mixer") in steps[on:card]


def test_a_stop_in_the_middle_of_a_batch_switches_everything_off(rig):
    r = rig()
    _full_batch(r)
    r.ask("batch")
    r.clock.at(150, lambda: r.ask("stop", by="Sam"))  # 60 s filling, 2 min premix: in the premix
    r.runner.poll()
    for switch in ("switch.balance_power", "switch.bloom_power", "switch.tank_fill", "switch.tank_mixer",
                   "switch.mix_valve"):
        assert r.fake.states[switch][0] == "off", switch
    assert r.fake.states["input_boolean.tank_hold"][0] == "off"
    status = r.status()[1]
    assert status["handled_result"] == "stopped"  # the stop request's own answer
    assert status["history"][0]["result"] == "stopped: premix: stop requested by Sam"
    assert status["batch"]["result"] == "stopped: premix: stop requested by Sam"
    assert r.codes() == ["CS-806"]
    message = r.alert("CS-806")["message"]
    assert "stopped in its premix step" in message and "Dosed before it stopped: nothing" in message
    assert r.runner.holds(r.c.rooms[0]) is None and r.saved()["inflight"] is None


def test_a_dose_that_fails_in_a_batch_ends_it_with_both_codes(rig):
    r = rig()
    _full_batch(r)
    r.behaviour["script.bloom_start"] = "silent"
    r.ask("batch")
    r.runner.poll()
    assert r.codes() == ["CS-802", "CS-806"]
    status = r.status()[1]
    assert status["handled_result"] == "stopped: dose: Bloom: not confirmed"
    assert status["history"][0]["doses"] == {"balance": 300, "bloom": 150.0}
    assert "Dosed before it stopped: 300 mL of Balance, 150 mL of Bloom." in (
        r.alert("CS-806")["message"])


def test_dosing_hardware_that_does_not_read_off_keeps_the_rooms_held_until_it_does(rig):
    r = rig()
    _full_batch(r)
    r.stuck["switch.tank_mixer"] = 99  # it starts, and will not stop
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: finish: switch.tank_mixer did not read off"
    # Held, and saying why: it reads on.
    reason = "dosing hardware still on: switch.tank_mixer"
    assert r.runner.holds(r.c.rooms[0]) == reason and r.c._blocked(r.c.rooms[0], 1) == reason
    message = r.alert("CS-806")["message"]
    assert "switch.tank_mixer still does not read off" in message
    assert "stay held, and its hold stays on, until they do" in message
    # The hold stays on while it does not read off: other automations keep off the tank.
    assert r.fake.states["input_boolean.tank_hold"][0] == "on"
    assert r.saved()["inflight"]["kind"] == "batch"  # a restart would still switch it off
    assert r.fake.states["input_datetime.tank_filled"][0] == "2026-09-27 19:00:00"  # not finished
    r.ask(ml=5)
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: switch.tank_mixer does not read off yet"
    r.stuck["switch.tank_mixer"] = 0
    r.runner.poll()  # switched off again, and it goes this time
    r.runner.poll()  # it reads off: the hold goes off
    assert r.fake.states["input_boolean.tank_hold"][0] == "off"
    r.runner.poll()  # and reads off: released
    assert r.runner.holds(r.c.rooms[0]) is None and r.saved()["inflight"] is None
    assert "Everything now reads off; the hold was released" in r.alert("CS-806")["message"]


def test_a_switch_the_batch_cannot_close_ends_it_before_anything_is_filled(rig):
    r = rig()
    _full_batch(r)
    r.stuck["switch.f1_feed"] = 99
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: close: switch.f1_feed did not read off"
    assert ("turn_on", "switch.tank_fill") not in r.actions()
    assert r.codes() == ["CS-806"]
    assert r.runner.holds(r.c.rooms[0]) is None  # its own hardware reads off: the rooms water again


def test_a_batch_waits_for_a_shot_in_flight_before_closing_anything(rig):
    r = rig()
    _full_batch(r)
    r.c._busy, r.c._shot_room = True, r.c.rooms[0]  # a shot is running in the room
    r.clock.at(45, lambda: setattr(r.c, "_busy", False))
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    closed = datetime.fromisoformat(r.fake.changed["switch.row1"])
    assert closed >= BASE + timedelta(seconds=45)  # nothing closed while the shot ran


def test_a_batch_gives_up_on_a_shot_still_running_after_ten_minutes(rig):
    r = rig()
    _full_batch(r)
    r.c._busy, r.c._shot_room = True, r.c.rooms[0]  # and this one never ends
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: hold: a shot was still running after 10 minutes"
    assert 600 <= r.clock.t < 600 + 30
    assert r.fake.states["switch.row1"][0] == "on"  # the shot's own valve was never touched
    assert r.runner.holds(r.c.rooms[0]) is None


def test_a_room_with_a_latched_hardware_fault_or_its_hold_on_refuses_a_batch(rig):
    r = rig()
    _full_batch(r)
    r.c.rooms[0].hardware_fault = {"reason": "valve stuck", "entities": ["switch.row1"]}
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: the room has a hardware fault latched"
    r.c.rooms[0].hardware_fault = None
    r.set("input_boolean.tank_hold", "on")
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == (
        "refused: input_boolean.tank_hold is on already: something else is dosing")
    r.set("input_boolean.tank_hold", "off")
    r.set("number.recipe_bloom", "unavailable")  # never replaced by the recipe's fixed 100 mL
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: the recipe amount for Bloom can't be read"
    r.set("number.recipe_bloom", "150")
    r.set("sensor.bloom_flow", "0")
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "refused: Bloom is not calibrated (flow 0)"
    assert r.actions() == [] and r.runner.holds(r.c.rooms[0]) is None
    # A pump the recipe gives 0 mL is skipped, calibrated or not.
    r.set("number.recipe_bloom", "0")
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert ("turn_on", "script.bloom_start") not in r.actions()


def test_the_batch_holds_its_room_and_every_room_on_its_hardware_and_no_other(rig, capsys):
    shared = _desc(prefix="f1_", slug="f1", pump=None, mainline="switch.f1_feed",
                   valves={"1": "switch.f1_row1"})  # fed through a switch the batch closes
    same_pump = _desc(prefix="veg_", slug="veg", pump="switch.main_pump", mainline=None,
                      valves={"1": "switch.veg_row1"})  # shares the batch room's pump
    other = _desc(prefix="clone_", slug="clone", pump="switch.clone_pump", mainline=None,
                  valves={"1": "switch.clone_row1"})
    r = rig({"sensor.crop_steering_f1_engine_config": ("ok", shared),
             "sensor.crop_steering_veg_engine_config": ("ok", same_pump),
             "sensor.crop_steering_clone_engine_config": ("ok", other),
             "switch.f1_row1": ("off", {}), "switch.veg_row1": ("off", {}),
             "switch.clone_row1": ("off", {}), "switch.clone_pump": ("off", {})})
    rooms = {room.slug: room for room in r.c.rooms}
    assert set(rooms) == {"default", "f1", "veg", "clone"}
    _full_batch(r)
    seen, shots = {}, []

    def during():
        seen.update({slug: r.c._blocked(room, 1) for slug, room in rooms.items()})
        before = len(r.fake.calls)
        r.c._execute_shot(rooms["veg"], 1, 10, 5)  # a shot already past the gate: refused under the lock
        shots.extend(call for call in r.fake.calls[before:] if call[0] == "switch")

    r.clock.at(100, during)
    r.ask("batch")
    r.runner.poll()
    assert seen["default"] == seen["f1"] == seen["veg"] == "making a batch"
    assert seen["clone"] != "making a batch"
    assert shots == [] and not r.c._busy
    assert "[veg] Z1 shot held: making a batch" in capsys.readouterr().out
    # f1's feed and every valve of the rooms it holds were closed; the clone room was left alone.
    closed = {entity for service, entity in r.actions() if service == "turn_off"}
    assert {"switch.f1_row1", "switch.f1_feed", "switch.veg_row1", "switch.row1"} <= closed
    assert not {"switch.clone_row1", "switch.clone_pump"} & closed
    assert all(r.c._blocked(room, 1) != "making a batch" for room in rooms.values())


def test_a_request_refused_while_a_batch_runs_is_never_taken_again(rig):
    r = rig()
    _full_batch(r)
    batch = r.ask("batch")
    dose, answers = {}, []
    r.clock.at(300, lambda: answers.append(r.status()[1]["handled_result"]))
    r.clock.at(520, lambda: dose.update(r.ask(ml=10)))  # in the postmix
    r.clock.at(525, lambda: answers.append(r.status()[1]["handled_result"]))
    r.runner.poll()
    assert answers == ["making a batch", "refused: a batch is running"]
    status = r.status()[1]
    # The batch's end does not claim the request back: that dose must not run after it.
    assert (status["handled"], status["handled_result"]) == (dose["id"], "refused: a batch is running")
    assert status["history"][0]["result"] == "finished" and batch["id"] != dose["id"]
    presses = r.actions().count(("press", "button.balance_start"))
    r.clock.t += 5
    r.runner.poll()
    assert r.actions().count(("press", "button.balance_start")) == presses == 1


def test_an_unforeseen_error_in_a_batch_still_switches_everything_off(rig, monkeypatch):
    r = rig()
    _full_batch(r)

    def broken(job):
        r.runner._begin(job, "mix")
        raise RuntimeError("a bug")

    monkeypatch.setattr(r.runner, "_mix", broken)
    r.ask("batch")
    r.runner.poll()
    status = r.status()[1]
    assert status["handled_result"] == "stopped: mix: an error in the controller (RuntimeError('a bug'))"
    assert [(s["step"], s["state"]) for s in status["batch"]["steps"]][-1] == ("mix", "failed")
    assert r.fake.states["switch.tank_fill"][0] == "off" and r.codes() == ["CS-806"]
    assert r.runner.holds(r.c.rooms[0]) is None


def test_a_cleanup_that_fails_keeps_the_rooms_held_until_everything_reads_off(rig, monkeypatch):
    r = rig()
    _full_batch(r)
    r.full_after = None

    def broken(job, reason):
        raise RuntimeError("cleanup bug")

    monkeypatch.setattr(r.runner, "_ended", broken)
    r.set("switch.tank_fill", "on")  # say the fill valve was not closed
    r.ask("batch")
    r.runner.poll()
    assert r.runner.holds(r.c.rooms[0]).startswith("dosing hardware still on: switch.balance_power")
    assert r.fake.states["input_boolean.tank_hold"][0] == "on"
    for _pass in range(3):  # the next passes read it all off, then switch the hold off, and let go
        r.clock.t += dosing_runner.POLL_S
        r.runner.poll()
    assert r.runner.holds(r.c.rooms[0]) is None and r.saved()["inflight"] is None
    assert r.fake.states["input_boolean.tank_hold"][0] == "off"
    # The cleanup broke before its own alert: the release says what ended, and that it reads off.
    assert r.codes() == ["CS-804", "CS-806"]
    message = r.alert("CS-806")["message"]
    assert "ended (stopped: fill: the tank did not read full within 20 min)" in message
    assert "Everything now reads off; the hold was released" in message


def test_the_thread_recovers_first_then_reads_every_two_seconds_and_survives_an_error(rig):
    r = rig()
    r.config()
    passes = []
    real_poll = r.runner.poll

    def poll(busy=None):
        passes.append(r.clock.t)
        if len(passes) == 1:
            raise RuntimeError("one bad pass")
        return real_poll(busy)

    def sleep(seconds):
        r.clock.t += seconds
        if len(passes) == 3:
            r.runner._exiting = True

    r.runner.poll, r.runner._sleep = poll, sleep
    r.runner._run()
    assert passes == [0.0, 2.0, 4.0]
    assert any("one bad pass" in line for line in r.logs)


def test_a_batch_that_overruns_its_watchdog_is_ended(rig):
    r = rig()
    _full_batch(r)
    r.runner._watchdog = lambda batch, plan: 100.0
    r.ask("batch")
    r.runner.poll()
    assert r.status()[1]["handled_result"] == "stopped: premix: it ran past its watchdog"
    assert r.codes() == ["CS-806"]


# ------------------------------------------------------------------ restarts
def _interrupted(tmp_path, kind="batch", **extra):
    record = {"kind": kind, "at": BASE.isoformat(), "request": "abc", "by": "Ben",
              "off": ["switch.balance_power", "switch.bloom_power", "switch.tank_fill", "switch.tank_mixer",
                      "switch.mix_valve"],
              "hold": "input_boolean.tank_hold", "doses": {"balance": 300}, **extra}
    (tmp_path / "dosing_state.json").write_text(json.dumps(
        {"rooms": {"default": {"handled": "abc", "handled_result": "running", "inflight": record,
                               "history": [], "last": {}}}}), encoding="utf-8")


def test_a_batch_interrupted_by_a_restart_is_switched_off_and_never_resumed(rig, tmp_path):
    _interrupted(tmp_path)
    r = rig({"switch.tank_fill": ("on", {}), "switch.tank_mixer": ("on", {}), "switch.mix_valve": ("on", {}),
             "input_boolean.tank_hold": ("on", {})})
    assert r.runner.recover() is True
    for switch in ("switch.tank_fill", "switch.tank_mixer", "switch.mix_valve"):
        assert r.fake.states[switch][0] == "off", switch
    # Held until it reads off, and the batch's hold stays on until then.
    assert r.runner.holds(r.c.rooms[0]).startswith("dosing hardware still on: ")
    assert r.fake.states["input_boolean.tank_hold"][0] == "on" and r.codes() == []
    r.runner.poll()  # it all reads off: the hold goes off
    assert r.fake.states["input_boolean.tank_hold"][0] == "off"
    r.runner.poll()  # and reads off: released, and said once
    assert r.runner.holds(r.c.rooms[0]) is None
    assert r.codes() == ["CS-803"]
    message = r.alert("CS-803")["message"]
    assert "never resumes" in message and "Everything now reads off; the hold was released" in message
    saved = r.saved()
    assert saved["inflight"] is None
    assert saved["history"][0]["result"] == "interrupted by a restart"
    assert saved["history"][0]["doses"] == {"balance": 300}
    r.fake.calls.clear()
    assert r.runner.recover() is True and r.actions() == []  # once


def test_recovery_holds_while_home_assistant_is_down_and_the_exit_switches_off_first(rig, tmp_path):
    _interrupted(tmp_path, kind="dose")
    r = rig()
    r.runner._call = lambda *a, **k: False  # Home Assistant not answering yet
    assert r.runner.recover() is True  # holding needs nothing from it
    assert r.runner.holds(r.c.rooms[0]).startswith("dosing hardware still on: ")
    r.runner._get = lambda entity, timeout=8: (None, {}, None)
    r.runner.poll()
    assert r.saved()["inflight"]["kind"] == "dose" and r.codes() == []  # kept, and nothing to say yet
    r.runner._call, r.runner._get = r.call, r.fake.ha_get  # it answers: read off, released, said
    r.runner.poll()
    assert r.runner.holds(r.c.rooms[0]) is None and r.codes() == ["CS-803"]
    # A dose's record never names a hold: the batch's hold was never touched.
    assert ("turn_off", "input_boolean.tank_hold") not in r.actions()
    # Stopping mid-batch: switched off on the way out, the record kept for the next start, and the
    # batch's hold left on for it (the next start switches it off once the rest reads off).
    _interrupted(tmp_path)
    again = r.build(r.runner.path)
    r.set("switch.tank_fill", "on")
    r.set("input_boolean.tank_hold", "on")
    r.fake.calls.clear()
    again.exit()
    assert r.fake.states["switch.tank_fill"][0] == "off"
    assert r.fake.states["input_boolean.tank_hold"][0] == "on"
    assert r.saved()["inflight"]["kind"] == "batch"
    assert all(service == "turn_off" for service, _entity in r.actions())


# ------------------------------------------------------------------ the status, and old installs
def test_the_status_says_what_each_room_is_doing(rig):
    r = rig()
    r.config(pumps=(BALANCE, BLOOM))
    r.runner.poll()
    state, status = r.status()
    assert state == "idle" and set(status["pumps"]) == {"balance", "bloom"}
    assert status["pumps"]["bloom"] == {"state": "idle", "flow_ml_s": 5.0, "target_ml": None,
                                        "started_at": None, "expected_s": None, "last": None}
    assert status["batch"]["step"] == "idle" and status["handled"] is None
    seen = []
    r.clock.at(3, lambda: seen.append(r.status()))
    r.ask(ml=100)
    r.runner.poll()
    during_state, during = seen[0]
    assert during_state == "dosing"
    assert during["pumps"]["balance"] == {"state": "dosing", "flow_ml_s": 10.0, "target_ml": 100,
                                          "started_at": BASE.isoformat(), "expected_s": 10.0, "last": None}
    r.fake.set_state(CONFIG, "unknown", {})  # the integration can't read its store
    r.runner.poll()
    assert r.status()[0] == "unavailable"
    r.set("binary_sensor.balance_dosing", "unavailable")
    r.config()
    r.clock.t += dosing_runner.REFRESH_S
    r.runner.poll()
    assert r.status()[1]["pumps"]["balance"]["state"] == "unavailable"


def test_the_status_carries_when_it_was_published_and_is_published_every_minute(rig):
    """The page tells a stale controller by `updated_at`: republished at least once a minute when
    nothing changes, and not more often than things change."""
    r = rig()
    r.config()
    r.runner.poll()
    assert r.status()[1]["updated_at"] == BASE.isoformat()
    r.clock.t = 30
    r.runner.poll()
    assert r.status()[1]["updated_at"] == BASE.isoformat()  # nothing new to say
    r.clock.t = 61
    r.runner.poll()
    assert r.status()[1]["updated_at"] == (BASE + timedelta(seconds=61)).isoformat()


def test_an_install_without_dosing_runs_exactly_as_before(rig):
    """No dosing_config sensor (an integration from before dosing): nothing is read twice, switched,
    published or held."""
    r = rig()
    assert r.runner.recover() is True
    r.runner.poll()
    assert r.fake.calls == [] and STATUS not in r.fake.sets
    room = r.c.rooms[0]
    with_dosing = r.c._blocked(room, 1)
    r.c.dosing = None
    assert r.c._blocked(room, 1) == with_dosing


def test_the_controller_starts_without_dosing_if_it_cannot_be_built(monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("no")

    monkeypatch.setattr(dosing_runner, "DosingRunner", broken)
    c, _fake = _build({"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                                     "valves": {"1": "switch.v1"}}})
    assert c.dosing is None
    assert c._dosing_hold(c.rooms[0]) is None
    c._start_dosing()  # nothing to start, and no error


def test_the_controller_builds_its_runner_and_recovers_before_the_first_loop(monkeypatch, tmp_path):
    c, _fake = _build({"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                                     "valves": {"1": "switch.v1"}}})
    assert isinstance(c.dosing, dosing_runner.DosingRunner)
    assert c.dosing.path.endswith("dosing_state.json")
    order = []

    class Stop(BaseException):
        pass

    monkeypatch.setattr(c.dosing, "recover", lambda: order.append("recover"))
    monkeypatch.setattr(c.dosing, "start", lambda: order.append("thread"))
    monkeypatch.setattr(c, "_log_timezone", lambda: None)
    monkeypatch.setattr(c, "loop_once", lambda now: order.append("loop"))

    def sleep(_seconds):
        raise Stop()

    monkeypatch.setattr(controller.time, "sleep", sleep)
    with pytest.raises(Stop):
        c.run()
    assert order == ["recover", "thread", "loop"]

    def broken():
        raise RuntimeError("a bug")

    order.clear()
    monkeypatch.setattr(c.dosing, "recover", broken)  # the thread still starts, and tries again
    with pytest.raises(Stop):
        c.run()
    assert order == ["thread", "loop"]


def test_every_dosing_code_goes_out_through_the_alert_list():
    c, fake = _build({"num_zones": 1})
    for code in ("CS-801", "CS-802", "CS-803", "CS-804", "CS-805", "CS-806", "CS-807"):
        assert c._dosing_alert(c.rooms[0], code, "a title", "a message") is True
    assert c._dosing_alert(c.rooms[0], "CS-899", "made up", "never shown") is True  # never kept
    ids = [d["notification_id"] for dom, svc, d in fake.calls if dom == "persistent_notification"]
    assert ids == [f"f2_dosing_default_{n}" for n in (801, 802, 803, 804, 805, 806, 807)]
    # One notification per event: a second event within 30 minutes is its own card, and an update of
    # the same event (it reads off now) replaces its card at once: the runner paces the repeats.
    assert c._dosing_alert(c.rooms[0], "CS-801", "a title", "another", "balance_2026_09_28t02") is True
    assert fake.calls[-1][2]["notification_id"] == "f2_dosing_default_801_balance_2026_09_28t02"
    assert c._dosing_alert(c.rooms[0], "CS-801", "a title", "it reads off now",
                           "balance_2026_09_28t02") is True
    assert fake.calls[-1][2]["message"].startswith("it reads off now")
