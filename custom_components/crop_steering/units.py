"""Probe units the integration understands, and how each becomes the unit it steers in.

Pore EC is steered in mS/cm and VWC in percent. A probe in another unit is accepted only when the
conversion is exact. Letting a raw 3200 uS/cm into an EC comparison written for 3.2 mS/cm would read
as a thousandfold overshoot, and the engine enlarges shots when pore EC is over target.

The rules are the one device-unit table (generated/defaults.py, UNITS), which the controller app
reads through too, so the two can never read one probe differently.
"""

from __future__ import annotations

import logging

from .generated.defaults import UNITS, to_canonical

_LOGGER = logging.getLogger(__name__)
# (sensor, unit, how it was taken) already said in the log, so each is said once a run.
_SAID: set = set()


def normalise(unit) -> str:
    return str(unit or "").lower().replace(" ", "")


def accepted(kind: str) -> set[str]:
    return set(UNITS[kind]["convert"]) if kind in UNITS else set()


def refusal(kind: str, unit) -> str | None:
    """Why this unit is not accepted for this kind of probe, when there is a specific reason."""
    return UNITS.get(kind, {}).get("refused", {}).get(normalise(unit))


def to_native(kind: str | None, unit, value: float, source: str | None = None):
    """(the reading in the unit the integration steers in or None, whether it was set aside for its unit).

    A unit the table does not know, or none, is read as the steering unit while the reading is
    plausible for it. Installs older than setup validation have probes with no unit or an odd label,
    and their readings must keep meaning what they meant. A refused unit (ppm), or an unknown unit
    with an implausible reading, is set aside for its unit. A reading with no unit that is out of
    range passes through, so the zone reading excludes it as out of range, exactly as before. The
    first time `source` reports a unit the table does not simply recognise, the log says so once,
    naming the sensor and the unit.
    """
    if kind not in UNITS:
        return value, False
    converted, taken = to_canonical(kind, value, unit)
    if taken == "implausible" and not normalise(unit):
        return value, False
    if source and taken != "recognised" and (source, unit, taken) not in _SAID:
        _SAID.add((source, unit, taken))
        canonical = UNITS[kind]["canonical"]
        if converted is None:
            _LOGGER.warning(
                "%s reports %s in %r, which can't be taken as %s, so the probe is set aside",
                source,
                kind,
                unit or "no unit",
                canonical,
            )
        else:
            _LOGGER.info(
                "%s reports %s in %r, a unit the table does not know, so it is read as %s "
                "while it stays plausible",
                source,
                kind,
                unit or "no unit",
                canonical,
            )
    return converted, converted is None
