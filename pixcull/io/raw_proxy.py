"""v2.1-P2-1 — RAW-video proxy bridge.

Charter ``docs/ROADMAP-v2.1-charter.md`` § v2.1-P2-1.  Native RAW-video
decode (Blackmagic ``.braw``, Canon ``.crm``, RED ``.r3d``, ARRI
``.ari``, DJI RAW-DNG sequences) needs a vendor SDK PixCull can't ship.
This bridges the gap: **detect** a RAW source, hand back a guided
transcode-to-ProRes recipe, and **invoke** a vendor transcoder if the
user has one configured (``PIXCULL_RAW_TRANSCODER``) — so they stay in
one flow.  ffmpeg-decodable sources just get a ProRes proxy directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from pixcull.io.video import FFmpegError, probe_video

# Container extensions that need a vendor SDK / NLE transcode first.
RAW_PROXY_EXTS: set[str] = {".braw", ".crm", ".dng", ".r3d", ".ari", ".arx"}

_VENDOR_HINT = {
    ".braw": "Blackmagic RAW — export ProRes from DaVinci Resolve or use "
             "the BRAW SDK / blackmagic-raw-player.",
    ".crm": "Canon Cinema RAW Light — transcode in Canon EOS VR Utility / "
            "Cinema RAW Development, or DaVinci Resolve.",
    ".dng": "CinemaDNG / DJI RAW frame sequence — assemble to ProRes in "
            "Resolve (it's a still-image sequence, not one video stream).",
    ".r3d": "RED R3D — REDCINE-X PRO or Resolve.",
    ".ari": "ARRI RAW — ARRIRAW Converter or Resolve.",
}


def needs_proxy(path_or_ext: str | Path) -> bool:
    """True when the source is a RAW container that needs transcoding."""
    s = str(path_or_ext)
    ext = s if s.startswith(".") else Path(s).suffix
    return ext.lower() in RAW_PROXY_EXTS


@dataclass
class ProxyRecipe:
    source: str
    ext: str
    needs_transcode: bool
    advice: str
    suggested_cmd: str

    def to_dict(self) -> dict:
        return asdict(self)


def raw_proxy_recipe(path: Path) -> ProxyRecipe:
    """A human recipe for getting ``path`` into a PixCull-readable proxy."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in RAW_PROXY_EXTS:
        hint = _VENDOR_HINT.get(ext, "Transcode to ProRes in your NLE.")
        out = path.with_suffix(".proxy.mov").name
        return ProxyRecipe(
            source=str(path), ext=ext, needs_transcode=True,
            advice=(f"{ext} is RAW video — PixCull can't decode it without a "
                    f"vendor SDK. {hint} Then run `pixcull video {out}`. "
                    "Set PIXCULL_RAW_TRANSCODER=<tool> to auto-invoke a "
                    "transcoder (called as `<tool> <in> <out>`)."),
            suggested_cmd=f"<your-transcoder> {path.name} {out}")
    # ffmpeg-decodable → a direct ProRes proxy keeps the edit lighter.
    out = path.with_suffix(".proxy.mov").name
    return ProxyRecipe(
        source=str(path), ext=ext, needs_transcode=False,
        advice="ffmpeg-decodable — PixCull can read it directly; a ProRes "
               "proxy is optional (smaller, faster scrubbing).",
        suggested_cmd=(f"ffmpeg -i {path.name} -c:v prores_ks -profile:v 0 "
                       f"-c:a copy {out}"))


def make_proxy(
    path: Path,
    out_dir: Path,
    *,
    transcoder: str | None = None,
    ffmpeg: str | None = None,
) -> Path:
    """Produce a ProRes proxy for ``path`` under ``out_dir``.

    * ffmpeg-decodable source → transcode to ProRes 422-proxy via ffmpeg.
    * RAW source → invoke ``PIXCULL_RAW_TRANSCODER`` (or ``transcoder``)
      as ``<tool> <in> <out>`` if configured; otherwise raise
      :class:`FFmpegError` carrying the guided recipe.
    """
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (path.stem + ".proxy.mov")
    recipe = raw_proxy_recipe(path)

    if recipe.needs_transcode:
        tool = transcoder or os.environ.get("PIXCULL_RAW_TRANSCODER", "")
        tool_bin = shutil.which(tool) or (tool if tool and Path(tool).exists()
                                          else "")
        if not tool_bin:
            raise FFmpegError(recipe.advice)
        try:
            proc = subprocess.run([tool_bin, str(path), str(out)],
                                  capture_output=True, text=True, timeout=3600)
        except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
            raise FFmpegError(f"RAW transcoder failed: {exc}")
        if proc.returncode != 0 or not out.exists():
            raise FFmpegError(
                f"RAW transcoder returned {proc.returncode}: "
                f"{proc.stderr.strip()[:300]}")
        return out

    # ffmpeg-decodable → ProRes proxy.
    probe_video(path, ffprobe=None)            # validates it's readable
    ffmpeg_bin = shutil.which(ffmpeg or "ffmpeg") or ffmpeg
    if not ffmpeg_bin:
        raise FFmpegError("ffmpeg not found on PATH")
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(path), "-c:v", "prores_ks", "-profile:v", "0",
           "-c:a", "aac", str(out)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        raise FFmpegError(f"ffmpeg proxy transcode failed: {exc}")
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffmpeg returned {proc.returncode}: {proc.stderr.strip()[:300]}")
    return out
