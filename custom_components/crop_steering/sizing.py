"""Pure compatibility rules for explicitly configured zone hydraulics."""

SIZING_KEYS = {
    "substrate_volume",
    "plant_count",
    "drippers_per_plant",
    "dripper_flow_rate",
}


def configured_sizing(entry, zone):
    config = {
        **(getattr(entry, "data", None) or {}),
        **(getattr(entry, "options", None) or {}),
    }
    zones = config.get("zones") or {}
    values = zones.get(str(zone), zones.get(zone, {})) or {}
    return {key: values[key] for key in SIZING_KEYS if key in values}, config.get(
        "setup_revision", 0
    )


def prefer_setup_value(last_attributes, revision, configured_value):
    """A new explicit value wins once; unrelated setup edits preserve HA tuning."""
    return (
        type(revision) is int
        and revision > 0
        and last_attributes.get("setup_revision", 0) != revision
        and last_attributes.get("setup_value") != configured_value
    )
