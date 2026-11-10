"""The standalone container's health check (docker-compose.yml, `healthcheck:`).

Docker runs this inside the container every minute. It exits 0 while the controller's loop is running (it
completed a pass, or was in a shot, recently: alive.health) and 1 when it is not, with one line saying which.
Docker then shows the container as healthy or unhealthy (`docker ps`). It asks Home Assistant nothing and
switches nothing. The Home Assistant app does not use it: the Supervisor watches the app itself.
"""
import os
import sys

import alive


def main(env=None):
    healthy, words = alive.health(os.environ if env is None else env)
    print(words)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
