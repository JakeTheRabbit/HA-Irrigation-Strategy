"""Plumbing layouts: a tent with ONE switch must irrigate; a pumped room must never lose its pump quietly.

Reported from a first install: a single-zone tent where one switch (the pump on a smart plug)
is the whole fertigation system. Setup accepted it - its own tooltip said "leave the pump
empty if..." - and the controller then held the room forever, because it required a pump AND a
mainline AND a valve as three different switches.

"No pump" is a DECLARATION (`plumbing` in the descriptor), never an inference from an empty
mapping: on a pumped install a pump mapping cleared by accident must keep holding loudly rather
than open valves with no water behind them. A descriptor without `plumbing` - every install that
predates it - keeps the original three-stage rule and the original setup fingerprint.
"""
import json

import pytest

import controller
import fake_ha

KILL = "input_boolean.kill"
DESCRIPTOR = "sensor.crop_steering_engine_config"
TENT = "switch.gt1_irrigation_switch"


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


def _descriptor(**attrs):
    base = {"prefix": "", "slug": "default", "num_zones": 1, "active": True,
            "active_zone_ids": [1], "enable_flag": KILL, "setup_revision": 1}
    base.update(attrs)
    return base


@pytest.fixture
def build(monkeypatch):
    """Construct a controller whose default room comes from the published descriptor, the way a
    real install does (no add-on `hardware` option)."""
    def _build(descriptor, *, options=None, switches=()):
        fake = fake_ha.FakeHA()
        fake.set_state(DESCRIPTOR, "default", descriptor)
        # Setup is adopted with the kill switch OFF and hardware OFF, then the operator arms it.
        fake.set_state(KILL, "off")
        for entity in switches:
            fake.set_state(entity, "off")
        monkeypatch.setattr(controller, "load_options",
                            lambda: {"num_zones": 1, "enable_flag": KILL, **(options or {})})
        for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
            monkeypatch.setattr(controller, name, getattr(fake, name))
        clock = Clock()
        monkeypatch.setattr(controller.time, "sleep", clock.sleep)
        monkeypatch.setattr(controller.time, "monotonic", clock.monotonic)
        c = controller.Controller()
        for entity in (KILL, "switch.crop_steering_system_enabled",
                       "switch.crop_steering_auto_irrigation_enabled",
                       "switch.crop_steering_zone_1_enabled"):
            fake.set_state(entity, "on")
        fake.calls.clear()
        return c, fake, clock
    return _build


def _switch_calls(fake):
    return [(service, data["entity_id"]) for domain, service, data in fake.calls if domain == "switch"]


# ------------------------------------------------------------------ the declared layouts
@pytest.mark.parametrize("layout, needs", [
    ("valves_only", (False, False)),
    ("pump_valves", (True, False)),
    ("mainline_valves", (False, True)),
    ("pump_mainline_valves", (True, True)),
    (None, (True, True)),          # a descriptor from before layouts existed
    ("", (True, True)),
    ("something_newer", (True, True)),  # an unknown layout is never read as "needs less"
])
def test_a_layout_names_the_stages_it_needs_and_anything_else_is_the_original_three(layout, needs):
    assert controller.plumbing_needs(layout) == needs


def test_a_tent_descriptor_maps_with_only_its_one_switch():
    hw = controller.hardware_from_descriptor(
        _descriptor(plumbing="valves_only", pump="", mainline="", valves={"1": TENT}))
    assert hw == {"pump": None, "mainline": None, "valves": {1: TENT}, "plumbing": "valves_only"}


@pytest.mark.parametrize("descriptor", [
    _descriptor(pump="", mainline="", valves={"1": "switch.v1"}),              # legacy, pump cleared
    _descriptor(pump="switch.p", mainline="", valves={"1": "switch.v1"}),      # legacy, mainline cleared
    _descriptor(plumbing="pump_valves", pump="", valves={"1": "switch.v1"}),   # declared pump, none mapped
    _descriptor(plumbing="mainline_valves", mainline="", valves={"1": "switch.v1"}),
    _descriptor(plumbing="valves_only", valves={}),                             # nothing to open at all
    _descriptor(plumbing="valves_only", valves={"1": ""}),
])
def test_a_room_missing_a_stage_its_layout_needs_is_unmapped_not_quietly_downgraded(descriptor):
    assert controller.hardware_from_descriptor(descriptor) is None


def test_a_mapped_stage_is_kept_even_when_the_layout_does_not_need_it():
    """It stays in the OFF checks and the safe-off; a layout only relaxes what is REQUIRED."""
    hw = controller.hardware_from_descriptor(
        _descriptor(plumbing="valves_only", pump="switch.p", valves={"1": "switch.v1"}))
    assert hw["pump"] == "switch.p"


# ------------------------------------------------------------------ the tent, end to end
def test_a_single_switch_tent_irrigates_with_exactly_one_on_and_one_off(build):
    c, fake, clock = build(_descriptor(plumbing="valves_only", pump="", mainline="",
                                       valves={"1": TENT}), switches=[TENT])
    room = c.rooms[0]
    assert room.setup_revision == 1 and room._setup_pending is None  # adopted with no pump to check
    assert "no hardware mapped" not in (c._blocked(room, 1) or "")

    c._execute_shot(room, 1, 30, 5, flow_lps=0.01)

    assert _switch_calls(fake) == [("turn_on", TENT), ("turn_off", TENT)]
    assert fake.ha_get(TENT)[0] == "off"
    assert room.hardware_fault is None
    assert room.state[1]["shots"] == 1
    assert room.state[1]["daily_vol"] == pytest.approx(0.30)  # 0.01 L/s x 30 s
    # No 2 s pump prime, no 1 s mainline settle and no depressurise wait: there is nothing
    # upstream to wait for. Only the shot itself and the OFF read-back take time.
    assert clock.seconds == pytest.approx(30 + controller.CONFIRM_FIRST_READ_S)


def test_a_pump_and_valve_room_primes_the_pump_but_never_touches_a_mainline(build):
    c, fake, _clock = build(_descriptor(plumbing="pump_valves", pump="switch.p", mainline="",
                                        valves={"1": "switch.v1"}), switches=["switch.p", "switch.v1"])
    c._execute_shot(c.rooms[0], 1, 10, 5, flow_lps=0.01)
    assert _switch_calls(fake) == [("turn_on", "switch.p"), ("turn_on", "switch.v1"),
                                   ("turn_off", "switch.v1"), ("turn_off", "switch.p")]
    assert c.rooms[0].hardware_fault is None


def test_the_original_three_stage_sequence_is_unchanged(build):
    c, fake, _clock = build(_descriptor(pump="switch.p", mainline="switch.m", valves={"1": "switch.v1"}),
                            switches=["switch.p", "switch.m", "switch.v1"])
    c._execute_shot(c.rooms[0], 1, 10, 5, flow_lps=0.01)
    assert _switch_calls(fake) == [
        ("turn_on", "switch.p"), ("turn_on", "switch.m"), ("turn_on", "switch.v1"),
        ("turn_off", "switch.v1"), ("turn_off", "switch.m"), ("turn_off", "switch.p")]


# ------------------------------------------------------------------ fail-safe is not weakened
def test_a_pumped_room_whose_pump_mapping_was_cleared_holds_and_says_what_is_missing(build):
    c, fake, _clock = build(_descriptor(pump="", mainline="switch.m", valves={"1": "switch.v1"}),
                            switches=["switch.m", "switch.v1"])
    block = c._blocked(c.rooms[0], 1)
    assert block and ("no hardware mapped" in block or "Invalid setup" in block)
    c._loop_room(c.rooms[0], controller.datetime.now())
    assert not any(service == "turn_on" for service, _entity in _switch_calls(fake))


def test_the_hold_names_the_missing_stage(build):
    c, _fake, _clock = build(_descriptor(pump="switch.p", mainline="switch.m",
                                         valves={"1": "switch.v1"}),
                             switches=["switch.p", "switch.m", "switch.v1"])
    room = c.rooms[0]
    room.hw = {"pump": None, "mainline": "switch.m", "valves": {1: "switch.v1"}}
    assert "set pump in" in c._blocked(room, 1)
    room.hw = {"pump": None, "mainline": None, "valves": {1: "switch.v1"}, "plumbing": "valves_only"}
    assert "no hardware mapped" not in (c._blocked(room, 1) or "")
    room.hw = {"pump": None, "mainline": None, "valves": {}, "plumbing": "valves_only"}
    assert "this zone's valve" in c._blocked(room, 1)


def test_a_single_switch_that_will_not_turn_off_latches_a_fault_and_is_asked_again(build, monkeypatch):
    c, fake, _clock = build(_descriptor(plumbing="valves_only", valves={"1": TENT}), switches=[TENT])

    def stuck_on(domain, service, **data):
        fake.calls.append((domain, service, data))
        if service == "turn_on":
            fake.set_state(data["entity_id"], "on")
        return True  # HA accepts the turn_off, but the relay never releases

    monkeypatch.setattr(controller, "ha_call", stuck_on)
    c._execute_shot(c.rooms[0], 1, 10, 5, flow_lps=0.01)

    assert c.rooms[0].hardware_fault  # durable hold: no next shot until a human clears it
    # It is the only shut-off there is, so it is retried rather than "cutting a pump" that isn't there.
    assert _switch_calls(fake).count(("turn_off", TENT)) >= 2
    assert c.rooms[0].state[1]["shots"] == 1  # water WAS delivered; the cap must see it


def test_a_tent_valve_that_refuses_to_open_is_reported_without_inventing_a_pump(build, monkeypatch):
    c, fake, _clock = build(_descriptor(plumbing="valves_only", valves={"1": TENT}), switches=[TENT])
    original = fake.ha_call
    monkeypatch.setattr(controller, "ha_call",
                        lambda domain, service, **data: False
                        if (service, data.get("entity_id")) == ("turn_on", TENT)
                        else original(domain, service, **data))
    c._execute_shot(c.rooms[0], 1, 10, 5, flow_lps=0.01)
    alert = next(data for domain, service, data in fake.calls
                 if (domain, service) == ("persistent_notification", "create"))
    assert "valve command failed" in alert["title"]
    assert "Pump" not in alert["message"] and "shot NOT counted" in alert["message"]
    assert c.rooms[0].state[1]["shots"] == 0


# ------------------------------------------------------------------ in-place upgrade
def test_an_existing_installs_setup_fingerprint_is_byte_identical_so_restart_resume_survives_the_upgrade():
    """A controller from before layouts saved this exact string. If the new one hashed the same
    descriptor differently, every upgraded install would fail resume and sit blocked behind a
    disarm cycle nobody knew was needed (the 2026-09-20 incident, again)."""
    attrs = _descriptor(pump="switch.p", mainline="switch.m", valves={"1": "switch.v1"},
                        feed_ec_sensor="sensor.feed_ec", feed_ph_sensor="")
    room = type("Room", (), {"enable_flag": KILL})()
    saved_by_0_14 = json.dumps({
        "active": True, "zones": [1], "pump": "switch.p", "mainline": "switch.m",
        "valves": {"1": "switch.v1"}, "enable_flag": KILL,
        "feed_ec_sensor": "sensor.feed_ec", "feed_ph_sensor": "",
    }, sort_keys=True)
    assert controller.Controller._setup_fingerprint(attrs, room) == saved_by_0_14
    # ...and an integration that publishes the mS/cm default changes nothing either.
    assert controller.Controller._setup_fingerprint({**attrs, "feed_ec_factor": 1.0}, room) == saved_by_0_14


def test_changing_the_layout_or_the_feed_unit_is_a_setup_change_that_needs_adopting():
    room = type("Room", (), {"enable_flag": KILL})()
    base = _descriptor(pump="switch.p", mainline="switch.m", valves={"1": "switch.v1"},
                       feed_ec_sensor="sensor.feed_ec")
    fingerprint = controller.Controller._setup_fingerprint
    assert fingerprint({**base, "plumbing": "pump_mainline_valves"}, room) != fingerprint(base, room)
    assert fingerprint({**base, "feed_ec_factor": 0.001}, room) != fingerprint(base, room)


# ------------------------------------------------------------------ feed EC in the probe's own unit
def _fresh(fake, entity, value):
    fake.set_state(entity, value)  # FakeHA stamps a current last_updated, so it reads as fresh


def test_a_microsiemens_feed_probe_is_gated_in_millisiemens(build):
    c, fake, _clock = build(_descriptor(plumbing="valves_only", valves={"1": TENT},
                                        feed_ec_sensor="sensor.feed_ec", feed_ec_factor=0.001),
                            switches=[TENT])
    room = c.rooms[0]
    assert room.feed_ec_factor == 0.001
    _fresh(fake, "sensor.feed_ec", "2300")
    assert c._read_feed_ec(room) == pytest.approx(2.3)
    _fresh(fake, "sensor.feed_ec", "25000")  # 25 mS/cm: outside the plausible band in ANY unit
    assert c._read_feed_ec(room) is None


def test_without_a_published_factor_an_out_of_band_reading_still_fails_closed(build):
    """An older integration publishes no factor. A uS/cm probe then reads as a dead probe (None),
    which closes the source-water gate - the safe direction - rather than passing 2300 'mS/cm'."""
    c, fake, _clock = build(_descriptor(plumbing="valves_only", valves={"1": TENT},
                                        feed_ec_sensor="sensor.feed_ec"), switches=[TENT])
    _fresh(fake, "sensor.feed_ec", "2300")
    assert c.rooms[0].feed_ec_factor == 1.0
    assert c._read_feed_ec(c.rooms[0]) is None


def test_the_factor_describes_the_integrations_probe_not_an_addon_option_override(build):
    c, fake, _clock = build(_descriptor(plumbing="valves_only", valves={"1": TENT},
                                        feed_ec_sensor="sensor.integration_probe", feed_ec_factor=0.001),
                            options={"feed_ec_sensor": "sensor.addon_option_probe"}, switches=[TENT])
    room = c.rooms[0]
    # The add-on option is set before adoption; adoption then follows the descriptor.
    room.feed_ec_sensor = "sensor.addon_option_probe"
    room.feed_ec_factor = controller.descriptor_feed_ec_factor(
        {"feed_ec_sensor": "sensor.integration_probe", "feed_ec_factor": 0.001}, room.feed_ec_sensor)
    assert room.feed_ec_factor == 1.0
    _fresh(fake, "sensor.addon_option_probe", "2.4")
    assert c._read_feed_ec(room) == pytest.approx(2.4)


@pytest.mark.parametrize("published", ["garbage", None, 0, -1, float("inf"), float("nan"), 1e6, [], {}])
def test_a_malformed_factor_reads_as_millisiemens(published):
    descriptor = {"feed_ec_sensor": "sensor.feed_ec", "feed_ec_factor": published}
    assert controller.descriptor_feed_ec_factor(descriptor, "sensor.feed_ec") == 1.0
