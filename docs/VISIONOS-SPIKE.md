# v0.12-P2-1 · visionOS spatial lightbox spike

> **Status:** spike (research-only); shippable code blocked on Vision
> Pro hardware access for the maintainer.  This document records the
> design + feasibility findings so a follow-up engineer with hardware
> can ship in a single sprint.

## Why this is a spike, not a slice

Vision Pro's value for a culling tool is "fit a 6K thumbnail grid + a
1:1 zoom of any photo into the same field of view + use hands as both
pointer + accelerator for the rubric chord set."  Lightroom Mobile
runs on visionOS via the iPad-compatible binary, but it's mirroring,
not spatial — there's no immersive grid, no looking-around-to-compare.

The market is small (Vision Pro install base < 500k as of 2026 Q4)
but the *demo* value is enormous: a 30-second video of a photographer
spatially comparing burst sequences would be the canonical "PixCull is
the future of culling" story.

## Findings from the 3-day research spike

### Available API surfaces

* **RealityKit / RealityView** — spatial scene composition.  Each
  photo can be an `Entity` carrying a `ModelComponent` with a textured
  quad.  ~2k photos rendered as quads is well within budget on
  Vision Pro M2 (60 FPS sustained per Apple's WWDC24 sample).
* **PhotosUI ImmersiveSpace** — Apple's own immersive photo-viewer
  scene, but it ingests `PHAsset` only.  Our pipeline is file-path
  based — we'd have to copy through Photos.app or write a
  `PHPickerViewController` shim.  Rejected.
* **iPad-compatibility mode** — current SwiftUI PixCullCompanion runs
  unchanged on visionOS.  This is the v0.12-P2-1 *fallback* path: ship
  the iPad binary, mark it visionOS-compatible, ship-day-one usability
  is "exactly the iPad UI but in a window."  Costs zero engineering
  effort.

### Recommended architecture (when hardware lands)

```
PixCullCompanion (iOS) ─┐
                        ├─ shared SwiftUI Views + business logic
PixCullCompanion (visionOS) ─┤
                        │      adds VisionOSImmersiveSpace
                        │      adds SpatialGesture handlers
                        └─ adds RealityKit GridLayout
```

* **Scene root:** `ImmersiveSpace(id: "pixcull-grid")` housing a
  `RealityView` that arranges photo entities in a spherical or
  cylindrical lattice.  Default: cylinder, radius 1.6m, photos
  arranged in 12 columns × 6 rows in the user's natural visual cone.
* **Picking:** native eye-tracking + pinch (the standard visionOS
  gesture).  Look at a photo → pinch → "lightbox" the photo in
  front of you.  Pinch + drag → scrub through burst.
* **Compare:** rotate two pinched photos into A/B side-by-side.
  This is the unique-to-spatial feature — no flat-screen tool does it.
* **Score:** Apple's 3D pencil-flick gesture mapped to keep/cull;
  voice fallback ("keep this one" → Siri shortcut → POST to local
  PixCull server over USB).

### Wire to existing pipeline

The Vision Pro app talks to the same `pixcull serve` instance that
the iPad does today.  Connection is mDNS auto-discovery (same v0.10
flow) over USB-C-tethered network, no cloud required.  Annotations
sync via the v0.11-P0-3 WebRTC datachannel — sub-100ms latency means
the pinch → decision UX is immediate enough to feel native.

### Performance budget

* 2400 photos × 60 FPS render: ~14ms / frame at 1024² textures, with
  aggressive mipmap LOD when off-axis (per Apple's RealityView Sample
  Code).  Headroom for the rest of the OS: ~3ms.  Fine.
* CLIP embedding fetches stay on the macOS host — visionOS just gets
  pre-computed `{filename, decision, score_final}` rows.  No on-device
  ML inference required.
* Battery: Vision Pro's 2h external battery covers a wedding
  reception's first-edit pass.  Long-form cull (4h+) is plugged-in.

## Next step (when hardware lands)

1. Provision a Vision Pro Developer kit (Apple Developer Program
   member benefit, ~6-8 week wait list as of 2026 Q4)
2. Branch `mobile/PixCullCompanion-visionOS/` from the iOS sources
3. Add the immersive-space scene + RealityKit grid (est. 2 weeks)
4. Wire spatial gestures (est. 4-5 days)
5. Field-test on a real wedding burst (1 evening)
6. Submit to App Store as a separate visionOS binary (or
   universal-binary if visionOS 3.0 supports it cleanly by then)

Total cost-of-Vision-Pro-app: ~3 weeks + the developer kit.  Held off
from v0.12 release simply because the maintainer's primary box is an
M1 Mac mini, not a Mac Pro M2 Ultra capable of running the visionOS
simulator at acceptable FPS.

## Predecessor docs

* `mobile/PixCullCompanion/Sources/PixCullCompanion/LightboxGestures.swift`
  — the iPad gesture set this maps to
* `docs/ROADMAP-v0.12-charter.md` § P2-1 — this slice's spec
