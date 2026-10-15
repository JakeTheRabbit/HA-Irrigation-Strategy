"""The controller app starts with its host by default: addons/f2_control/config.yaml `boot: auto`.

Supervisor uses an app's saved Start on boot when its owner has ever set one, and the app's default
otherwise (supervisor/apps/app.py `App.boot`: `persist.get(ATTR_BOOT, <default>)`; installing saves
no choice, supervisor/apps/data.py). So after an update an app nobody switched starts with the host,
and one set by hand, either way, keeps its setting. With `boot: manual` a box that restarted came
back with its controller stopped and its rooms unwatered until someone noticed.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "addons" / "f2_control" / "config.yaml"


def test_the_controller_starts_with_its_host_unless_its_owner_said_otherwise():
    assert re.search(r"^boot: auto$", CONFIG.read_text(encoding="utf-8"), re.M)


def test_the_container_starts_again_with_docker_and_install_says_so():
    """A container has no `boot:`; the compose file's restart policy is its Start on boot."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"^    restart: unless-stopped$", compose, re.M)
    install = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    assert "`restart: unless-stopped`" in install
