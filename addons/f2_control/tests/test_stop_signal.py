"""Stopping the app must hand SIGTERM to the controller straight away.

The image's init (s6-overlay, PID 1 because config.yaml sets `init: false`) otherwise signals the
controller only after its own services are down, and kills it 3 s later: a safe-off that waits on a
slow Home Assistant was cut off before it switched the shot's valve off. With
S6_CMD_RECEIVE_SIGNALS the controller gets the signal at once and the container ends when it exits,
inside the `timeout:` the Supervisor waits.
"""
import pathlib
import re

ADDON = pathlib.Path(__file__).parents[1]


def test_the_image_hands_the_stop_signal_to_the_controller():
    dockerfile = (ADDON / "Dockerfile").read_text()
    assert re.search(r"^ENV S6_CMD_RECEIVE_SIGNALS=1$", dockerfile, re.M)
    assert dockerfile.index("S6_CMD_RECEIVE_SIGNALS") < dockerfile.index("CMD [")


def test_the_init_that_reads_it_is_the_images_own():
    assert re.search(r"^init: false$", (ADDON / "config.yaml").read_text(), re.M)
