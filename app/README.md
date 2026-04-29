# PixCull.app — V4.0 macOS bundle

## What this is

A double-click .app that bundles the entire PixCull stack so a non-developer
photographer can install and use it without touching a terminal. Wraps:

- The web demo (`scripts/serve_demo.py`)
- The full V0.1-V3.1 pipeline + 6-axis rubric + meta-judge
- A native macOS menu-bar UI (`rumps`) for status / quit / open

## Files in this directory

| | |
|---|---|
| `launcher.py` | Entry point. Runs first-run setup → starts in-process HTTP server → shows menu bar status item → opens browser. |
| `pixcull.spec` | PyInstaller build recipe. Bundles Python + all deps + bundled V2.1 axis rescorers. Models > 100 MB download on first run instead of bloating the .app. |
| `NOTARIZATION.md` | How to sign + notarize for wider distribution (requires $99/year Apple Developer account). |
| `README.md` | This file. |

## How a user experiences it

1. Download `PixCull.dmg`, drag `PixCull.app` to `/Applications`
2. First launch → AppleScript dialog: "下载基础模型 / 全部模型 / 取消"
3. ~10 min one-time download (CLIP / DINOv2 / U²-Net / pyiqa, optionally Qwen3-VL)
4. Status bar icon appears, browser opens to http://127.0.0.1:8770/
5. Drag photos / select local folder → analysis → results page with 6-axis stars

## How a developer builds it

```bash
# From pixcull/ project root
.venv/bin/pip install pyinstaller rumps    # one-time
./scripts/build_app.sh                     # builds dist/PixCull.app  (~5 min)
./scripts/make_dmg.sh                      # makes dist/PixCull.dmg

# Test
open dist/PixCull.app
```

The .app is **ad-hoc signed**, which is enough for personal use
(first launch needs right-click → Open). For wider distribution see
`NOTARIZATION.md`.

## Where data lives

| Path | What |
|---|---|
| `/Applications/PixCull.app` | The bundle (everything except big models) |
| `~/Library/Application Support/PixCull/` | Per-user state (delete to fully uninstall) |
| `~/Library/Application Support/PixCull/runs/` | Each analysis run (input copies in upload mode, scores in scan mode) |
| `~/Library/Application Support/PixCull/model_cache/huggingface/` | Downloaded models (CLIP, DINOv2, Qwen3-VL, etc.) |
| `~/Library/Application Support/PixCull/.pixcull_first_run_done` | Marker file — delete to re-run setup |

## Architecture: why menu bar + in-process server (not Electron / Tauri)

* **The "web demo" stays the source of truth.** Same `serve_demo.py`
  works in dev mode (terminal) and in the bundle. No UI rewrite for
  the .app — saves us thousands of lines of duplicate React/Svelte.
* **Menu bar fits the workflow.** Photo culling runs in the background
  while the user works in Lightroom on the same screen. A floating
  Dock window would clutter their primary tool.
* **In-process server (vs subprocess).** PyInstaller's `sys.executable`
  in a bundle is the launcher binary, not a Python interpreter — so
  spawning a subprocess to run `serve_demo.py` doesn't work.
  Instead we import `serve_demo` as a module and call its
  `ThreadingHTTPServer` directly in a daemon thread. Clean shutdown
  via `server.shutdown()` from the menu bar's "退出" item.

## Known limitations / TODOs

- **Tk-broken pyenv Python**: pyenv-installed Python 3.12 doesn't
  ship `_tkinter`. The launcher uses rumps (NSStatusItem-based)
  instead. If a user builds with a Python that DOES have Tk, that's
  fine — we just don't depend on it.
- **First launch UX**: model download happens with macOS notifications,
  no inline progress bar yet. V4.1 idea: serve a `/setup` HTML page
  with a real progress bar.
- **Apple silicon only by default**: spec defaults to whatever arch
  the build machine has. `--target-arch universal2` works if you
  install a universal Python, but doubles the .app size.
- **No auto-update**: V4.1 candidate — integrate Sparkle.
