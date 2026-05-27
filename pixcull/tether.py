"""P2.2 — Lightroom / Capture One tether integration via folder watch.

Pro shoots use tethered capture: camera → USB → Lr/C1 → photo lands
in a "tether destination" folder. Pre-P2.2 the photographer had to
finish the shoot, then explicitly trigger a PixCull scan on the
folder. P2.2 makes culling LIVE: a watcher process polls the tether
folder, runs analyze_one on each new image within 1-2 sec of capture,
and POSTs the decision back so the photographer's iPad / phone /
second display shows real-time keep/cull verdicts as they shoot.

Design choices
==============
* Polling, not OS-level FS events. ``watchdog`` is the canonical
  cross-platform FS-events library but ships its own C extension
  + threading model that's been a frequent breakage source (the
  V18.1 numpy regression playbook all over again). Polling at
  1-second granularity is plenty fast for tether scenarios — a
  pro DSLR shoots 10-20 fps in burst, but the tether transfer +
  Lr/C1 catalog import takes 1-3 sec end-to-end, so by the time
  a new file lands in the tether folder it's been at least 1 sec.
* Single-folder watch per tether session. The user invokes
  ``scripts/pixcull_tether.py <folder>`` (or POST /tether/start)
  and the watcher exits when they Ctrl-C / POST /tether/stop.
  No daemon, no persistence, no surprises.
* Analyze through the existing scan path. Each new file is run
  through ``analyze_one`` + ``fuse_score`` + ``decide`` (same
  pipeline as a regular /scan_local) but emits results to a
  ``tether-live`` virtual run so the iOS / browser UI can show
  the live feed.

Output: a regular PixCull run dir under ``/tmp/pixcull_demo/
tether_<session_id>/`` that the existing /results / /api/v1/runs
endpoints can serve. iOS V0.2's PhotoGridView refreshes when
new rows land via its existing polling.

Per-frame cost — at V21's ~1.35s analyze on M1 Max, the watcher
can keep up with a 30fps-burst as long as the camera writes to
the tether folder no faster than ~1 every 1.5s. For faster
shoots (high-fps wildlife) we'd need parallel analyze (V21 path
already supports it via PIXCULL_WORKERS env var).
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable


# Polling interval. 1 second is the right balance between latency
# (lightroom catalog ~3 sec; our analyze ~1.5 sec; user-visible
# end-to-end ~5 sec) and CPU (idle poll = effectively free).
_POLL_INTERVAL_S = 1.0

# Track active tether sessions globally so the HTTP API can list /
# stop them. Each entry: {session_id: TetherSession}.
_ACTIVE_SESSIONS: dict[str, "TetherSession"] = {}
_SESSIONS_LOCK = threading.Lock()


class TetherSession:
    """One folder-watch session. Polls a folder for new image files,
    analyzes each one, and pushes results to a per-session run dir.

    Lifecycle:
      * ``start()`` — spawn the watcher thread
      * ``stop()`` — signal stop + join (clean shutdown)
      * ``status()`` — non-blocking snapshot for the API
    """

    def __init__(self, folder: Path, session_id: str | None = None,
                   vertical: str | None = None):
        self.folder = Path(folder).expanduser().resolve()
        if not self.folder.is_dir():
            raise ValueError(f"not a folder: {self.folder}")
        self.session_id = session_id or f"tether_{uuid.uuid4().hex[:10]}"
        self.vertical = vertical
        self.run_id = self.session_id

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: set[Path] = set()
        # Snapshot existing files at start so we don't analyze the
        # photographer's entire pre-existing tether catalog.
        # Only NEW files (created after session start) trigger
        # analyze.
        for p in self._iter_images():
            self._seen.add(p)
        self.started_at = time.time()
        self.n_analyzed = 0
        self.n_failed = 0
        self.last_filename: str | None = None
        self.last_decision: str | None = None
        self.last_at: float | None = None

    def _iter_images(self):
        from pixcull.io.formats import ALL_EXTS
        if not self.folder.exists():
            return
        for p in self.folder.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in ALL_EXTS:
                continue
            if p.name.startswith("."):
                continue
            yield p

    def _output_dir(self) -> Path:
        """Per-session run dir under the standard /tmp/pixcull_demo/
        tree so existing /results endpoints serve it without a new
        route."""
        d = Path("/tmp/pixcull_demo") / self.run_id / "output"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _analyze_one_file(self, path: Path) -> dict | None:
        """Pipeline-aligned analyze of one file. Mirrors what
        scan_multi.py does per-image, plus appends to the session's
        scores.csv so the /results UI sees rows as they land."""
        from pixcull.pipeline.worker import analyze_one
        from pixcull.scoring.fusion import fuse_score
        from pixcull.scoring.decision import decide
        from pixcull.config import PixCullConfig

        try:
            row = analyze_one(path)
            if row is None:
                return None
            config = PixCullConfig.load()
            scene = str(row.get("scene") or "")
            flags = list(row.get("flags") or [])
            dims = fuse_score(row, flags, scene, config)
            dec, reasons = decide(
                dims["final"], flags, config,
                scene=scene, vertical=self.vertical,
            )
            return {
                "filename":    path.name,
                "path":        str(path),
                "scene":       scene,
                "flags":       flags,
                "decision":    dec.value,
                "score_final": float(dims["final"]),
                "reason":      "; ".join(reasons),
            }
        except Exception as exc:  # noqa: BLE001
            print(f"[tether] analyze failed {path.name}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return None

    def _append_row(self, result: dict) -> None:
        """Append one analyzed row to scores.csv. The header is
        written on first call so the file is self-describing for
        any tool reading it mid-session.

        v0.10-P1-2 — also extends the schema with mtime + sharpness
        + is_burst_peak so the streaming peak picker (below) can
        re-evaluate the trailing-window's burst flags on every
        new arrival.
        """
        import csv
        scores_path = self._output_dir() / "scores.csv"
        is_new = not scores_path.exists()
        # v0.10-P1-2 — header now carries the streaming-burst fields.
        cols = ["filename", "path", "scene", "decision",
                "score_final", "flags", "reason",
                "mtime", "sharpness", "is_burst_peak"]
        # Persist as a single-line CSV row (flags joined w/ "|")
        flat = dict(result)
        flat["flags"] = "|".join(result.get("flags") or [])
        # Default the new columns when the analyzer didn't fill them.
        flat.setdefault("mtime",         time.time())
        flat.setdefault("sharpness",     "")
        flat.setdefault("is_burst_peak", False)
        with scores_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            if is_new:
                w.writeheader()
            w.writerow({c: flat.get(c, "") for c in cols})
        # v0.10-P1-2 — re-evaluate burst peaks across the trailing
        # window every time a new row lands.  This is the streaming
        # equivalent of the offline peak-picker; the photographer's
        # 🏆 badge will now transfer to the newer winning frame
        # within ~1 s of the file landing on disk.
        try:
            self._restream_burst_peaks(scores_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[tether] burst restream failed: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)

    def _restream_burst_peaks(self, scores_path: Path) -> None:
        """v0.10-P1-2 — re-rank burst peaks across the trailing
        window of scores.csv after a new row was appended.

        Only the last WINDOW_SIZE rows are touched; older bursts
        are frozen (their peak doesn't change retroactively).  We
        rewrite the trailing window slice in place — the file is
        small enough (a few MB even for a 5k-photo wedding) that
        an O(window) rewrite per arrival is fine.
        """
        import csv
        from pixcull.tether_stream import update_burst_peaks, WINDOW_SIZE

        if not scores_path.exists():
            return
        with scores_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)
            fieldnames = reader.fieldnames or []
        if not all_rows:
            return
        # Slice the trailing window, re-rank, splice back.
        head = all_rows[:-WINDOW_SIZE]
        tail = all_rows[-WINDOW_SIZE:]
        # Coerce mtime to float so the streamer's comparisons work
        # — DictReader returns everything as strings.
        for r in tail:
            try:
                r["_mtime_float"] = float(r.get("mtime") or 0.0)
            except (TypeError, ValueError):
                r["_mtime_float"] = 0.0
            r["mtime"] = r["_mtime_float"]   # update_burst_peaks reads this
        retoured = update_burst_peaks(tail)
        # Stitch + write back.  Drop the _mtime_float helper.
        for r in retoured:
            r.pop("_mtime_float", None)
            r["mtime"] = str(r.get("mtime") or "")
            r["is_burst_peak"] = "True" if r.get("is_burst_peak") else "False"
        for r in head:
            r.pop("_mtime_float", None)
        with scores_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in head:
                writer.writerow({c: r.get(c, "") for c in fieldnames})
            for r in retoured:
                writer.writerow({c: r.get(c, "") for c in fieldnames})

    def _write_manifest(self) -> None:
        """Marker file so ``_reload_run_from_disk`` recognizes the
        session as a real run on first /results request."""
        m = self._output_dir().parent / "manifest.json"
        if m.exists():
            return
        m.write_text(json.dumps({
            "schema":     "pixcull.tether.session.v1",
            "run_id":     self.run_id,
            "mode":       "tether",
            "folder":     str(self.folder),
            "vertical":   self.vertical,
            "started_at": self.started_at,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run(self) -> None:
        self._write_manifest()
        while not self._stop.is_set():
            try:
                current = set(self._iter_images())
                new_files = current - self._seen
                # Sort by mtime so we analyze in capture order
                # (matters for burst reviews where the first frame
                # of a burst should land first).
                new_files = sorted(new_files,
                                     key=lambda p: p.stat().st_mtime)
                for p in new_files:
                    if self._stop.is_set():
                        break
                    # Skip files still being written (mtime within
                    # the last 200 ms — likely mid-copy). Re-poll
                    # on the next interval.
                    if time.time() - p.stat().st_mtime < 0.2:
                        continue
                    result = self._analyze_one_file(p)
                    self._seen.add(p)
                    if result is None:
                        self.n_failed += 1
                        continue
                    self._append_row(result)
                    self.n_analyzed += 1
                    self.last_filename = result["filename"]
                    self.last_decision = result["decision"]
                    self.last_at = time.time()
                    print(f"[tether] {self.session_id} {p.name}: "
                          f"{result['decision']} "
                          f"(score {result['score_final']:.2f})",
                          file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"[tether] poll loop error: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
            self._stop.wait(_POLL_INTERVAL_S)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run,
                                          name=f"tether-{self.session_id}",
                                          daemon=True)
        self._thread.start()
        with _SESSIONS_LOCK:
            _ACTIVE_SESSIONS[self.session_id] = self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        with _SESSIONS_LOCK:
            _ACTIVE_SESSIONS.pop(self.session_id, None)

    def status(self) -> dict:
        return {
            "session_id":   self.session_id,
            "run_id":       self.run_id,
            "folder":       str(self.folder),
            "vertical":     self.vertical,
            "running":      self._thread is not None and self._thread.is_alive(),
            "started_at":   self.started_at,
            "elapsed_s":    time.time() - self.started_at,
            "n_analyzed":   self.n_analyzed,
            "n_failed":     self.n_failed,
            "last":         {
                "filename": self.last_filename,
                "decision": self.last_decision,
                "at":       self.last_at,
            },
        }


def start_session(folder: Path,
                     vertical: str | None = None,
                     session_id: str | None = None) -> TetherSession:
    """Start a new tether-watch session. Returns the session object;
    caller can read ``.status()`` and call ``.stop()`` to end it.
    """
    session = TetherSession(folder, session_id=session_id,
                              vertical=vertical)
    session.start()
    return session


def list_sessions() -> list[dict]:
    with _SESSIONS_LOCK:
        return [s.status() for s in _ACTIVE_SESSIONS.values()]


def get_session(session_id: str) -> TetherSession | None:
    with _SESSIONS_LOCK:
        return _ACTIVE_SESSIONS.get(session_id)


def stop_session(session_id: str) -> bool:
    s = get_session(session_id)
    if s is None:
        return False
    s.stop()
    return True


__all__ = [
    "TetherSession",
    "start_session",
    "stop_session",
    "list_sessions",
    "get_session",
]
