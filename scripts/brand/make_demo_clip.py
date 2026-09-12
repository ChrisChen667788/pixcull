"""v3.77 — build the demo clip the transcript screenshot is shot from.

`24-transcript-edit.png` was an ffmpeg test pattern with synthesised
speech. It read as a rendering bug on the front page of both READMEs,
and it was there because the panel it shows needs *speech*: the panel's
whole job is to put spoken words on screen as editable text, and real
speech is a voiceprint, and the words themselves are whatever was said.

So the clip is real footage with its real audio, and the faces in it are
frosted.

**The faces have to be frosted, not avoided.** Measured on the source:
speech runs from 0.5s to 18.7s of a 20.7s clip, so trimming away the
stretch where the subject turns to camera takes the audio with it. And
across the whole sledding set there is no clip where the subject stays
turned away.

**Detection runs at full size.** A first pass screened 640 px frames,
found a 29-second "face-free" run in another clip, and at native
3840×2160 that run had bystanders with legible faces in it. This
repository already knew that — "`face_count == 0` is not evidence of no
face; screen by eye at ≥1400 px" — and the shortcut reproduced it
anyway.

**Gaps are filled, not trusted.** The detector finds the face on about
three frames in four, and the misses are scattered through the middle of
a run rather than at its edges. A per-frame blur would therefore leave
the face legible on a quarter of the frames. Every gap between two
detections is interpolated and the box is dilated generously, so a miss
is covered by its neighbours.

Usage::

    python scripts/brand/make_demo_clip.py \\
        --src "/path/to/clip.MP4" --out /tmp/pixcull_demo/sled.mp4
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

#: How much bigger than the detected box the frosted region is drawn.
#: The detector returns a tight crop around the features; a hat and a
#: chin turned away live just outside it. Enough to cover, not so much
#: that the treatment becomes the subject — the first cut used 0.55 and
#: produced a grey slab over a third of the frame, which is exactly the
#: "looks like a bug" this version exists to get rid of.
DILATE = 0.22

#: How far either side of a gap to look for a detection to interpolate
#: between. At 30 fps this is half a second.
COAST = 15


def _probe(src: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(src)],
        capture_output=True, text=True)
    vals = [v for v in out.stdout.split() if v]
    return {"width": int(vals[0]), "height": int(vals[1]),
            "duration": float(vals[2])}


def _detect(frames: list[Path], conf: float) -> list[list[tuple]]:
    """One list of boxes per frame, in pixels."""
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    import mediapipe as mp

    from pixcull.detectors.face import FACE_DETECTOR_MODEL
    det = mp_vision.FaceDetector.create_from_options(
        mp_vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=str(FACE_DETECTOR_MODEL)),
            min_detection_confidence=conf))
    out = []
    for f in frames:
        res = det.detect(mp.Image.create_from_file(str(f)))
        boxes = []
        for d in (res.detections or []):
            b = d.bounding_box
            boxes.append((b.origin_x, b.origin_y,
                          b.origin_x + b.width, b.origin_y + b.height))
        out.append(boxes)
    return out


def _fill_gaps(per_frame: list[list[tuple]]) -> list[list[tuple]]:
    """Carry a box across the frames where the detector found nothing.

    The first cut took the union of everything seen within COAST frames
    either side. On a sled the subject crosses a lot of frame in half a
    second, so that union was enormous and centred on nothing: it buried
    a third of the picture under grey and still left the head showing
    above it on some frames. Worse on both counts than doing nothing.

    This walks between the nearest real detection on each side and
    interpolates, which tracks the motion instead of bounding it. A gap
    at the very start or end has only one neighbour, so it holds that
    box rather than inventing a trajectory.
    """
    n = len(per_frame)
    prev = [-1] * n
    nxt = [-1] * n
    last = -1
    for i in range(n):
        if per_frame[i]:
            last = i
        prev[i] = last
    last = -1
    for i in range(n - 1, -1, -1):
        if per_frame[i]:
            last = i
        nxt[i] = last

    def _first(i):
        # v3.87 — `[0]` is the whole multi-face story: a gap between two
        # frames that each held two faces is filled with ONE box, and
        # the second person is unfrosted for the length of the gap.
        # Nothing downstream could see that, because the containment
        # check only looks at frames that HAVE a detection. `main()`
        # refuses the clip when this arises rather than covering one
        # face and reporting success.
        return per_frame[i][0]

    filled: list[list[tuple]] = []
    for i in range(n):
        if per_frame[i]:
            filled.append(list(per_frame[i]))
            continue
        a, b = prev[i], nxt[i]
        if a >= 0 and i - a > COAST:
            a = -1
        if b >= 0 and b - i > COAST:
            b = -1
        if a < 0 and b < 0:
            filled.append([])
        elif a < 0 or b < 0:
            filled.append([_first(a if a >= 0 else b)])
        else:
            wgt = (i - a) / (b - a)
            pa, pb = _first(a), _first(b)
            filled.append([tuple(round(pa[k] + (pb[k] - pa[k]) * wgt)
                                 for k in range(4))])
    return filled


def _frost(img, boxes, w: int, h: int):
    """Frosted glass: an oval of heavy blur, feathered at its edge.

    A hard rectangle of grey is what a broken decode looks like. The
    mask is an ellipse with a soft edge so the treatment reads as
    deliberate, and the blur is scaled to the region so a small face and
    a large one are equally unreadable.
    """
    from PIL import Image, ImageDraw, ImageFilter
    for (x0, y0, x1, y1) in boxes:
        bw, bh = x1 - x0, y1 - y0
        px, py = int(bw * DILATE), int(bh * DILATE)
        x0, y0 = max(0, x0 - px), max(0, y0 - py)
        x1, y1 = min(w, x1 + px), min(h, y1 + py)
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        region = img.crop((x0, y0, x1, y1))
        rw, rh = region.size
        radius = max(14, int(min(rw, rh) * 0.42))
        blurred = region.filter(ImageFilter.GaussianBlur(radius))
        mask = Image.new("L", (rw, rh), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, rw - 1, rh - 1), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(max(6, min(rw, rh) // 10)))
        region.paste(blurred, (0, 0), mask)
        img.paste(region, (x0, y0))
    return img


def _coverage_report(per_frame: list[list[tuple]],
                     filled: list[list[tuple]],
                     escaped: list[int]) -> list[str]:
    """What the containment check knows, and the much larger part it does not.

    v3.77 printed one line — `containment: 0 detected face(s) fell
    outside the frosted region` — and that line was read, by its author,
    as "no face escaped". It is not the same statement, and v3.87
    measured the gap on the clip that line cleared:

    * On **145 of 620 frames the detector found nothing at all**. The
      containment loop iterates over what was found, so on those frames
      it has nothing to iterate and passes. The frames where a face is
      hardest to find are exactly the frames where it is least likely to
      be frosted, and they are the ones the check is blind to.

    * Worse, and this is the part that makes the whole approach a proxy
      rather than a test: on frame 101 the detector returned **two boxes,
      both on the subject's coat** — one over a shoulder, one over a
      pocket — and none on her face, which is in profile at the top of
      the frame and entirely legible. Both boxes were inside the frosted
      region, so containment was 100%, the script printed its clean line,
      and the face shipped unfrosted. Two false positives satisfied the
      guard completely.

    Neither a second detector nor a lower confidence closes this. Both
    on-disk models were tried on that frame: BlazeFace short-range finds
    the coat, FaceLandmarker finds nothing at all.

    So the numbers below are diagnostics, not a certificate. The gate on
    publication is a person looking at the frames that will actually
    appear on screen — `docs/demo-clip-frames.tsv` and the refusal in
    `capture_video_shots.py`.
    """
    n = len(per_frame)
    unseen = sum(1 for b in per_frame if not b)
    interpolated = sum(1 for i in range(n) if not per_frame[i] and filled[i])
    bare = sum(1 for b in filled if not b)
    return [
        f"[clip] detector returned a box on {n - unseen}/{n} frames; "
        f"{interpolated} more got an interpolated box; {bare} frames "
        f"carry no frosted region at all",
        f"[clip] containment: {len(escaped)} of the boxes it did return "
        f"fell outside the frosted region"
        + (f" — {escaped[:8]}" if escaped else ""),
        "[clip] this does NOT say the faces are covered: it says the "
        "boxes are. A face the detector missed, and a box it put on a "
        "coat, both pass. Screen the frames you will publish by eye.",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=0.0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--conf", type=float, default=0.20)
    ap.add_argument("--keep-frames", type=Path, default=None,
                    help="write the frosted frames here for an eye check")
    args = ap.parse_args()

    if not args.src.is_file():
        print(f"no such clip: {args.src}", file=sys.stderr)
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"{tool} not on PATH", file=sys.stderr)
            return 2

    sys.path.insert(0, str(REPO))
    from PIL import Image

    meta = _probe(args.src)
    print(f"[clip] source {meta['width']}x{meta['height']} "
          f"{meta['duration']:.1f}s")

    tmp = Path(tempfile.mkdtemp(prefix="pixcull-clip-"))
    raw, done = tmp / "raw", tmp / "done"
    raw.mkdir(); done.mkdir()

    cut = []
    if args.start:
        cut += ["-ss", str(args.start)]
    if args.duration:
        cut += ["-t", str(args.duration)]
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *cut,
         "-i", str(args.src), "-vf", f"fps={args.fps},scale={args.width}:-2",
         "-y", str(raw / "%05d.png")], check=True)
    frames = sorted(raw.glob("*.png"))
    print(f"[clip] {len(frames)} frames at {args.width}px")

    per_frame = _detect(frames, args.conf)
    seen = sum(1 for b in per_frame if b)
    filled = _fill_gaps(per_frame)
    covered = sum(1 for b in filled if b)
    print(f"[clip] detector found a face on {seen}/{len(frames)} frames; "
          f"gap-filling covers {covered}")

    w = h = 0
    for f, boxes in zip(frames, filled):
        img = Image.open(f).convert("RGB")
        w, h = img.size
        if boxes:
            img = _frost(img, boxes, w, h)
        img.save(done / f.name)
    if args.keep_frames:
        args.keep_frames.mkdir(parents=True, exist_ok=True)
        for f in sorted(done.glob("*.png")):
            shutil.copy2(f, args.keep_frames / f.name)

    # Containment: is every box the detector found in the ORIGINAL inside
    # the region that got frosted? Exactly checkable, and it catches one
    # real failure — a gap fill that drifts off a face the detector did
    # see. Keep it. It is not a clearance, and v3.87 measured how far
    # short it falls; `_coverage_report` says the rest.
    escaped = []
    for i, (found, drawn) in enumerate(zip(per_frame, filled)):
        for fb in found:
            ok = False
            for db in drawn:
                bw, bh = db[2] - db[0], db[3] - db[1]
                px, py = int(bw * DILATE), int(bh * DILATE)
                if (fb[0] >= db[0] - px and fb[1] >= db[1] - py
                        and fb[2] <= db[2] + px and fb[3] <= db[3] + py):
                    ok = True
                    break
            if not ok:
                escaped.append(i)
    for line in _coverage_report(per_frame, filled, escaped):
        print(line)
    if escaped:
        print("[clip] REFUSING to write: a box the detector found is not "
              "covered.", file=sys.stderr)
        return 1
    crowded = sum(1 for b in per_frame if len(b) > 1)
    gaps = sum(1 for i, b in enumerate(per_frame) if not b and filled[i])
    if crowded and gaps:
        print(f"[clip] REFUSING to write: {crowded} frame(s) hold more than "
              f"one detection and {gaps} frame(s) are gap-filled. The fill "
              f"carries one box, so on those frames everyone but the first "
              f"person is uncovered. Cut to a stretch with one subject, or "
              f"frost by hand.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    audio = tmp / "audio.m4a"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *cut,
         "-i", str(args.src), "-map", "0:a:0", "-c:a", "aac", "-b:a", "128k",
         "-y", str(audio)], check=True)
    # -map_metadata -1 so no drive name, original path, device tag or
    # GPMF telemetry rides along into a public repository.
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-framerate", str(args.fps), "-i", str(done / "%05d.png"),
         "-i", str(audio), "-map_metadata", "-1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
         "-c:a", "copy", "-shortest", "-y", str(args.out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"[clip] wrote {args.out} ({args.out.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
