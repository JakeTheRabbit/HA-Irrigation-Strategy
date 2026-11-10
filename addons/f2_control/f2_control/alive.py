"""The alive file: how the standalone container's health check knows the controller's loop is running.

The controller writes the file after each completed pass and through a shot (Controller._alive). The file holds
how long, in seconds, that stays true. healthcheck.py, which Docker runs inside the container every minute,
reads the file's age. Standard library only, and nothing here raises: the health check is a separate, short
process that must not need the controller's own imports, and writing the file is never a reason for the
controller to fail.
"""
import math
import os
import time

PATH = "/tmp/crop-steering-alive"  # one fixed place, the same for the controller and for the check
GOOD_FOR_S = 300.0  # how old the file may be when it does not say (read while it was written)


def path(env):
    """F2_ALIVE_PATH (the tests' seam), else PATH. Not in the data folder: it is not state, and it does not
    outlive the container."""
    return env.get("F2_ALIVE_PATH") or PATH


def mark(env, good_for_s):
    """The loop completed a pass, or a shot is running -> whether the file was written."""
    try:
        with open(path(env), "w", encoding="utf-8") as fh:
            fh.write(f"{float(good_for_s):.0f}\n")
        return True
    except (OSError, TypeError, ValueError):
        return False


def clear(env):
    """A start: what the last run of this container left says nothing about this one."""
    try:
        os.remove(path(env))
    except OSError:
        pass


def health(env, now=None):
    """-> (healthy, words) from the file's age. No file: no pass has completed since the controller started."""
    try:
        where = path(env)
        age = (time.time() if now is None else now) - os.stat(where).st_mtime
        with open(where, encoding="utf-8") as fh:
            said = fh.read().strip()
    except OSError:
        return False, "the controller has not completed a pass since it started"
    try:
        good_for = float(said)
        good_for = good_for if math.isfinite(good_for) and good_for > 0 else GOOD_FOR_S
    except ValueError:
        good_for = GOOD_FOR_S
    if age > good_for:
        return False, (f"the controller last completed a pass {age:.0f} s ago (more than {good_for:.0f} s): it is "
                       "hung or waits on a refused token, or Home Assistant is not answering")
    return True, f"the controller completed a pass {max(age, 0.0):.0f} s ago"
