#!/usr/bin/env python3
"""Build `samples/input` from full-resolution originals.

v3.64 — this existed only as a sequence of ad-hoc commands, and doing it
by hand went wrong three times:

* the first cut stripped EXIF wholesale, which broke burst folding —
  the feature the demo exists to show groups on ``DateTimeOriginal``;
* the second dropped GPS and the body serial but left
  ``LensSerialNumber``, which identifies the owner's lens just as well;
* the third picked the thirty-two highest-scoring frames, which left
  the set with one near-duplicate pair in it and every frame a `keep`.
  A culling demo where nothing is culled and nothing folds shows the
  visitor nothing.

So the curation is a file now, and the reasons sit next to the names.

The screening rule this encodes is the one that matters and the one an
automatic check cannot make: **the product's own face detector is a
first pass, never the answer.** It reported this whole pool clean, and
looking at the frames found a portrait, a second portrait, and a girl
running across a field whose face is perfectly legible at full size.
Every name below was looked at by eye at 1600 px, and anywhere a human
figure appeared, again at native resolution.

Rebuilding the run in `samples/output` afterwards is a second step, and
it has one non-obvious requirement:

    pixcull run samples/input --output /tmp/samrun --vlm-mode off
    cp /tmp/samrun/{scores.csv,rubric.jsonl,embeddings.npz} samples/output/

**`--vlm-mode off` is not optional.** Without it, `pixcull run` sends
every frame to the cloud judge whenever a MiniMax key is on the machine
and consent was recorded once — which it was, in August. Clearing
`MINIMAX_API_KEY` does not prevent it: on macOS the key is read from the
keychain as well, because that is where the app stores it so a GUI launch
with no shell environment can still find it. Six of these photographs
went to MiniMax during v3.64 for exactly that reason.
`tests/test_sample_run_never_went_to_the_cloud.py` checks the artifact
rather than trusting this paragraph.

Usage:  python scripts/brand/prepare_samples.py <originals-dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "samples" / "input"

LONG_EDGE = 1600
QUALITY = 82

#: EXIF that identifies the photographer's hardware or where they stood.
#: 0x8825 GPSInfo · 0xA430 CameraOwnerName · 0xA431 BodySerialNumber
#: 0xA435 LensSerialNumber
STRIP_IFD0 = (0x8825,)
STRIP_EXIF = (0xA430, 0xA431, 0xA435)

#: The set, and why each frame is in it. Scores are from the run in
#: `samples/output`; they move a little when the set changes, because
#: normalisation is per-run.
FRAMES: dict[str, str] = {
    # The strong end. These are what the grid opens on and what the
    # README's hero is cut from.
    "3J0A9972": "0.90 — griffon on approach, the highest of the set",
    "3J0A9858": "0.87 — the same colony, perched",
    "3J0A8855": "0.86 — Gongga at last light",
    "3J0A7615": "0.87 — alpenglow, the frame most people stop on",
    "3J0A7802": "0.86 — long exposure, the still lake",
    "3J0A8333": "0.84 — cloud breaking over the ridge",
    "3J0A8451": "0.84 — horses in the braided river",
    "3J0A7594": "0.84 — raking light across the plateau",
    "3J0A7544": "0.83 — the peak from the grassland",
    "3J0A7226": "0.82 — the meander, wide",
    "3J0A7113": "0.83 — cairns, peak behind",
    "3J0A7790": "0.83 — shore at dusk",
    "3J0A7788": "0.82 — one minute earlier, wider",
    "3J0A7799": "0.85 — the same lake, blue hour",
    "3J0A5204": "0.82 — the road through the danxia",
    "3J0A4591": "0.82 — yardang at sunrise",
    "3J0A4475": "0.83 — yardang, closer",
    "3J0A4345": "0.81 — the beacon wall",
    "3J0A4279": "0.83 — the cart above the dunes",
    "3J0A3835": "0.82 — eaves and bell",
    "3J0A6924": "0.80 — the autumn valley",
    "3J0A4654-2": "0.83 — reeds in front of the pavilion",

    # Four near-duplicate pairs. Without these the demo has nothing to
    # fold, and burst folding is the thing it is meant to demonstrate.
    # Each pair is the same view seconds or a minute apart, and in each
    # one frame is clearly better than the other.
    "3J0A7235": "0.84 — pair A, the keeper",
    "3J0A7237": "0.77 — pair A, same view, softer",
    "3J0A5516": "0.84 — pair B, the bus placed",
    "3J0A5520": "0.80 — pair B, the bus gone past",
    "3J0A7062": "0.78 — pair C, cairn and lake",
    "3J0A7063": "0.75 — pair C, cairn recomposed",
    "3J0A7090": "0.87 — pair D, the wide one and the one it keeps",
    "3J0A7088": "0.72 — pair D, the same lake, longer lens",
    "3J0A7089": "0.69 — pair D, same view again",

    # And one that does not survive, so the demo has a verdict other
    # than `keep` in it.
    "3J0A5036": "0.64 — dune abstract, the only `maybe`",
}

#: Looked at and rejected. Written down because the next person to
#: rebuild this set will otherwise re-add them: the detector says they
#: are clean, and they score well.
REJECTED = {
    "3J0A9410": "0.87 — a girl runs across the field at the right edge, "
                "and her face is entirely legible at native resolution",
    "3J0A6029": "0.79 — a portrait; the detector had it in the clean pool",
    "3J0A6024": "0.79 — the same portrait, one frame later",
    "3J0A9477": "0.87 — people at the edge of the landscape",
    "3J0A6947": "0.85 — same",
    "3J0A7071": "0.84 — same",
    "3J0A7084": "0.83 — same",
    "3J0A5136": "0.85 — the tour bus's registration plate is readable",
    "3J0A5030": "0.82 — several hundred people on the camel trail. No face "
                "resolves, but the subject of the photograph is a crowd",
}


def prepare(src: Path, dst: Path) -> None:
    im = Image.open(src)
    exif = im.getexif()
    for tag in STRIP_IFD0:
        exif.pop(tag, None)
    ifd = exif.get_ifd(0x8769)
    for tag in STRIP_EXIF:
        ifd.pop(tag, None)
    w, h = im.size
    scale = LONG_EDGE / max(w, h)
    if scale < 1:
        im = im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    im.save(dst, "JPEG", quality=QUALITY, exif=exif.tobytes(), optimize=True)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    originals = Path(argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    keep = {f"{n}.jpg" for n in FRAMES}
    for stale in OUT.glob("*.jpg"):
        if stale.name not in keep:
            stale.unlink()
            print(f"removed {stale.name}")
    for name in FRAMES:
        src = originals / f"{name}.jpg"
        if not src.is_file():
            print(f"MISSING {src}", file=sys.stderr)
            return 1
        prepare(src, OUT / f"{name}.jpg")
        print(f"wrote   {name}.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
