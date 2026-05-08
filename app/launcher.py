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


def config_path() -> Path:
    """User config file: API keys, mode defaults. Mode 0600.

    Schema (all optional):
      {
        "deepseek_api_key": "sk-...",
        "vlm_mode": "off" | "local" | "deepseek" | ...,
        "meta_mode": "off" | "deepseek" | ...
      }
    """
    return app_data_dir() / "config.json"


def load_config() -> dict:
    """Load + sanitize the user's config.

    V14.0: instead of silently swallowing a corrupt file (which used to
    drop the user's DeepSeek key without warning), back up the bad file
    with a timestamp suffix and surface a one-line note via stderr so
    something rebooted the user's API key isn't a mystery. The notify
    side is wired by the launcher's main() at startup since we can't
    import rumps from this module-level helper.
    """
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Back up the corrupt file before returning empty so the user can
        # recover their key by hand if they had one.
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = p.with_suffix(f".corrupt-{stamp}.json")
            p.replace(backup)
            sys.stderr.write(
                f"[pixcull] config.json was unreadable ({type(exc).__name__}: "
                f"{exc}); backed up to {backup}\n"
            )
        except OSError as exc2:
            sys.stderr.write(
                f"[pixcull] config.json unreadable AND couldn't back up: "
                f"{type(exc2).__name__}: {exc2}\n"
            )
        return {}


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

        # V7.1: read user-supplied config.json for API keys + mode
        # defaults. Sets the env var DeepSeek meta-judge looks up,
        # so users don't need to launch from terminal with env vars.
        cfg = load_config()
        if cfg.get("deepseek_api_key"):
            os.environ["DEEPSEEK_API_KEY"] = cfg["deepseek_api_key"]
        # Defaults: if the user has a DeepSeek key, turn on the full
        # hybrid stack. Otherwise gracefully degrade to off.
        default_vlm = "local" if (
            (cfg.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY"))
        ) else "off"
        default_meta = "deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "off"

        server = ThreadingHTTPServer(("127.0.0.1", self.port), sd._Handler)
        # Stash config the way serve_demo's CLI flag would
        server.rescorer_mode = "auto"        # type: ignore[attr-defined]
        server.rescorer_path = str(resource_root() / "models" / "rescorer_v1.joblib")  # type: ignore[attr-defined]
        server.max_upload_bytes = 8 * 1024 * 1024 * 1024  # 8 GB  # type: ignore[attr-defined]
        server.max_upload_files = 500        # type: ignore[attr-defined]
        server.vlm_mode = cfg.get("vlm_mode", default_vlm)   # type: ignore[attr-defined]
        server.meta_mode = cfg.get("meta_mode", default_meta) # type: ignore[attr-defined]

        print(f"[launcher] vlm_mode={server.vlm_mode} meta_mode={server.meta_mode}",
              file=sys.stderr)

        self._server = server
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception as exc:
                # V14.0 — server shutdown failure during quit shouldn't
                # block the app exit, but it's worth knowing about.
                sys.stderr.write(
                    f"[launcher] server.stop() failed: "
                    f"{type(exc).__name__}: {exc}\n"
                )


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


def run_first_setup(include_vlm: bool, status_cb=None) -> bool:
    """Sequential model warming with progress reporting.

    Returns True if all targets completed. Failures are logged via the
    status callback but don't abort — degraded mode is OK.

    V14.6 — ``status_cb`` is an optional callable invoked between
    targets so the in-process server can update its
    ``_FIRST_RUN_STATE`` and the browser-side progress page can
    drive a real progress bar instead of relying on macOS native
    notifications. Falls back to silent operation if not provided
    (matches the V11.x behaviour for any non-launcher caller).
    """
    targets = list(WARM_TARGETS)
    if include_vlm:
        targets.append(OPTIONAL_VLM)

    def _emit(**kw):
        if status_cb is not None:
            try:
                status_cb(**kw)
            except Exception as exc:
                # Status callback failure must never derail the actual
                # download — log and carry on.
                sys.stderr.write(
                    f"[setup] status callback failed: "
                    f"{type(exc).__name__}: {exc}\n"
                )

    _emit(phase="warming", total=len(targets), current=0,
          step_label="准备下载…", started_at=time.time(),
          include_vlm=include_vlm, errors=[])

    n_ok = 0
    for i, (label, fn) in enumerate(targets, start=1):
        _emit(current=i - 1, step_label=f"下载 {label}…")
        try:
            fn()
            _emit(current=i, step_label=f"{label} ✓")
            n_ok += 1
        except Exception as exc:
            err_msg = f"{type(exc).__name__}: {exc}"
            print(f"[setup] {label} failed: {err_msg}", file=sys.stderr)
            # Append to errors via a callback that reads-modifies-writes
            # under the server's lock.
            if status_cb is not None:
                try:
                    status_cb(_append_error=(label, err_msg))
                except Exception:
                    pass
            _emit(current=i, step_label=f"{label} 失败(继续)")

    first_run_marker().write_text(
        f"completed at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"include_vlm={include_vlm}\n"
        f"n_ok={n_ok}/{len(targets)}\n"
        f"app_version={APP_VERSION}\n",
        encoding="utf-8",
    )
    _emit(phase="done", current=n_ok, total=len(targets),
          step_label="全部就绪")
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
            rumps.MenuItem("配置 DeepSeek API key", callback=self._on_set_key),
            rumps.MenuItem("查看错误日志", callback=self._on_open_logs),
            rumps.MenuItem("重新下载模型 (首次设置)", callback=self._on_resetup),
            rumps.MenuItem("检查更新", callback=self._on_check_update),
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

    def _on_set_key(self, _):
        """Prompt for DeepSeek API key + persist to config.json."""
        # Use AppleScript display dialog with hidden answer for the key
        script = (
            'set t to display dialog "粘贴 DeepSeek API key (会写到 '
            '~/Library/Application Support/PixCull/config.json,权限 0600,'
            '不会进 git)" default answer "" with hidden answer '
            'with title "PixCull · DeepSeek API key"\n'
            'return text returned of t'
        )
        try:
            out = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            key = (out.stdout or "").strip()
        except Exception:
            return
        if not key:
            return
        cfg = load_config()
        cfg["deepseek_api_key"] = key
        cfg.setdefault("vlm_mode", "local")
        cfg.setdefault("meta_mode", "deepseek")
        try:
            config_path().write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            os.chmod(config_path(), 0o600)
        except OSError as exc:
            osa_notify(APP_NAME, f"保存失败: {exc}")
            return
        osa_notify(APP_NAME, "API key 已保存,下次启动生效")

    def _on_open_logs(self, _):
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(log_dir)])

    def _on_check_update(self, _):
        """V13.0 — manual Sparkle-style update check."""
        try:
            sys.path.insert(0, str(resource_root() / "app"))
            import updater  # type: ignore
            result = updater.check_for_update(force=True)
        except Exception as exc:
            rumps.alert(title=APP_NAME,
                         message=f"检查失败: {type(exc).__name__}: {exc}")
            return
        if not result.get("available"):
            rumps.alert(title=APP_NAME,
                         message=f"已是最新版本 v{updater._running_version()}")
            return
        choice = rumps.alert(
            title=APP_NAME,
            message=(f"发现新版本 v{result['latest']}\n"
                     f"你当前 v{result['current']}\n\n"
                     f"{(result.get('notes') or '')[:300]}\n\n"
                     f"在浏览器打开下载页?"),
            ok="打开下载",
            cancel="稍后",
        )
        if choice == 1:  # "ok"
            webbrowser.open(result.get("download_url") or "https://pixcull.dev/")

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

def _redirect_stderr_to_log() -> None:
    """V7.1: capture stdout/stderr to a per-launch log file.

    PyInstaller --windowed mode silently drops any text written to
    stdout/stderr. When the pipeline crashes (FileNotFoundError on
    a missing data file etc.) the user sees nothing in the UI and
    Console.app shows only macOS framework chatter. Redirecting to
    a file inside the user's data dir means the next time something
    breaks we have a Python traceback to read.

    Files rotate by date so logs don't grow unbounded.
    """
    import datetime
    log_dir = app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fname = log_dir / f"pixcull_{datetime.date.today().isoformat()}.log"
    try:
        # Use line-buffered append. Inherit fd to subprocess if any.
        f = open(fname, "a", buffering=1, encoding="utf-8")
        sys.stdout = f
        sys.stderr = f
        f.write(f"\n--- launcher started at {datetime.datetime.now().isoformat()} ---\n")
    except OSError:
        pass


def main() -> int:
    _redirect_stderr_to_log()
    os.environ.setdefault("HF_HOME", str(hf_cache_dir()))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(hf_cache_dir()))

    is_first_run = not first_run_marker().exists()
    include_vlm = False

    # V14.6 — for first runs we still ask the user up-front via a
    # native dialog (it's a one-time decision: download VLM or skip).
    # But unlike before, we DON'T block on the actual download in the
    # foreground. Instead:
    #   1. Get the include-VLM choice via dialog.
    #   2. Start the HTTP server immediately.
    #   3. Open browser to /first_run for live progress.
    #   4. Spawn run_first_setup() on a background thread that pushes
    #      state into serve_demo._FIRST_RUN_STATE, which the browser
    #      polls. This makes the wait visible and gives the user a
    #      sense of what's happening + how long is left.
    if is_first_run:
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

    port = find_free_port()
    handle = ServerHandle(port)
    handle.start()

    if not wait_for_ready(port, timeout=30.0):
        osa_notify(APP_NAME, "服务器 30 秒内没就绪,请查看 Console.app")
        handle.stop()
        return 1

    if is_first_run:
        # Browser-side progress page — opens immediately, polls
        # /first_run_status, redirects to / when phase == "done".
        osa_notify(APP_NAME, f"开始首次设置 · 浏览器中查看进度 · {port}")
        webbrowser.open(f"http://127.0.0.1:{port}/first_run")

        # Spawn the actual download on a background thread. The
        # status_cb hits the in-process serve_demo state via the
        # ``first_run_set`` / ``first_run_append_error`` helpers —
        # those acquire the same lock /first_run_status reads from
        # so the browser sees consistent snapshots.
        def _setup_worker():
            try:
                import scripts.serve_demo as sd  # type: ignore

                def status_cb(_append_error=None, **fields):
                    if _append_error is not None:
                        sd.first_run_append_error(*_append_error)
                    if fields:
                        sd.first_run_set(**fields)

                run_first_setup(include_vlm, status_cb=status_cb)
            except Exception as exc:
                sys.stderr.write(
                    f"[setup] worker crashed: "
                    f"{type(exc).__name__}: {exc}\n"
                )
                # Best-effort: tell the page to give up so it stops
                # spinning forever.
                try:
                    import scripts.serve_demo as sd  # type: ignore
                    sd.first_run_set(
                        phase="done",
                        step_label=f"setup 异常: {type(exc).__name__}",
                    )
                except Exception:
                    pass

        threading.Thread(target=_setup_worker, daemon=True,
                          name="pixcull-first-run").start()
    else:
        osa_notify(APP_NAME, f"已启动 · 顶部菜单栏图标 · {port}")
        webbrowser.open(f"http://127.0.0.1:{port}/")

    # V13.0 — fire a background update check (debounced to once per
    # day inside the function). Doesn't block startup.
    def _update_worker():
        try:
            sys.path.insert(0, str(resource_root() / "app"))
            import updater  # type: ignore
            updater.background_check()
        except Exception as exc:
            # V14.0 — leave a trail; stderr is captured to the log file
            # by _redirect_stderr_to_log so this is recoverable later.
            sys.stderr.write(
                f"[launcher] update check failed silently: "
                f"{type(exc).__name__}: {exc}\n"
            )
    threading.Thread(target=_update_worker, daemon=True).start()

    # rumps owns the run loop from here. ^C in dev mode shuts everything
    # down via the quit handler.
    PixCullMenuApp(handle).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
