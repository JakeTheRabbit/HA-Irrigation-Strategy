"""The standalone container's health check (healthcheck.py, alive.py, Controller._alive).

The controller writes an alive file after each completed pass and through a shot. The file says how long it
stays good for: three passes and two minutes. Docker runs healthcheck.py inside the container; it exits 0 while
the file is fresh and 1 when it is old or missing, and Docker shows the container as healthy or unhealthy.
"""
import os

import pytest

import alive
import controller
import healthcheck
from test_controller import _build, _desc


def _env(tmp_path):
    return {"F2_ALIVE_PATH": str(tmp_path / "alive")}


def test_no_file_is_unhealthy_a_fresh_one_healthy_and_an_old_one_unhealthy(tmp_path, capsys):
    env = _env(tmp_path)
    assert alive.health(env) == (False, "the controller has not completed a pass since it started")
    assert healthcheck.main(env) == 1
    alive.mark(env, 300)
    at = os.stat(env["F2_ALIVE_PATH"]).st_mtime
    assert alive.health(env, now=at + 299) == (True, "the controller completed a pass 299 s ago")
    healthy, words = alive.health(env, now=at + 301)
    assert healthy is False and "301 s ago (more than 300 s)" in words
    assert "hung or waits on a refused token, or Home Assistant is not answering" in words  # not "stopped"
    assert healthcheck.main(env) == 0
    assert "completed a pass" in capsys.readouterr().out


def test_the_file_says_how_long_it_is_good_for_and_one_that_does_not_gets_five_minutes(tmp_path):
    env = _env(tmp_path)
    alive.mark(env, 1020)  # a controller told to pass every 300 s
    at = os.stat(env["F2_ALIVE_PATH"]).st_mtime
    assert alive.health(env, now=at + 1000)[0] is True
    assert alive.health(env, now=at + 1021)[0] is False
    for junk in ("", "soon", "nan", "-5", "0"):  # read while it was written, or damaged
        with open(env["F2_ALIVE_PATH"], "w", encoding="utf-8") as fh:
            fh.write(junk)
        at = os.stat(env["F2_ALIVE_PATH"]).st_mtime
        assert alive.health(env, now=at + 299)[0] is True, junk
        assert alive.health(env, now=at + 301)[0] is False, junk


def test_a_clock_that_went_back_is_not_an_old_file(tmp_path):
    env = _env(tmp_path)
    alive.mark(env, 300)
    at = os.stat(env["F2_ALIVE_PATH"]).st_mtime
    assert alive.health(env, now=at - 3600) == (True, "the controller completed a pass 0 s ago")


def test_the_path_is_one_fixed_place_for_the_controller_and_the_check_never_the_data_folder():
    assert alive.path({"F2_DATA_DIR": "/data", "TMPDIR": "/somewhere/else"}) == "/tmp/crop-steering-alive"


def test_a_folder_that_is_not_there_never_raises_in_the_check_or_the_controller(tmp_path):
    env = {"F2_ALIVE_PATH": str(tmp_path / "no-such-folder" / "alive")}
    assert alive.mark(env, 300) is False
    assert alive.health(env)[0] is False
    alive.clear(env)  # nothing to remove: no raise


def test_a_start_forgets_what_the_last_run_of_the_container_left(tmp_path):
    """`docker restart` keeps the container's files: a controller that then waits on a refused token must not
    show healthy on the last run's file."""
    env = _env(tmp_path)
    alive.mark(env, 300)
    assert alive.health(env)[0] is True
    alive.clear(env)
    assert alive.health(env) == (False, "the controller has not completed a pass since it started")
    source = (controller.__file__)
    with open(source, encoding="utf-8") as fh:
        main = fh.read().split('if __name__ == "__main__":')[1]
    assert main.index("alive.clear(os.environ)") < main.index("runtime_env.preflight(")  # before it can park


@pytest.fixture
def running(monkeypatch):
    c, fake = _build({"num_zones": 1}, states={"sensor.crop_steering_engine_config": ("ok", _desc())})

    class Clock:
        seconds = 1000.0

    monkeypatch.setattr(controller.time, "monotonic", lambda: Clock.seconds)
    return c, Clock


def test_the_controller_says_alive_for_three_passes_and_two_minutes_at_most_every_ten_seconds(running):
    c, clock = running
    path = os.environ["F2_ALIVE_PATH"]
    assert not os.path.exists(path)
    c._alive()
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == f"{3 * c.loop_seconds + 120:.0f}\n" == "300\n"
    os.remove(path)
    clock.seconds += 9
    c._alive()
    assert not os.path.exists(path)  # not written again within 10 s
    clock.seconds += 2
    c._alive()
    assert os.path.exists(path)


def test_a_shot_in_progress_keeps_it_alive(running):
    c, clock = running
    c._keep_alive(0.0)  # a shot's wait calls this every round, even with no time left for its writes
    assert alive.health(os.environ)[0] is True


def test_a_path_that_cannot_be_written_never_stops_the_loop_and_is_said_once(running, monkeypatch, tmp_path, capsys):
    c, clock = running
    monkeypatch.setenv("F2_ALIVE_PATH", str(tmp_path / "no-such-folder" / "alive"))
    c._alive()  # no raise
    clock.seconds += 60
    c._alive()
    assert alive.health(os.environ)[0] is False
    assert capsys.readouterr().out.count("cannot be written") == 1


def test_a_clock_that_went_back_never_mutes_it(running):
    c, clock = running
    c._alive()
    os.remove(os.environ["F2_ALIVE_PATH"])
    clock.seconds -= 5000
    c._alive()
    assert os.path.exists(os.environ["F2_ALIVE_PATH"])


def test_a_controller_that_waits_on_a_refused_token_writes_nothing(running, monkeypatch):
    """Parked (runtime_env / _park_refused): the loop makes no pass, so the container goes unhealthy."""
    c, _clock = running

    class Done(Exception):
        pass

    passes = []

    def parked():
        passes.append(os.path.exists(os.environ["F2_ALIVE_PATH"]))
        if len(passes) >= 3:
            raise Done

    monkeypatch.setattr(controller._GATE, "state", "all")
    monkeypatch.setattr(c, "_park_refused", parked)
    monkeypatch.setattr(c, "loop_once", lambda now: (_ for _ in ()).throw(RuntimeError("refused")))
    monkeypatch.setattr(c, "_log_timezone", lambda: True)
    monkeypatch.setattr(c, "_start_dosing", lambda: None)
    with pytest.raises(Done):
        c.run()
    assert passes == [False, False, False] and alive.health(os.environ)[0] is False


def test_the_main_loop_says_alive_only_after_a_pass_that_completed(running, monkeypatch):
    """A pass that raises is logged and tried again (run), and does not count: a controller whose every pass
    fails goes unhealthy."""
    c, clock = running
    passes = []

    class Done(Exception):
        pass

    def sleep_for(seconds):
        clock.seconds += seconds
        if len(passes) >= 2:
            raise Done

    def loop_once(now):
        passes.append(os.path.exists(os.environ["F2_ALIVE_PATH"]))
        if len(passes) == 1:
            raise RuntimeError("the first pass fails")

    monkeypatch.setattr(c, "loop_once", loop_once)
    monkeypatch.setattr(c, "_sleep_for", sleep_for)
    monkeypatch.setattr(c, "_log_timezone", lambda: True)
    monkeypatch.setattr(c, "_start_dosing", lambda: None)
    with pytest.raises(Done):
        c.run()
    assert passes == [False, False]  # nothing was written before or after the failed pass
    assert alive.health(os.environ)[0] is True  # the second pass completed
