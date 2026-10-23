"""Presets and copy_config (G10) through a real Home Assistant: zone 3's settings copied to zones 1
and 2 of the same room, previewed first (nothing written), then written through number.set_value
and select.select_option, each read back; the journal holds one target.changed per write, named
for the copy and its caller; a preset saved once lists for every caller."""

import pytest
from homeassistant import config_entries
from homeassistant.core import Context
from homeassistant.data_entry_flow import FlowResultType

DOMAIN = "crop_steering"
ROOM = "room:room_"
SINCE = "2000-01-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    hass.config.components.add("frontend")
    yield


def number(zone, key):
    return f"number.crop_steering_room_zone_{zone}_{key}"


def p2_mode(zone):
    return f"select.crop_steering_room_zone_{zone}_p2_mode"


async def _three_zones(hass):
    hass.states.async_set("sensor.vwc", "41", {"unit_of_measurement": "%"})
    for z in (1, 2, 3):
        hass.states.async_set(f"switch.valve_{z}", "off")
    flow = hass.config_entries.flow
    result = await flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await flow.async_configure(result["flow_id"], {"name": "Room"})
    result = await flow.async_configure(result["flow_id"], {"num_zones": 3})
    answers = {"zone_1_vwc": ["sensor.vwc"]}
    for z in (1, 2, 3):
        answers.update(
            {
                f"zone_{z}_name": f"Bench {z}",
                f"zone_{z}_active": True,
                f"zone_{z}_switch": f"switch.valve_{z}",
                f"zone_{z}_plant_count": 4,
            }
        )
    result = await flow.async_configure(result["flow_id"], answers)
    assert result["step_id"] == "hardware", result.get("errors")
    result = await flow.async_configure(result["flow_id"], {"plumbing": "valves_only"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def _call(hass, user, service, **data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )


async def _set(hass, entity_id, value):
    if entity_id.startswith("select."):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": value},
            blocking=True,
        )
    else:
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": value},
            blocking=True,
        )


async def test_copy_zone_3_to_zones_1_2_writes_and_reads_back(hass, hass_admin_user):
    await _three_zones(hass)
    await _set(hass, number(3, "p2_shot_size"), 6.5)
    await _set(hass, number(3, "p2_time_between_shots"), 45)
    await _set(hass, p2_mode(3), "Timed")
    await _set(
        hass, number(2, "p2_shot_size"), 6.5
    )  # zone 2 already has zone 3's shot size
    program = {
        "name": "Mothers AM",
        "type": "recycle",
        "zones": [3],
        "duration_s": 120,
        "interval_min": 30,
        "window": {"kind": "custom", "from": "08:00", "to": "12:00"},
    }
    await _call(
        hass,
        hass_admin_user,
        "timer_program_set",
        room_id=ROOM,
        expected_revision=0,
        program=program,
    )
    before = {
        z: float(hass.states.get(number(z, "p2_shot_size")).state) for z in (1, 2)
    }
    to = [{"room_id": ROOM, "zone": 1}, {"room_id": ROOM, "zone": 2}]
    args = {
        "from": {"room_id": ROOM, "zone": 3},
        "to": to,
        "sections": ["targets", "phase_timing", "water_limits", "timers"],
    }

    preview = await _call(hass, hass_admin_user, "copy_config", preview=True, **args)
    assert "applied" not in preview
    rows = {
        (r["target"]["zone"], r["key"]): (r["old"], r["new"]) for r in preview["diff"]
    }
    assert rows[(1, "p2_shot_size")] == (before[1], 6.5)
    assert (2, "p2_shot_size") not in rows  # unchanged rows are not listed
    assert rows[(1, "p2_mode")] == ("Moisture", "Timed")
    assert rows[(2, "p2_time_between_shots")][1] == 45
    assert (
        rows[(1, "timer")][0] is None and rows[(1, "timer")][1]["name"] == "Mothers AM"
    )
    assert float(hass.states.get(number(1, "p2_shot_size")).state) == before[1]

    done = await _call(hass, hass_admin_user, "copy_config", preview=False, **args)
    assert done["applied"] and {a["readback"] for a in done["applied"]} == {"verified"}
    assert [(a["target"]["zone"], a["key"]) for a in done["applied"]] == [
        (r["target"]["zone"], r["key"]) for r in done["diff"]
    ]
    for z in (1, 2):
        assert float(hass.states.get(number(z, "p2_shot_size")).state) == 6.5
        assert float(hass.states.get(number(z, "p2_time_between_shots")).state) == 45
        assert hass.states.get(p2_mode(z)).state == "Timed"
    # The zones joined zone 3's timer program rather than getting copies of it.
    (timer,) = (await _call(hass, hass_admin_user, "timer_program_list", room_id=ROOM))[
        "programs"
    ]
    assert (timer["name"], timer["zones"]) == ("Mothers AM", [1, 2, 3])
    # Read back: the same copy now changes nothing.
    again = await _call(hass, hass_admin_user, "copy_config", preview=True, **args)
    assert again["diff"] == []

    # One target.changed per write, by the admin, named for the copy (not a second from the log).
    hub = hass.data[DOMAIN]["_journal"]
    await hub._ready.wait()
    await hass.async_block_till_done()
    events = (
        await _call(
            hass,
            hass_admin_user,
            "journal_query",
            room_id=ROOM,
            since=SINCE,
            kinds=["target.changed"],
        )
    )["events"]
    copied = [
        e for e in events if e["source"]["detail"] == "copy from room:room_ zone 3"
    ]
    # (the timer rows journal config.changed in the timer store instead)
    assert len(copied) == len([a for a in done["applied"] if a["key"] != "timer"])
    assert {e["source"]["actor"] for e in copied} == {"manual"}
    assert {e["readback"] for e in copied} == {"verified"}
    copied_ids = {e["data"]["entity_id"] for e in copied}
    assert not [
        e
        for e in events
        if e["source"]["detail"] is None
        and e["data"]["entity_id"] in copied_ids
        and e["data"]["new"] == 6.5
        and e["zone"] in (1, 2)
    ]


async def test_a_preset_saved_once_is_listed_for_every_caller(hass, hass_admin_user):
    from homeassistant.auth.const import GROUP_ID_USER
    from pytest_homeassistant_custom_component.common import MockUser

    await _three_zones(hass)
    await _set(hass, number(3, "p2_shot_size"), 6.5)
    saved = await _call(
        hass,
        hass_admin_user,
        "preset_save",
        name="Week 3",
        scope="targets",
        expected_revision=0,
        **{"from": {"room_id": ROOM, "zone": 3}},
    )
    assert saved["preset"]["values"]["targets"]["p2_shot_size"] == 6.5
    assert saved["skipped"] == []  # every setting of the zone read
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    staff = MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)
    listed = await _call(hass, staff, "preset_list")
    assert [p["name"] for p in listed["presets"]] == ["Week 3"]

    applied = await _call(
        hass,
        hass_admin_user,
        "preset_apply",
        preset_id=saved["preset"]["id"],
        to=[{"room_id": ROOM, "zone": 1}],
    )
    assert {a["key"]: a["readback"] for a in applied["applied"]}[
        "p2_shot_size"
    ] == "verified"
    assert float(hass.states.get(number(1, "p2_shot_size")).state) == 6.5
    await _call(
        hass,
        hass_admin_user,
        "preset_delete",
        id=saved["preset"]["id"],
        expected_revision=1,
    )
    assert (await _call(hass, staff, "preset_list"))["presets"] == []


async def test_all_covers_every_per_zone_number(hass):
    """Every number a zone has is in a section `all` copies, or named as never copied: a new zone
    number that no section covers fails here instead of being left behind by a copy."""
    from custom_components.crop_steering import presets

    await _three_zones(hass)
    (numbers,) = hass.data[DOMAIN]["_numbers"].values()
    zone_keys = {k.removeprefix("zone_1_") for k in numbers if k.startswith("zone_1_")}
    covered = {k for s in presets.SCOPES["all"] for k in presets.SECTIONS[s]}
    assert zone_keys and zone_keys - covered - set(presets.NOT_COPIED) == set()


async def test_a_copy_from_a_zone_with_no_timer_is_ok_and_keeps_the_target_in_its_own(
    hass, hass_admin_user
):
    await _three_zones(hass)
    await _set(hass, number(2, "p2_shot_size"), 7.5)
    program = {
        "name": "Mothers AM",
        "type": "recycle",
        "zones": [1],
        "duration_s": 120,
        "interval_min": 30,
        "window": {"kind": "custom", "from": "08:00", "to": "12:00"},
    }
    await _call(
        hass,
        hass_admin_user,
        "timer_program_set",
        room_id=ROOM,
        expected_revision=0,
        program=program,
    )
    out = await _call(
        hass,
        hass_admin_user,
        "copy_config",
        api=2,
        preview=False,
        to=[{"room_id": ROOM, "zone": 1}],
        sections=["targets", "timers"],
        **{"from": {"room_id": ROOM, "zone": 2}},
    )
    # Zone 2 has no timer program: named in `missing`, never a refusal of the copy.
    assert out["ok"] is True, out
    assert out["readback"]["status"] == "verified"
    assert out["data"]["missing"] == [
        {
            "target": {"room_id": ROOM, "zone": 1},
            "key": "timer",
            "reason": "source zone has no timer program",
        }
    ]
    assert float(hass.states.get(number(1, "p2_shot_size")).state) == 7.5
    (timer,) = (await _call(hass, hass_admin_user, "timer_program_list", room_id=ROOM))[
        "programs"
    ]
    assert timer["zones"] == [1]


async def test_a_copy_refused_in_part_answers_the_events_of_what_it_wrote(
    hass, hass_admin_user, monkeypatch
):
    from custom_components.crop_steering import presets

    await _three_zones(hass)
    await _set(hass, number(3, "p2_shot_size"), 6.5)
    await _set(hass, number(3, "p2_time_between_shots"), 45)
    write_all = presets._write_all

    async def refuse_spacing(hass, writes, pending, errors, context):
        spacing = [i for i in pending if writes[i]["key"] == "p2_time_between_shots"]
        for i in spacing:
            errors[i] = "out of range"
        await write_all(
            hass, writes, [i for i in pending if i not in spacing], errors, context
        )

    monkeypatch.setattr(presets, "_write_all", refuse_spacing)
    out = await _call(
        hass,
        hass_admin_user,
        "copy_config",
        api=2,
        preview=False,
        to=[{"room_id": ROOM, "zone": 1}],
        sections=["targets", "phase_timing"],
        **{"from": {"room_id": ROOM, "zone": 3}},
    )
    assert out["ok"] is False and out["error"]["code"] == "guard_refused", out
    assert "p2_time_between_shots: out of range" in out["error"]["message"]
    await hass.data[DOMAIN]["_journal"]._ready.wait()
    await hass.async_block_till_done()
    events = (
        await _call(
            hass,
            hass_admin_user,
            "journal_query",
            room_id=ROOM,
            since=SINCE,
            kinds=["target.changed"],
        )
    )["events"]
    by_id = {e["id"]: e for e in events}
    mine = [by_id[i] for i in out["event_ids"]]
    written = {e["data"]["key"] for e in mine if e["outcome"] == "ok"}
    assert "p2_shot_size" in written and "p2_time_between_shots" not in written
    assert float(hass.states.get(number(1, "p2_shot_size")).state) == 6.5
