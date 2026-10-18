"""Bind every source paragraph to its own picture and measured voice take."""


def _index(items, name):
    result = {}
    for item in items:
        if item["id"] in result:
            raise ValueError(f'duplicate {name}: {item["id"]}')
        result[item["id"]] = item
    return result


def plan(lessons, cues, records):
    expected = []
    for lesson in lessons:
        for slide in lesson["slides"]:
            for index, text in enumerate(slide["narration"].split("\n\n")):
                expected.append({"id": f'{slide["id"]}-p{index+1:02}',
                                 "lesson": lesson["id"], "scene": slide["id"],
                                 "paragraph": index, "text": text})
    pictures = _index(cues, "picture")
    voices = _index(records, "voice")
    ids = {x["id"] for x in expected}
    if set(pictures) != ids or set(voices) != ids:
        raise ValueError("paragraph coverage differs between source, pictures and voices")
    result, offsets = [], {}
    for source in expected:
        key = source["id"]
        for item in (pictures[key], voices[key]):
            if any(item.get(k) != v for k, v in source.items()):
                raise ValueError(f'source mismatch: {key}')
        record = voices[key]
        frames = record["frames"]
        if (not isinstance(frames, int) or frames <= 0
                or abs(record["duration"] - frames/24) > .001):
            raise ValueError(f'invalid frame duration: {key}')
        start = offsets.get(source["lesson"], 0)
        end = start + frames
        result.append({**pictures[key], "start_frame": start, "end_frame": end,
                       "frames": frames, "start": start/24, "end": end/24,
                       "duration": frames/24})
        offsets[source["lesson"]] = end
    return result
