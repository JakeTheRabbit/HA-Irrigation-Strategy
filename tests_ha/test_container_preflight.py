"""A standalone container's preflight against Home Assistant's REAL REST API (auth, ban middleware, views).

`GET /api/` answers any signed-in user, which is why the preflight also writes one state, the admin
probe: in Home Assistant only an administrator may write a state, and the controller writes its
heartbeat and status. Here the token of a real ordinary user (the Users group, what a staff phone
signs in as) passes `GET /api/`, is refused the probe with 401, and the real preflight parks before
any controller is built: nothing is switched and nothing more is sent. An administrator's token
passes both and the preflight returns. With an empty TZ both adopt Home Assistant's own time zone
from the real `GET /api/config`. Only the HTTP listener's start is stood in for (conftest.real_api).
"""

import os
import time
from functools import partial

import pytest
import requests
import runtime_env
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.auth.models import Credentials
from homeassistant.const import EVENT_CALL_SERVICE
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser

VALVE = "switch.zone_1_valve"
ZONE = "Pacific/Auckland"


@pytest.fixture(autouse=True)
def _custom_integrations(hass, enable_custom_integrations):
    """Home Assistant's real `http` and `api` serve this module (conftest.real_api)."""
    yield


@pytest.fixture(autouse=True)
def _process_zone():
    """The preflight moves this process onto Home Assistant's time zone; put it back afterwards."""
    saved = os.environ.get("TZ")
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


class Hour(Exception):
    pass


class Clock:
    seconds = 0.0

    def sleep(self, seconds):
        self.seconds += seconds
        if self.seconds > 3600:
            raise Hour

    def monotonic(self):
        return self.seconds


class Recorded:
    """The real `requests`, with every answer noted."""

    def __init__(self):
        self.sent = []

    def get(self, url, **kwargs):
        answer = requests.get(url, **kwargs)
        self.sent.append(("GET", url, answer.status_code))
        return answer

    def post(self, url, **kwargs):
        answer = requests.post(url, **kwargs)
        self.sent.append(("POST", url, answer.status_code))
        return answer


async def _staff_token(hass, local_auth):
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    user = MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)
    credential = Credentials(id="staff-credential", auth_provider_type="homeassistant",
                             auth_provider_id=None, data={"username": "staff"}, is_new=False)
    user.credentials.append(credential)
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID, credential=credential)
    return hass.auth.async_create_access_token(refresh)


async def _preflight(hass, base, token, tmp_path):
    await hass.config.async_set_time_zone(ZONE)
    env = {"F2_RUNTIME": "container", "HA_URL": base, "HA_TOKEN": token, "TZ": "",
           "F2_STATE_PATH": str(tmp_path / "state.json")}
    http, clock = Recorded(), Clock()
    run = partial(runtime_env.preflight, None, env, version="test", http=http, sleep=clock.sleep,
                  clock=clock.monotonic)
    try:
        await hass.async_add_executor_job(run)
    except Hour:
        return "parked", http.sent
    return "returned", http.sent


async def test_a_non_admin_token_parks_before_the_controller_is_built(hass, real_api, local_auth, tmp_path):
    token = await _staff_token(hass, local_auth)
    hass.states.async_set(VALVE, "on")
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, calls.append)

    outcome, sent = await _preflight(hass, real_api, token, tmp_path)

    assert outcome == "parked"  # a simulated hour, never an exit
    assert sent == [
        ("GET", real_api + "/", 200),
        ("GET", real_api + "/config", 200),
        ("POST", f"{real_api}/states/{runtime_env.RUNTIME_ENTITY}", 401),
    ]
    assert calls == []
    assert hass.states.get(VALVE).state == "on"
    assert hass.states.get(runtime_env.RUNTIME_ENTITY) is None
    assert os.environ["TZ"] == ZONE


async def test_an_administrators_token_passes_the_admin_probe(hass, real_api, hass_access_token, tmp_path):
    outcome, sent = await _preflight(hass, real_api, hass_access_token, tmp_path)

    assert outcome == "returned"
    assert [status for _method, _url, status in sent] == [200, 200, 201]
    assert hass.states.get(runtime_env.RUNTIME_ENTITY).state == "container"
