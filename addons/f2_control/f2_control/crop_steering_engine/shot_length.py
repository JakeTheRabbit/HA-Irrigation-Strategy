"""How long a shot runs: the one rule, for the controller and the integration.

The controller times every shot with it, and the integration's shot-duration sensors show what it
gives, so the dashboard never shows a length the controller would not run.

Pure, with no imports, so every layer can carry it. This file is the source,
crop-steering-engine/src/crop_steering_engine/shot_length.py. Two byte-for-byte copies ship: the
controller's vendored engine and the integration's
custom_components/crop_steering/generated/shot_length.py (Home Assistant installs the integration on
its own, so it cannot import the engine). Edit the source, then copy it over both;
tests/test_generated_copies.py fails while any copy differs. The integration's copy is linted with
black, so keep this file black-clean.
"""

# The shortest shot that runs, in seconds, and the shortest maximum shot length a room may set.
MIN_SHOT_S = 5
# A room with neither maximum shot length entity (an install from before them) runs within this.
DEFAULT_MAX_SHOT_S = 900.0


def raw_seconds(size_pct, substrate_l, flow_lps):
    """Seconds a shot of `size_pct` % of `substrate_l` litres takes at `flow_lps` litres a second.

    Zone totals (or one plant's substrate and one plant's flow: plant count cancels). The caller
    checks first that the substrate and the flow are finite and above 0.
    """
    return size_pct / 100.0 * substrate_l / flow_lps


def valid_cap(value):
    """The room's maximum shot length as seconds, or None when it is not one (not a finite number of
    MIN_SHOT_S or more). With None the controller starts no shot (CS-203) and never puts a default
    in its place."""
    try:
        cap = float(value)
    except (TypeError, ValueError):
        return None
    if cap != cap or cap in (float("inf"), float("-inf")) or cap < MIN_SHOT_S:
        return None
    return cap


def shot_seconds(raw, cap):
    """What a shot of `raw` seconds runs for: whole seconds, at least MIN_SHOT_S, and never longer
    than the room's maximum shot length `cap` (a valid_cap value)."""
    return max(MIN_SHOT_S, min(int(cap), int(raw)))
