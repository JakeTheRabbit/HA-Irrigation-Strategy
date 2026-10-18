"""Create paragraph-sized, frame-aligned pilot narration using local Kokoro.

Optional dependencies: kokoro-onnx, onnxruntime, numpy, soundfile. Models and
generated masters stay outside Git. Existing matching takes are resumable.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from build_academy_audio import pronunciation


def paragraphs(lessons):
    for lesson in lessons:
        for slide in lesson["slides"]:
            for index, text in enumerate(slide["narration"].split("\n\n")):
                yield {
                    "id": f'{slide["id"]}-p{index + 1:02}',
                    "lesson": lesson["id"],
                    "scene": slide["id"],
                    "paragraph": index,
                    "text": text,
                }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--source", type=Path, default=Path("www/learn/course/modules/pilots.json"))
    ap.add_argument("--speed", type=float, default=.82)
    args = ap.parse_args()
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    from kokoro_onnx import Kokoro

    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(args.models / "kokoro-v1.0.onnx"), options,
                                   providers=["CPUExecutionProvider"])
    voice = Kokoro.from_session(session, str(args.models / "voices-v1.0.bin"))
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for card in paragraphs(json.loads(args.source.read_text(encoding="utf-8-sig"))):
        spoken = pronunciation(card["text"])
        signature = hashlib.sha256((spoken + f"|af_heart|{args.speed}|frame24|tail.3").encode()).hexdigest()
        wav = args.output / (card["id"] + ".wav")
        receipt = wav.with_suffix(".json")
        if receipt.exists() and wav.exists() and json.loads(receipt.read_text())["generation_signature"] == signature:
            record = json.loads(receipt.read_text())
        else:
            samples, sr = voice.create(spoken, voice="af_heart", speed=args.speed,
                                       lang="en-us", sentence_pause=.35, clause_pause=.16)
            assert sr == 24000, "Frame padding assumes 24000 Hz and 24 fps"
            speech_samples = len(samples)
            frames = math.ceil((speech_samples + round(.3 * sr)) / (sr // 24))
            samples = np.pad(samples, (0, frames * (sr // 24) - speech_samples))
            sf.write(str(wav), samples, sr, subtype="PCM_16")
            record = {**card, "spoken": spoken,
                      "source_sha256": hashlib.sha256(card["text"].encode()).hexdigest(),
                      "generation_signature": signature, "voice": "af_heart",
                      "speed": args.speed, "sample_rate": sr, "frames": frames,
                      "duration": frames / 24, "speech_duration": speech_samples / sr,
                      "engine": "Kokoro ONNX 0.6.1 / model v1.0"}
            receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)
        print(f'{card["id"]}: {record["duration"]:.2f}s [{len(records)}]', flush=True)
    (args.output / "manifest.json").write_text(json.dumps({"records": records}, indent=2), encoding="utf-8")
    print(f'COMPLETE {len(records)} cues, {sum(r["duration"] for r in records)/60:.2f} minutes', flush=True)


if __name__ == "__main__":
    main()
