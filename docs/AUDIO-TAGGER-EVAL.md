# Audio tagger eval — DSP baseline vs learned (v2.2-P0-1)

- Eval set: `/tmp/pixcull_audio_eval` · 64 clips (ESC-50 subset, CC BY-NC 3.0 — eval only, not redistributed)
- Learned model: `~/.pixcull/models/audio_tagger.onnx` (YAMNet → ONNX, Apache-2.0)

| kind | DSP P | DSP R | DSP F1 | learned P | learned R | learned F1 | ΔF1 |
|---|---|---|---|---|---|---|---|
| applause | 0.00 | 0.00 | 0.00 | 1.00 | 0.75 | 0.86 | +0.86 |
| laughter | 0.12 | 0.20 | 0.15 | 1.00 | 0.25 | 0.40 | +0.25 |

- **macro-F1:** DSP `0.075` · learned `0.629` · Δ `+0.553`
- **verdict:** ✅ learned ≥ DSP — promote to default

> Regenerate with `scripts/eval_audio_tagger.py`.

## Reading the numbers

The DSP heuristic (`scoring/audio_events.py`) is **weak on real clips** —
applause F1 = 0.00 (it fires no applause on 20 real clapping clips),
laughter 0.15, macro-F1 0.075. The learned YAMNet tagger lifts macro-F1
to **0.629** (applause 0.86, laughter 0.40) — **+0.55, ~8× the DSP** — so
it is promoted to default. The DSP path stays as the always-available
offline fallback (no model / no `onnxruntime` ⇒ byte-identical to before).

`laughter` recall (0.25) trails precision (1.00): YAMNet at thresh 0.5 is
conservative on laughter; lowering `OnnxTagger.thresh` trades precision
for recall. The default 0.5 keeps zero false positives — good for the
moment-boost use.

## How to reproduce

```bash
# model — throwaway venv (pulls TensorFlow; see the script header):
python3 -m venv /tmp/tfconv
/tmp/tfconv/bin/pip install tensorflow tensorflow_hub tf2onnx "setuptools<81"
/tmp/tfconv/bin/python scripts/convert_yamnet_to_onnx.py \
    --out ~/.pixcull/models/audio_tagger.onnx
# eval — project venv (onnxruntime only):
python scripts/eval_audio_tagger.py --eval-dir <clips-dir> \
    --model ~/.pixcull/models/audio_tagger.onnx --out docs/AUDIO-TAGGER-EVAL.md
```

A model at `~/.pixcull/models/audio_tagger.onnx` (+ `.labels.json`) is
picked up automatically by `scoring/audio_tagger.py::get_tagger` (learned
becomes the default tagger) and by `pixcull models path audio-tagger`
(v2.2-P1-2).

## Model

Google **YAMNet** (AudioSet, Apache-2.0) → ONNX via
`scripts/convert_yamnet_to_onnx.py` (freeze variables → `tf2onnx`; single
`waveform` input → `[n_frames, 521]`). `OnnxTagger` feeds the 16 kHz
waveform and maps the 521 AudioSet classes → laughter / applause / music
via the sidecar `labels.json`. ~16 MB; **not committed** (binary) —
reproduce with the script or `pixcull models pull audio-tagger`.

## Eval set & attribution

ESC-50 (Piczak, *ACM MM* 2015), CC BY-NC 3.0 — a subset of the
`laughing` / `clapping` classes (+ negatives) is fetched **locally** for
evaluation only and is **not** redistributed (repo-hygiene: eval data is
local-only). ESC-50 has no generic *music* class, so `music` is not
covered by this set.
