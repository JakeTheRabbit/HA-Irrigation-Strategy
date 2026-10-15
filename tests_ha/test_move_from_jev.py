"""MOVING A ROOM FROM THE JEV EDITION (docs/MOVING_FROM_JEV.md), in a real Home Assistant.

The controller app from this repository is a different Supervisor app from the Jev edition's, with an
empty data folder: a room moves once, by the copy command the doc prints. These tests run that command
exactly as the doc prints it on a Jev 3.11.1 app's data folder, then start the real controller on the
copy with the old app's options, the way the doc's steps 3 to 7 do.

The old data folder is what Jev 3.11.1 left: its state.json (state_3_11_1_learn_jev.json) and
jev_usage.json (jev_usage_3_11_1.json) recorded with entry_3_11_1_pumped_room.json, and data_3_11_1_files/: the ledger,
journal and setpoint memory its brain wrote and the dosing record its dosing runner wrote, recorded by
running 3.11.1's own controller, brain and dosing runner (12c6d1a) on its own test kit with every brain
answer stubbed and no network, not written by hand.
"""

import functools
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from conftest import fixture
from test_upgrade_in_place import JEV_3_11_1, KILL, _upgrade

DOC = Path(__file__).resolve().parents[1] / "docs" / "MOVING_FROM_JEV.md"
APP_CODE = Path(__file__).resolve().parents[1] / "addons" / "f2_control" / "f2_control"
RECORDED = Path(__file__).parent / "fixtures" / "data_3_11_1_files"
OLD, NEW = "e031e6d4_f2_control", "6db5faba_f2_control"
JEV_FILES = ("jev_usage.json", "jev_ledger.jsonl", "jev_journal.jsonl", "jev_setpoints.json")
EVERYTHING = ("state.json", "dosing_state.json", *JEV_FILES)
# The files Jev 3.11.1 writes into its data folder, as the doc's copy list names them. Changing that list is a
# decision: the doc, this pin and the old-install proof move together.
COPIED_SHA256 = "b9619c1ff9a1566a19df45c739ac8306fffede4ca6b3b6ad1ccc5db72f4413d3"


def _doc():
    return DOC.read_text(encoding="utf-8")


def _copied():
    """The file names the doc's copy command carries across, in its order."""
    (names,) = re.findall(r"for f in ([^;]+); do", _doc())
    return names.split()


def _old_app(root, names, folder="apps"):
    """A Jev 3.11.1 app's data folder holding `names` of its files (and the Supervisor's own options.json),
    and the new app's data folder as installing the app leaves it: empty."""
    recorded = {
        "state.json": json.dumps(fixture("state_3_11_1_learn_jev.json")["state"]).encode(),
        "jev_usage.json": json.dumps(fixture("jev_usage_3_11_1.json")["usage"]).encode(),
        "options.json": json.dumps(fixture("options_3_11_1_jev_cf.json")["options"]).encode(),
        **{path.name: path.read_bytes() for path in RECORDED.iterdir()},
    }
    data = root / folder / "data"
    old, new = data / OLD, data / NEW
    old.mkdir(parents=True)
    new.mkdir()
    for name in (*names, "options.json"):
        (old / name).write_bytes(recorded[name])
    return old, new


def _move(root, new=NEW):
    """The doc's copy command, as printed, with the host's Supervisor data folder ($SUP) at `root`."""
    (script,) = re.findall(r"-v \"\$SUP\":/s alpine sh -c '(.*?)'\n *```", _doc(), re.S)
    return subprocess.run(
        ["sh", "-c", script.replace("/s/", f"{root}/")],
        env={**os.environ, "NEW": new},
        capture_output=True,
        text=True,
        check=False,
    )


def _start(controller_for, monkeypatch, new, options):
    """The real controller started on the new app's data folder with the old app's options (doc step 3), on the
    day the usage file was written. The brain's routes are stubbed: `built` records every route list it was given."""
    import jev_bridge
    import jev_kit
    from jev.client import Asker

    noon = datetime.fromisoformat(fixture("jev_usage_3_11_1.json")["usage"]["day"])
    noon = noon.replace(hour=12).timestamp()
    built, stub = [], jev_kit.FakeTransport({})
    monkeypatch.setattr(jev_bridge, "Routes", lambda found, **kw: built.append(found) or stub)
    monkeypatch.setattr(
        jev_bridge, "Asker", functools.partial(Asker, threaded=False, clock=lambda: noon)
    )
    monkeypatch.setenv("F2_STATE_PATH", str(new / "state.json"))
    c, fake, _clock = controller_for(fixture(options)["options"])
    return c, fake, built


async def _room(hass, hass_storage):
    """Both layers as the doc leaves them at step 7: the integration from this repository on the 3.11.1 room's
    config entry and dosing store, and the kill switch on."""
    seed = fixture(JEV_3_11_1)
    store = f"crop_steering.dosing.{seed['entry_id']}"
    hass_storage[store] = {
        "version": 1,
        "minor_version": 1,
        "key": store,
        "data": fixture("dosing_3_11_1.json")["dosing"],
    }
    await _upgrade(hass, JEV_3_11_1, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")


# ------------------------------------------------------------------ the whole move
async def test_a_3_11_1_room_moved_by_the_doc_carries_straight_on_with_its_brain_and_dosing(
    hass, hass_storage, controller_for, monkeypatch, tmp_path
):
    await _room(hass, hass_storage)
    old, new = _old_app(tmp_path, EVERYTHING)
    moved = _move(tmp_path)
    assert moved.returncode == 0, moved.stdout + moved.stderr
    assert sorted(p.name for p in new.iterdir()) == sorted(EVERYTHING)  # never the old options.json
    assert all((new / n).read_bytes() == (old / n).read_bytes() for n in EVERYTHING)

    c, fake, built = _start(controller_for, monkeypatch, new, "options_3_11_1_jev_cf.json")
    room, was = c.rooms[0], fixture("state_3_11_1_learn_jev.json")["state"]["default"]

    # No disarm cycle: the setup the old app adopted is the one the new app resumes, kill switch on.
    assert room._setup_pending is None, room._setup_pending
    assert room.setup_revision == 1
    assert "Setup" not in (c._blocked(room, 1) or "")
    for zone in (1, 2):
        st, old_zone = room.state[zone], was[str(zone)]
        assert (st["phase"], st["peak"], st["shots"], st["daily_vol"]) == (
            old_zone["phase"],
            old_zone["peak"],
            old_zone["shots"],
            old_zone["daily_vol"],
        )
        assert st["learn"] == old_zone["learn"]

    # The brain is on, on its own route, with the day's count, its ledger, journal and setpoint memory.
    usage = fixture("jev_usage_3_11_1.json")["usage"]
    assert c.jev is not None and c.jev.routes == ["Cloudflare"]
    assert built[0][0].token == "fixture-token"
    assert c.jev.asker.stats["calls"] == usage["calls"]
    lines = (RECORDED / "jev_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert c.jev.ledger.entries == [json.loads(line) for line in lines]
    assert len(c.jev.journal.entries) == 3
    saved = json.loads((RECORDED / "jev_setpoints.json").read_text(encoding="utf-8"))
    assert c.jev.setpoints.zone("default", 1)["home"] == saved["default:1"]["home"]

    # The dosing record is read back: the request it handled stays handled, its history is kept, nothing holds.
    record = json.loads((RECORDED / "dosing_state.json").read_text(encoding="utf-8"))["rooms"]
    assert c.dosing.recover()
    c.dosing.poll()
    shown = fake.sets["sensor.crop_steering_dosing"][1]
    assert shown["handled"] == record["default"]["handled"]
    assert shown["history"] == record["default"]["history"]
    assert c.dosing.holds(room) is None


@pytest.mark.parametrize("only", JEV_FILES)
async def test_any_one_jev_file_copied_keeps_a_cloudflare_brain_on(
    hass, hass_storage, controller_for, monkeypatch, tmp_path, only
):
    """A Jev app whose brain has not asked yet, or one from 3.0 to 3.3, holds only some of these files."""
    await _room(hass, hass_storage)
    _old, new = _old_app(tmp_path, ("state.json", only))
    assert _move(tmp_path).returncode == 0
    assert sorted(p.name for p in new.iterdir()) == sorted(("state.json", only))
    c, _fake, built = _start(controller_for, monkeypatch, new, "options_3_11_1_jev_cf.json")
    assert c.jev is not None and c.jev.routes == ["Cloudflare"] and built
    assert c.rooms[0]._setup_pending is None


async def test_a_typesafe_key_keeps_the_brain_on_with_no_jev_file(
    hass, hass_storage, controller_for, monkeypatch, tmp_path
):
    await _room(hass, hass_storage)
    _old, new = _old_app(tmp_path, ("state.json",))
    assert _move(tmp_path).returncode == 0
    c, _fake, built = _start(controller_for, monkeypatch, new, "options_3_11_1_jev_typesafe.json")
    assert c.jev is not None and c.jev.routes == ["TypeSafe"]
    assert built[0][0].token == "fixture-typesafe-key"


async def test_cloudflare_with_no_jev_file_runs_on_the_rules_and_asks_nothing(
    hass, hass_storage, controller_for, monkeypatch, tmp_path, capsys
):
    await _room(hass, hass_storage)
    _old, new = _old_app(tmp_path, ("state.json", "dosing_state.json"))
    assert _move(tmp_path).returncode == 0
    c, _fake, built = _start(controller_for, monkeypatch, new, "options_3_11_1_jev_cf.json")
    assert c.jev is None and built == []  # no brain, and no route to ask anything through
    said = capsys.readouterr().out
    assert "jev: off. The Cloudflare credentials start Jev only on an install that has run it before" in said
    assert "fixture-token" not in said
    assert c.rooms[0]._setup_pending is None  # the room carries straight on


# ------------------------------------------------------------------ the doc's command and tables
def test_the_copy_command_finds_the_older_supervisor_folder_too(tmp_path):
    _old, new = _old_app(tmp_path, EVERYTHING, folder="addons")
    assert _move(tmp_path).returncode == 0
    assert sorted(p.name for p in new.iterdir()) == sorted(EVERYTHING)


def test_the_copy_command_refuses_when_the_new_app_is_not_installed(tmp_path):
    old, _new = _old_app(tmp_path, EVERYTHING)
    moved = _move(tmp_path, new="1d36ddd9_f2_control")
    assert moved.returncode == 1 and "install the new app first" in moved.stdout
    assert sorted(p.name for p in old.iterdir()) == sorted((*EVERYTHING, "options.json"))


def test_the_app_ids_are_the_ones_the_supervisor_gives_those_addresses():
    """The Supervisor names a repository's apps by the first 8 hex digits of the sha1 of its lower-cased
    address, then the app's slug (f2_control)."""
    rows = re.findall(r"^\| `(https://github\.com/[^`]+)` \| `([0-9a-f]{8}_f2_control)` \|$", _doc(), re.M)
    assert len(rows) == 3
    for address, app in rows:
        assert app == hashlib.sha1(address.lower().encode()).hexdigest()[:8] + "_f2_control"
    ids = dict(rows)
    assert ids["https://github.com/JakeTheRabbit/HA-Crop-Steering-Jev"] == OLD
    assert ids["https://github.com/JakeTheRabbit/HA-Irrigation-Strategy"] == NEW
    testing = ids["https://github.com/JakeTheRabbit/HA-Irrigation-Strategy#testing"]
    assert f"NEW={NEW}   # {testing} for a staging room on #testing" in _doc()


def test_the_copy_list_names_every_file_the_controller_keeps_in_its_data_folder():
    """Every data file the controller app names in its code is copied, except the Supervisor's options.json
    (step 3 copies the options by hand). A new file in the data folder fails here until the doc says what
    happens to it, so it cannot go missing from a move silently."""
    named = set()
    for path in APP_CODE.rglob("*.py"):
        for name in re.findall(r"[\"'](?:/data/)?([A-Za-z0-9_.-]+\.jsonl?)[\"']", path.read_text(encoding="utf-8")):
            named.add(name)
    assert set(_copied()) == named - {"options.json"}
    assert {p.name for p in RECORDED.iterdir()} | {"state.json", "jev_usage.json"} == set(_copied())
    assert hashlib.sha256("\n".join(sorted(_copied())).encode()).hexdigest() == COPIED_SHA256
