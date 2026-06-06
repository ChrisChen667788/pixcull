#!/usr/bin/env python3
"""v2.2-P0-1 — convert Google's YAMNet (Apache-2.0) to ONNX for PixCull.

YAMNet is an AudioSet audio-event classifier: waveform (16 kHz mono) →
521-class scores, 0.96 s window / 0.48 s hop.  PixCull's ``OnnxTagger``
consumes exactly this — it feeds the raw waveform and maps the AudioSet
classes (Laughter / Applause / Music / …) to our kinds via the sidecar
``<model>.labels.json``.

Run in a **throwaway venv** (it pulls the TensorFlow stack — keep it out
of the project venv, which only needs ``onnxruntime`` to *run* the model)::

    python3 -m venv /tmp/tfconv
    /tmp/tfconv/bin/pip install tensorflow tensorflow_hub tf2onnx "setuptools<81"
    /tmp/tfconv/bin/python scripts/convert_yamnet_to_onnx.py \
        --out ~/.pixcull/models/audio_tagger.onnx

Output: ``<out>`` + ``<out>.labels.json`` (the 521 AudioSet display names
in output order).  ``pixcull`` then picks it up automatically
(``scoring/audio_tagger.py`` searches ``~/.pixcull/models/``).

Why freeze first: a plain ``tf2onnx`` ``from_function`` leaves YAMNet's
batch-norm weights as *dangling graph inputs*;
``convert_variables_to_constants_v2`` folds them in so the exported ONNX
has a single ``waveform`` input.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

YAMNET_URL = "https://tfhub.dev/google/yamnet/1"


def convert(out: Path) -> None:
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import tensorflow as tf
    import tensorflow_hub as hub
    import tf2onnx
    from tensorflow.python.framework.convert_to_constants import (
        convert_variables_to_constants_v2,
    )

    ym = hub.load(YAMNET_URL)
    names = [r["display_name"] for r in
             csv.DictReader(open(ym.class_map_path().numpy().decode()))]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(str(out) + ".labels.json").write_text(
        json.dumps(names, ensure_ascii=False), encoding="utf-8")

    spec = [tf.TensorSpec([None], tf.float32, name="waveform")]

    @tf.function(input_signature=spec)
    def f(x):
        scores, _emb, _logmel = ym(x)
        return tf.identity(scores, name="scores")

    frozen = convert_variables_to_constants_v2(f.get_concrete_function())
    tf2onnx.convert.from_graph_def(
        frozen.graph.as_graph_def(),
        input_names=[t.name for t in frozen.inputs],
        output_names=[t.name for t in frozen.outputs],
        opset=13, output_path=str(out))
    print(f"✓ {out} ({out.stat().st_size} bytes) "
          f"+ {out.name}.labels.json ({len(names)} classes)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path,
                    default=Path.home() / ".pixcull" / "models"
                    / "audio_tagger.onnx")
    convert(ap.parse_args().out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
