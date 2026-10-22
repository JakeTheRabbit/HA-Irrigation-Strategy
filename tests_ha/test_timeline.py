"""timeline_get and timeline_summary through a real Home Assistant (Pacific/Auckland): two rooms, events stored
with journal_append, the controller's projection_app for one room only, the supply descriptor for the pump load,
read by an ordinary signed-in user, in v1 and API v2.

The producers are not built yet (Task 8's shot data, Task 15's projection_app): the events and the sensor here are
synthetic, shaped by their contracts (tests/test_timeline.py has them)."""

from datetime import datetime, timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_real_flow import ZONES
from test_setup_entry import _install

from custom_components.crop_steering.generated.defaults import SIZING_DEFAULTS
from custom_components.crop_steering.generated.guards import zone_demand_lph
from custom_components.crop_steering.generated.ids import new_id

DOMAIN = "crop_steering"
TENT, VEG = "room:tent_", "room:veg_"
PUMP = "switch.main_pump"
VEG_VALVE = "switch.veg_valve_1"


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


async def _call(hass, user, name, **data):
    return await hass.services.async_call(
        DOMAIN,
        name,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def _veg_room(hass):
    """A second room, Veg, with no pump."""
    hass.states.async_set(VEG_VALVE, "off")
    hass.states.async_set("sensor.veg_vwc", "40", {"unit_of_measurement": "%"})
    flow = hass.config_entries.flow
    result = await flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "room"  # a room beside the first one
    result = await flow.async_configure(result["flow_id"], {"room_name": "Veg"})
    result = await flow.async_configure(result["flow_id"], {"num_zones": 1})
    result = await flow.async_configure(
        result["flow_id"],
        {
            **ZONES,
            "zone_1_name": "Veg",
            "zone_1_switch": VEG_VALVE,
            "zone_1_vwc": ["sensor.veg_vwc"],
            "zone_1_ec": [],
        },
    )
    assert result["step_id"] == "hardware", result.get("errors")
    result = await flow.async_configure(result["flow_id"], {"plumbing": "valves_only"})
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()


def _ev(kind, at, intent, **over):
    return {
        "v": 1,
        "id": new_id(),
        "ts": at.isoformat(),
        "kind": kind,
        "zone": 1,
        "outcome": "ok",
        "source": {"actor": "engine"},
        "correlation": {"intent_id": intent},
        "data": {},
        **over,
    }


async def test_two_rooms_48h_round_trip(hass, hass_admin_user, hass_read_only_user):
    await hass.config.async_set_time_zone("Pacific/Auckland")
    hass.states.async_set(PUMP, "off")
    await _install(hass, {"pump_switch": PUMP, "plumbing": "pump_valves"})
    await _veg_room(hass)
    await hass.data[DOMAIN]["_journal"]._ready.wait()
    demand = zone_demand_lph(
        4, SIZING_DEFAULTS["drippers_per_plant"], SIZING_DEFAULTS["dripper_flow_rate"]
    )
    await _call(
        hass,
        hass_admin_user,
        "supply_save",
        expected_revision=0,
        irrigation_pumps=[{"entity_id": PUMP, "max_flow_lph": demand * 4}],
    )

    now = dt_util.now()
    shot_at = now - timedelta(hours=2)
    tent = new_id()
    await _call(
        hass,
        hass_admin_user,
        "journal_append",
        room_id=TENT,
        events=[
            _ev("shot.started", shot_at, tent, data={"phase": "P1", "reason": "P1 ramp shot 1",
                                                     "commanded_l": 1.5, "vwc_before": 40.0}),
            _ev("shot.completed", shot_at + timedelta(seconds=60), tent,
                data={"elapsed_s": 60, "commanded_l": 1.5, "metered_l": None}),
        ],
    )
    veg = new_id()
    await _call(
        hass,
        hass_admin_user,
        "journal_append",
        room_id=VEG,
        events=[
            _ev("shot.started", shot_at, veg),
            _ev("shot.aborted", shot_at + timedelta(seconds=10), veg, outcome="failed", code="CS-302"),
        ],
    )
    planned_at = now + timedelta(hours=1)
    hass.states.async_set(
        "sensor.crop_steering_tent_projection_app",
        "2",
        {
            "intents": [
                {"id": "t1", "zone": 1, "at": planned_at.isoformat(), "duration_s": 90,
                 "source": "timer", "program_id": "p", "expected": False},
                {"id": "e1", "zone": 1, "at": (now - timedelta(hours=1)).isoformat(),
                 "duration_s": 30, "source": "engine", "expected": True},
            ]
        },
    )
    await hass.async_block_till_done()

    start, end = now - timedelta(hours=24), now + timedelta(hours=24)
    out = await _call(
        hass,
        hass_read_only_user,
        "timeline_get",
        rooms=[TENT, VEG],
        start=start.isoformat(),
        end=end.isoformat(),
    )
    tent_room, veg_room = out["rooms"]
    assert (tent_room["room_id"], veg_room["room_id"]) == (TENT, VEG)
    assert tent_room["planned_source"] == "projection_app"
    assert veg_room["planned_source"] == "unavailable"
    (row,) = tent_room["rows"]
    shot, planned = row["blocks"]
    assert (shot["kind"], shot["status"], shot["id"]) == ("shot", "done", tent)
    assert (shot["litres"], shot["metered_l"], shot["reason"]) == (1.5, None, "P1 ramp shot 1")
    assert shot["vwc_expected"] is None  # not sent: None, never guessed
    assert datetime.fromisoformat(shot["start"]).utcoffset() == dt_util.as_local(shot_at).utcoffset()
    assert (planned["id"], planned["kind"], planned["skippable"]) == ("t1", "planned", True)
    assert [p["pct"] for p in tent_room["pump_load"]] == [pytest.approx(25.0), 0.0]
    assert [p["pct"] for p in veg_room["pump_load"]] == [None, None]  # no pump known
    assert tent_room["lights"] and all(
        datetime.fromisoformat(w["on"]).utcoffset()
        == dt_util.as_local(datetime.fromisoformat(w["on"])).utcoffset()
        for w in tent_room["lights"]
    )
    (veg_row,) = veg_room["rows"]
    (aborted,) = veg_row["blocks"]
    assert (aborted["status"], aborted["code"]) == ("error", "CS-302")
    assert out["errors"]["count"] == 1
    assert out["errors"]["markers"][0]["room_id"] == VEG

    v2 = await _call(
        hass,
        hass_read_only_user,
        "timeline_get",
        api=2,
        rooms=[TENT, VEG],
        start=start.isoformat(),
        end=end.isoformat(),
        zones=[1],
    )
    assert v2["ok"] is True and v2["data"]["errors"]["count"] == 1

    too_long = (start + timedelta(hours=48, seconds=1)).isoformat()
    with pytest.raises(HomeAssistantError, match="timeline span is at most 48 h"):
        await _call(
            hass, hass_read_only_user, "timeline_get", rooms=[TENT], start=start.isoformat(), end=too_long
        )
    refused = await _call(
        hass, hass_read_only_user, "timeline_get", api=2, rooms=[TENT],
        start=start.isoformat(), end=too_long,
    )
    assert refused["ok"] is False and refused["error"]["code"] == "invalid"

    day = dt_util.as_local(shot_at).date().isoformat()
    summary = await _call(
        hass, hass_read_only_user, "timeline_summary", rooms=[TENT, VEG], days=[day]
    )
    assert summary == {
        "days": [
            {
                "date": day,
                "rooms": [
                    {"room_id": TENT, "shots": 1, "failed": 0, "warnings": 0, "held": 0, "queued": 0},
                    {"room_id": VEG, "shots": 1, "failed": 1, "warnings": 0, "held": 0, "queued": 0},
                ],
            }
        ]
    }
    days = [(dt_util.now().date() - timedelta(days=d)).isoformat() for d in range(15)]
    with pytest.raises(HomeAssistantError, match="at most 14 days"):
        await _call(hass, hass_read_only_user, "timeline_summary", rooms=[TENT], days=days)
