"""Every entity domain the Home Assistant under test has is one the Claude brain's scrub knows (jev.scrub.HA_DOMAINS),
so a platform added to Home Assistant fails here instead of an entity id of that domain reaching the model."""
from homeassistant.const import Platform
from jev.scrub import HA_DOMAINS


def test_the_scrub_knows_every_platform_of_this_home_assistant():
    assert sorted({p.value for p in Platform} - set(HA_DOMAINS)) == []
