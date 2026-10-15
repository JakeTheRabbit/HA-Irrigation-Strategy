"""The controller app starts with its host by default: addons/f2_control/config.yaml `boot: auto`.

Supervisor uses an app's saved Start on boot when its owner has ever set one, and the app's default
otherwise (supervisor/apps/app.py `App.boot`: `persist.get(ATTR_BOOT, <default>)`; installing saves
no choice, supervisor/apps/data.py). So after an update an app nobody switched starts with the host,
and one set by hand, either way, keeps its setting. With `boot: manual` a box that restarted came
back with its controller stopped and its rooms unwatered until someone noticed.
"""

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "addons" / "f2_control" / "config.yaml"


def test_the_controller_starts_with_its_host_unless_its_owner_said_otherwise():
    assert re.search(r"^boot: auto$", CONFIG.read_text(encoding="utf-8"), re.M)
