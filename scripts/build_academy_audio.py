"""Reproducible local academy narration. Optional kokoro-onnx + soundfile required.

Models and masters stay outside the repository. Resume skips only matching source hashes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time


def pronunciation(text):
    replacements = {
        r"\bVWC\b": "V W C",
        r"\bEC\b": "E C",
        r"\bpH\b": "P H",
        r"\bHAOS\b": "Home Assistant operating system",
        r"\bUEFI\b": "U E F I",
        r"\bMQTT\b": "M Q T T",
        r"\bUSB\b": "U S B",
        r"\bSSD\b": "S S D",
        r"\bP0\b": "P zero",
        r"\bP1\b": "P one",
        r"\bP2\b": "P two",
        r"\bP3\b": "P three",
        r"\bx86(?:[-–]64)?\b": "X eighty six sixty four",
        r"\bL/h\b": "litres per hour",
        r"\bmS/cm\b": "millisiemens per centimetre",
        r"\bpp\b": "percentage points",
    }
    for pattern, value in replacements.items():
        text = re.sub(pattern, value, text)
    return (
        text.replace("→", ", then ")
        .replace("×", " times ")
        .replace("÷", " divided by ")
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--production", type=Path, required=True)
    ap.add_argument("--modules", type=Path, default=Path("www/learn/course/modules"))
    ap.add_argument("--speed", type=float, default=0.82)
    args = ap.parse_args()
    from kokoro_onnx import Kokoro
    import soundfile as sf

    production = args.production.resolve()
    output = production / "narration"
    output.mkdir(exist_ok=True, parents=True)
    k = Kokoro(
        str(production / "models/kokoro-v1.0.onnx"),
        str(production / "models/voices-v1.0.bin"),
    )
    lessons = [
        lesson
        for p in sorted(args.modules.glob("*.json"))
        if p.stem != "pilots"
        for lesson in json.loads(p.read_text(encoding="utf-8-sig"))
    ]
    started = time.monotonic()
    records = []
    for lesson in lessons:
        folder = output / lesson["id"]
        folder.mkdir(exist_ok=True)
        for slide in lesson["slides"]:
            source = slide["narration"]
            spoken = pronunciation(source)
            digest = hashlib.sha256(
                (spoken + f"|af_heart|{args.speed}").encode()
            ).hexdigest()
            wav = folder / f'{slide["id"]}.wav'
            info = wav.with_suffix(".json")
            if (
                info.exists()
                and wav.exists()
                and json.loads(info.read_text())["source_sha256"] == digest
            ):
                record = json.loads(info.read_text())
            else:
                samples, sr = k.create(
                    spoken,
                    voice="af_heart",
                    speed=args.speed,
                    lang="en-us",
                    sentence_pause=0.35,
                    clause_pause=0.16,
                )
                temporary = wav.with_suffix(".part.wav")
                sf.write(temporary, samples, sr)
                os.replace(temporary, wav)
                record = {
                    "lesson": lesson["id"],
                    "slide": slide["id"],
                    "source": source,
                    "spoken": spoken,
                    "source_sha256": digest,
                    "voice": "af_heart",
                    "speed": args.speed,
                    "engine": "Kokoro ONNX 0.6.1 / model v1.0",
                    "sample_rate": sr,
                    "duration": len(samples) / sr,
                    "words": len(source.split()),
                }
                info.write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            records.append(record)
            print(
                f'{lesson["id"]}/{slide["id"]}: {record["duration"]:.1f}s ({len(records)})',
                flush=True,
            )
    (production / "narration-manifest.json").write_text(
        json.dumps(
            {"records": records, "elapsed": time.monotonic() - started}, indent=2
        ),
        encoding="utf-8",
    )
    print(
        f'COMPLETE {len(records)} slides; {sum(r["duration"] for r in records)/60:.1f} minutes',
        flush=True,
    )


if __name__ == "__main__":
    main()
