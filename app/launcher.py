"""PixCull.app launcher — macOS menu bar app + web UI.

Architecture:
* The launcher is a ``rumps`` menu-bar app (the camera icon in the
  top-right corner of the screen). Quitting from the menu cleanly
  shuts down the server.
* All "real" UI is the existing web demo at http://127.0.0.1:8770/.
  Status / progress / first-run setup all live there — keeps us
  off the Tk dependency chain that breaks on pyenv-built Python.
* First-run model warming lives at ``/setup`` and ``/setup_progress``
  (added to scripts/serve_demo.py via this commit's sibling change).

Why menu bar (not Dock app)
===========================
* Photo culling is "set and forget" — fits the menu bar idiom
  (Time Machine, Bartender, etc.).
* No floating window cluttering the desktop while the user works
  in Lightroom / Capture One on the same screen.
* Cleanly handles "minimize while batch runs" since closing the
  browser tab doesn't stop the analyzer.

Why ``rumps`` (not pyobjc directly)
===================================
``rumps`` is a 200-line wrapper over NSStatusItem + NSMenu that
gives us 95% of what we need with an order of magnitude less
boilerplate. The remaining 5% (custom NSAlert, AppleScript dialogs)
we call out to ``osascript``.

PyInstaller
===========
This file is the entry-point in app/pixcull.spec. Heavy imports happen
inside functions so the "click status bar icon" responsiveness isn't
gated on transformers being loaded.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import rumps


APP_NAME = "PixCull"
APP_VERSION = "4.0.0"


# ---------------------------------------------------------------------------
# Paths + setup primitives
# ---------------------------------------------------------------------------

def app_data_dir() -> Path:
    """Per-user dir for runs, models, cache. Created if missing."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path.home() / f".{APP_NAME.lower()}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def hf_cache_dir() -> Path:
    """We redirect HuggingFace to live under our app data dir.

    Default is ~/.cache/huggingface which collides with whatever else
    the user has. Putting it under our dir keeps users' systems clean
    and lets the admin panel report a sensible single location.
    """
    p = app_data_dir() / "model_cache" / "huggingface"
    p.mkdir(parents=True, exist_ok=True)
    return p


def first_run_marker() -> Path:
    return app_data_dir() / ".pixcull_first_run_done"


def resource_root() -> Path:
    """Where the bundled assets live.

    PyInstaller sets ``sys._MEIPASS`` to the temp extraction dir at
    runtime. In dev mode we run from project root, so use the file's
    grandparent (app/ → pixcull/).
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def find_free_port(preferred: int = 8770,
                    fallbacks=(8771, 8772, 9322, 7799)) -> int:
    for p in (preferred, *fallbacks):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("No free port — close other PixCull instances?")


# ---------------------------------------------------------------------------
# AppleScript dialogs — used for the few moments we need a native popup
# ---------------------------------------------------------------------------

def osa_dialog(text: str, buttons: list[str], default: str,
                title: str = APP_NAME) -> str:
    """Show a native AppleScript dialog. Returns the clicked button.

    Falls back to the default button if osascript is unavailable
    (shouldn't happen on macOS, but degrades gracefully).
    """
    if sys.platform != "darwin":
        return default
    btns = ", ".join(f'"{b}"' for b in buttons)
    script = (
        f'set t to display dialog "{text}" buttons {{{btns}}} '
        f'default button "{default}" with title "{title}"\n'
        f'return button returned of t'
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=300,
        )
        return out.stdout.strip() or default
    except Exception:
        return default


def osa_notify(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            timeout=5,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Server bootstrap
# ---------------------------------------------------------------------------

class ServerHandle:
    """Wraps the in-process HTTP server so the menu bar can stop it.

    Runs ``ThreadingHTTPServer`` in a daemon thread. We can't use a
    subprocess in a PyInstaller bundle — sys.executable is the
    launcher binary, not a Python interpreter. Threads are simpler
    anyway: shared memory + clean shutdown via server.shutdown().
    """

    def __init__(self, port: int):
        self.port = port
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # serve_demo.main() parses argv. Build a fake argv that maps
        # to the same defaults we'd pass on the CLI, then invoke its
        # main() in a thread.
        # We import lazily so heavy deps (transformers etc.) don't block
        # the menu bar app's startup.
        from http.server import ThreadingHTTPServer
        sys.path.insert(0, str(resource_root() / "scripts"))
        # The serve_demo module references its own globals (e.g.
        # _DEMO_ROOT). Importing it directly works because it's
        # arranged as a flat module.
        import serve_demo as sd  # type: ignore

        sd._DEMO_ROOT = app_data_dir() / "runs"
        sd._DEMO_ROOT.mkdir(parents=True, exist_ok=True)

        os.environ["HF_HOME"] = str(hf_cache_dir())
        os.environ["TRANSFORMERS_CACHE"] = str(hf_cache_dir())

        server = ThreadingHTTPServer(("127.0.0.1", self.port), sd._Handler)
        # Stash config the way serve_demo's CLI flag would
        server.rescorer_mode = "auto"        # type: ignore[attr-defined]
        server.rescorer_path = str(resource_root() / "models" / "rescorer_v1.joblib")  # type: ignore[attr-defined]
        server.max_upload_bytes = 8 * 1024 * 1024 * 1024  # 8 GB  # type: ignore[attr-defined]
        server.max_upload_files = 500        # type: ignore[attr-defined]
        server.vlm_mode = "off"              # type: ignore[attr-defined]
        server.meta_mode = "off"             # type: ignore[attr-defined]

        self._server = server
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass


def wait_for_ready(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
                return True
        except Exception:
            time.sleep(0.4)
    return False


# ---------------------------------------------------------------------------
# First-run model warming.
# Done in-process (not via HTTP) so we have a clean shot at imports
# before the server forks. Output is shown in a rumps Window.
# ---------------------------------------------------------------------------

def _warm_clip():
    from transformers import CLIPModel, CLIPProcessor
    CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    CLIPModel.from_pretrained("openai/clip-vit-base-patch32")

def _warm_dinov2():
    from transformers import AutoImageProcessor, AutoModel
    AutoImageProcessor.from_pretrained("facebook/dinov2-base")
    AutoModel.from_pretrained("facebook/dinov2-base")

def _warm_u2net():
    from rembg import new_session
    new_session(model_name="u2net")

def _warm_pyiqa():
    import pyiqa
    for name in ("laion_aes", "clipiqa"):
        pyiqa.create_metric(name, device="cpu")

def _warm_qwen3vl():
    from huggingface_hub import snapshot_download
    snapshot_download("mlx-community/Qwen3-VL-4B-Instruct-4bit")


WARM_TARGETS = [
    ("CLIP ViT-B/32", _warm_clip),
    ("DINOv2-base", _warm_dinov2),
    ("U²-Net", _warm_u2net),
    ("pyiqa LAION-Aes + CLIP-IQA", _warm_pyiqa),
]

OPTIONAL_VLM = ("Qwen3-VL-4B-4bit (~2.9 GB)", _warm_qwen3vl)


def run_first_setup(include_vlm: bool) -> bool:
    """Sequential model warming with native progress notifications.

    Returns True if all targets completed. Failures are logged via a
    notification but don't abort — degraded mode is OK.
    """
    targets = list(WARM_TARGETS)
    if include_vlm:
        targets.append(OPTIONAL_VLM)

    osa_notify(APP_NAME, f"开始下载模型(共 {len(targets)} 个,~10 分钟)…")
    n_ok = 0
    for i, (label, fn) in enumerate(targets, start=1):
        try:
            fn()
            osa_notify(APP_NAME, f"[{i}/{len(targets)}] {label} ✓")
            n_ok += 1
        except Exception as exc:
            osa_notify(APP_NAME, f"[{i}/{len(targets)}] {label} 失败: {exc}")
            print(f"[setup] {label} failed: {type(exc).__name__}: {exc}",
                  file=sys.stderr)

    first_run_marker().write_text(
        f"completed at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"include_vlm={include_vlm}\n"
        f"n_ok={n_ok}/{len(targets)}\n"
        f"app_version={APP_VERSION}\n",
        encoding="utf-8",
    )
    return n_ok == len(targets)


# ---------------------------------------------------------------------------
# Menu bar app
# ---------------------------------------------------------------------------

class PixCullMenuApp(rumps.App):
    """The menu bar's status item.

    Single instance — invoked once via ``main()`` after the first-run
    setup has completed and the server is up.
    """

    def __init__(self, handle: ServerHandle):
        super().__init__(APP_NAME, icon=None, quit_button=None)
        self._handle = handle
        self._port = handle.port
        self._url = f"http://127.0.0.1:{handle.port}/"

        self.menu = [
            rumps.MenuItem(f"打开 {APP_NAME} (浏览器)", callback=self._on_open),
            rumps.MenuItem("打开存储管理", callback=self._on_admin),
            None,                              # separator
            rumps.MenuItem(f"地址: {self._url}", callback=None),
            rumps.MenuItem(f"数据目录: …/{app_data_dir().name}",
                           callback=self._on_open_data_dir),
            None,
            rumps.MenuItem("重新下载模型 (首次设置)", callback=self._on_resetup),
            None,
            rumps.MenuItem(f"关于 {APP_NAME} v{APP_VERSION}", callback=self._on_about),
            rumps.MenuItem("退出", callback=self._on_quit),
        ]

    # --- menu callbacks ---------------------------------------------------
    def _on_open(self, _):
        webbrowser.open(self._url)

    def _on_admin(self, _):
        webbrowser.open(self._url + "admin")

    def _on_open_data_dir(self, _):
        subprocess.run(["open", str(app_data_dir())])

    def _on_resetup(self, _):
        try:
            first_run_marker().unlink()
        except FileNotFoundError:
            pass
        rumps.alert(
            title=APP_NAME,
            message="下次启动时会重新下载模型。立即退出?",
            ok="退出",
        )
        self._on_quit(None)

    def _on_about(self, _):
        rumps.alert(
            title=APP_NAME,
            message=(
                f"PixCull v{APP_VERSION}\n"
                f"AI 摄影分拣 · 6 轴 rubric + VLM + DeepSeek 综合\n\n"
                f"• 数据存于 ~/Library/Application Support/{APP_NAME}/\n"
                f"• 服务地址 {self._url}\n"
                f"• 命令行启动: scripts/serve_demo.py"
            ),
        )

    def _on_quit(self, _):
        try:
            self._handle.stop()
        except Exception:
            pass
        rumps.quit_application()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> int:
    os.environ.setdefault("HF_HOME", str(hf_cache_dir()))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(hf_cache_dir()))

    if not first_run_marker().exists():
        # Native AppleScript yes/no for the heavy VLM
        choice = osa_dialog(
            text=("欢迎使用 PixCull。\n\n"
                  "首次启动需要下载 ~2 GB 预训练模型(CLIP / DINOv2 / U²-Net / pyiqa)。"
                  "完成后所有功能离线可用。\n\n"
                  "可选:再下载本地视觉模型 Qwen3-VL-4B (~2.9 GB),"
                  "用于无 API 时的离线视觉评分。"),
            buttons=["取消", "仅基础模型", "全部下载"],
            default="仅基础模型",
        )
        if choice == "取消":
            return 0
        include_vlm = (choice == "全部下载")
        # Run model warming. This blocks for several minutes; we use
        # native notifications for progress instead of a window.
        run_first_setup(include_vlm)
        osa_notify(APP_NAME, "首次设置完成,启动中…")

    port = find_free_port()
    handle = ServerHandle(port)
    handle.start()

    if not wait_for_ready(port, timeout=30.0):
        osa_notify(APP_NAME, "服务器 30 秒内没就绪,请查看 Console.app")
        handle.stop()
        return 1

    osa_notify(APP_NAME, f"已启动 · 顶部菜单栏图标 · {port}")
    webbrowser.open(f"http://127.0.0.1:{port}/")

    # rumps owns the run loop from here. ^C in dev mode shuts everything
    # down via the quit handler.
    PixCullMenuApp(handle).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
