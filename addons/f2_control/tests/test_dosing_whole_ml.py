"""A batch doses whole mL (docs/DOSING.md, Configuration): a recipe amount read from its mL entity is
rounded half up before the pump is sent it, and one that rounds to 0 skips the pump, as the
integration rounds a fixed amount when it is saved. Driven as test_dosing_runner.py drives it."""
from __future__ import annotations

import pytest

from test_dosing_runner import _full_batch, make_rig


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return make_rig(tmp_path, monkeypatch)


def _volumes(r, entity):
    return [data["value"] for domain, service, data in r.fake.calls
            if service == "set_value" and data.get("entity_id") == entity]


@pytest.mark.parametrize("reading, sent", [("150.5", 151), ("150.49", 150), ("12.5", 13)])
def test_a_recipe_amount_read_from_its_entity_is_dosed_in_whole_ml(rig, reading, sent):
    r = rig()
    _full_batch(r)
    r.set("number.recipe_bloom", reading)
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert _volumes(r, "input_number.bloom_volume")[0] == sent
    assert r.status()[1]["history"][0]["doses"]["bloom"] == sent


def test_an_amount_under_half_a_ml_skips_the_pump(rig):
    r = rig()
    _full_batch(r)
    r.set("number.recipe_bloom", "0.4")
    r.ask("batch")
    r.poll()
    assert r.status()[1]["handled_result"] == "finished"
    assert ("turn_on", "script.bloom_start") not in r.actions()
