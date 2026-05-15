# PixCull Companion · iPad / iPhone

ROADMAP P2.1. Native SwiftUI app that connects to a PixCull server
over LAN (via the V25 `/api/v1` namespace) for on-location review
during a shoot.

## Why a mobile app

* **Wedding / event photographer** plugs the camera into a Mac
  running PixCull during the cocktail-hour break. The Mac scans
  the SD card. With the companion app on iPad, the photographer
  reviews the keep/maybe/cull on the couch — keyboard shortcuts
  on iPad's Magic Keyboard or just thumb swipes.
* **Sports photographer** processes a 1000-frame burst on a
  laptop in the press room. The companion app on the phone lets
  them confirm the chosen peak frame on the train ride home.
* **Studio team** has PixCull running on a dedicated NAS Mac.
  Multiple iPads at multiple desks all read from the same
  ``/api/v1`` JSON.

## Architecture

```
   iPad / iPhone (this app)            Mac / NAS (PixCull server)
   ┌─────────────────────────┐         ┌──────────────────────────────┐
   │ SwiftUI views           │ ─HTTP→  │ scripts/serve_demo.py        │
   │  RunList                │         │  /api/v1/users               │
   │  RunDetail              │         │  /api/v1/runs/<id>           │
   │  PhotoBrowser           │         │  /api/v1/runs/<id>/decisions │
   │ ─────────────────────── │         │  /api/v1/runs/<id>/face_clu… │
   │ APIClient (async/await) │         │  /api/v1/users/active        │
   │ Settings (server URL +  │         └──────────────────────────────┘
   │  X-PixCull-API-Key)     │
   └─────────────────────────┘
```

Zero local state besides:
* server URL (typed by the user, e.g. `http://192.168.1.42:8770`)
* API key (`X-PixCull-API-Key`) for non-localhost deployments —
  matches `PIXCULL_API_KEY` env on the Mac side

CORS isn't needed for native iOS (URLSession isn't a browser); the
V25 CORS allowlist applies only when the same endpoint is hit from
a JS app in Safari / Chrome.

## V0.1 (this commit) — read-only browser

What's included:
* `RunListView` — `GET /api/v1/runs` → list with summary pills
* `RunDetailView` — `GET /api/v1/runs/<id>` → counts + links
* `PhotoBrowserView` — embedded WKWebView pointing at the Mac's
  full results page. Avoids reimplementing the whole grid in
  SwiftUI for V0.1; later versions can swap to a native grid.
* `SettingsView` — server URL + API key persisted in @AppStorage
* Light/Dark adaptive styling via SwiftUI's automatic colors

What's deliberately NOT here yet (V0.2+):
* Native photo grid view (current: WKWebView fallback)
* On-device InsightFace re-clustering (the V25 API does it
  server-side; a native fallback would let users review when the
  Mac is asleep)
* Push notifications when a scan finishes
* Per-photo gestures (swipe-right = keep, swipe-left = cull) that
  POST back to the annotation endpoint

## Build

This is a Swift Package + Xcode project skeleton — not buildable
into a `.ipa` without Xcode. To open:

```
cd mobile/PixCullCompanion
open Package.swift                      # opens in Xcode
```

Or import as a SPM package into an existing iOS host app.

iOS 16+ target; SwiftUI 4. No third-party deps.

## Configuration

In-app: tap the gear icon → enter:
* **Server URL**: e.g. `http://192.168.1.42:8770` (LAN reachable)
* **API Key** (optional): only needed when the Mac sets
  `PIXCULL_API_KEY` env var

The app does a single `GET /api/v1/` ping on launch to verify
both URL and key.
