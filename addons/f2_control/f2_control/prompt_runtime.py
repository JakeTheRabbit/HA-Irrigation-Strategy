"""Synchronize optional room settings and publish exactly the prompt the controller built.

This does not call the AI or clear a remote cache. Unchanged payloads are not resent.
"""

from brain.prompt_context import export


def sync(c, room, ha_get, ha_call):
    brain = getattr(c, "jev", None)
    prompt = getattr(brain, "prompt", None)
    if prompt is None:
        return
    state, attrs = ha_get(f"sensor.crop_steering_{room.prefix}brain_prompt_config")[:2]
    if state in (None, "unknown", "unavailable"):
        return  # controller updated first: exact older prompt and no missing-setting alert
    try:
        revision = int(state)
    except (TypeError, ValueError):
        return
    config = attrs.get("config")
    if not isinstance(config, dict):
        return
    prompt.contexts[room.slug] = config
    prompt.use(getattr(r, "substrate", "generic") for r in getattr(c, "rooms", [room]))
    rebuild = attrs.get("rebuild", 0)
    if getattr(room, "_prompt_rebuild", rebuild) != rebuild:
        from brain.prompt import block_a

        prompt.a = block_a(prompt.pack)
        prompt.substrates = None
        prompt.use(getattr(r, "substrate", "generic") for r in getattr(c, "rooms", [room]))
    room._prompt_rebuild = rebuild
    payload = {"blocks": export(prompt, config), "stage_arc": prompt.arc,
               "substrates": list(prompt.substrates), "rebuild": rebuild,
               "cache_help": "Breakpoints cache the cumulative prefix; later blocks can cache earlier blocks."}
    signature = (revision, rebuild, tuple((b["id"], b["hash"]) for b in payload["blocks"]),
                 str(config.get("cache")))
    if getattr(room, "_published_prompt", None) == signature:
        return
    if ha_call("crop_steering", "brain_prompt_publish", room_id="room:" + room.prefix,
               expected_revision=revision, live=payload):
        room._published_prompt = signature
