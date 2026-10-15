"""The controller's fallback for P2 Time Between Shots is the number's own default.

A controller updated ahead of its integration has no such number and spaces top-ups by its built-in
value instead. Both come from the one defaults table and are 0 (off); if either moves alone, a
controller-only update and a full update would water the same room differently.
"""

from .test_defaults_table import table


def test_the_controller_falls_back_to_the_numbers_default_of_off():
    assert table().DEFAULTS["p2_time_between_shots"] == (0.0, 0.0)
