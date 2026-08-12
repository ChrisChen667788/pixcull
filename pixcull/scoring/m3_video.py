"""v2.52 — M3 watches the clip, so ranking stops being pure proxy.

``reel.py`` ranks candidates on ``mean_final + max_temporal``.  Both terms
come from per-frame photo scores and motion statistics, so a clip of the
vows and a clip of someone adjusting a mic score **identically** whenever
camera motion and face count happen to match.  There is no content signal
anywhere in the pipeline.  That is not a tuning problem; the information
was never collected.

M3 takes video natively, which is the one thing the local stack cannot
do at all — and unlike the photo path, there is no local measurement to
fuse here, because none of the temporal metrics answer "what is
happening".  They answer "how much is moving".

Two hard constraints shape this module:

**50 MB.**  A 1–3 s candidate is ~7.5 MB at 1080p/20 Mbps — fine — and
~187 MB at 4K ProRes, which is not.  Any shooter delivering ProRes or
high-bitrate RAW proxies trips the limit on every clip, so a transcode
gate is mandatory rather than defensive.

**The wire format is unverified.**  ``score_video`` refuses to guess
until ``pixcull m3 doctor --video`` has probed it, so this module reports
that as a skip with a reason rather than as a stream of nulls.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

#: Comfortably under M3's 50 MB so a transcode does not land on the line.
TARGET_CLIP_BYTES = 40 * 1024 * 1024

#: H.264 CRF for the fallback transcode. 23 is visually transparent
#: enough for a model that samples at 1 fps, and drops 4K ProRes by
#: roughly 40x.
TRANSCODE_CRF = 23

PROMPT = """\
你在帮摄影师从一段素材里挑出值得放进成片的片段。

看完这段视频后,只输出 JSON,不要任何其他文字:

{
  "happening": "这几秒里实际发生了什么,一句话,要具体",
  "keep_score": 0-100 的整数,这段进成片的价值,
  "moment_type": "vows|speech|first_dance|toast|entrance|candid|
                  reaction|scenery|setup|filler 之一",
  "has_speech": true/false,
  "reason": "给这个分数的理由,一句话"
}

评分标准:
- 90+ 只给不可替代的时刻(誓词、交换戒指、真情流露的反应)
- 60-89 给有内容的片段(致辞、跳舞、有互动的抓拍)
- 30-59 给能用但可替代的(空镜、走位、过渡)
- 30 以下给废片(整理设备、等待、镜头没对准)

注意:画面稳、人脸多,不等于这是重要时刻。有人在调麦克风,
也可以拍得很稳。请按**发生了什么**打分,不是按拍得稳不稳。
"""


class ClipTooLarge(RuntimeError):
    pass


@dataclass
class ClipVerdict:
    start_s: float
    end_s: float
    keep_score: float | None = None
    happening: str = ""
    moment_type: str = ""
    has_speech: bool = False
    reason: str = ""
    error: str | None = None
    skipped: str = ""      # why we did not even try

    def as_dict(self) -> dict[str, Any]:
        return {
            "m3_keep_score": self.keep_score,
            "m3_happening": self.happening,
            "m3_moment_type": self.moment_type,
            "m3_has_speech": self.has_speech,
            "m3_reason": self.reason,
            "m3_error": self.error or self.skipped or None,
        }


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH")
    return exe


def clip_to_tempfile(source: Path, start_s: float, end_s: float, *,
                     out_dir: Path | None = None,
                     max_bytes: int = TARGET_CLIP_BYTES) -> Path:
    """Cut ``[start_s, end_s)`` out of ``source`` as a standalone mp4.

    There was no such function: the trim logic lived inside
    ``assemble_reel``'s ``-filter_complex`` string, which produces a
    montage rather than a file per segment.

    Tries a stream copy first — free, and correct for most H.264
    deliverables — then re-encodes if the result is over ``max_bytes``.
    A 3 s 4K ProRes segment is ~187 MB and will always take the second
    path; without it every such shooter would get an exception per clip.
    """
    source = Path(source)
    if end_s <= start_s:
        raise ValueError(f"empty clip: {start_s}..{end_s}")
    out_dir = Path(out_dir or tempfile.mkdtemp(prefix="pixcull_m3clip_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{source.stem}_{start_s:.2f}-{end_s:.2f}".replace(".", "p")
    out = out_dir / f"{stem}.mp4"
    ff = _ffmpeg()
    base = [ff, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start_s:.3f}", "-t", f"{end_s - start_s:.3f}",
            "-i", str(source)]

    subprocess.run(base + ["-c", "copy", "-movflags", "+faststart",
                           str(out)],
                   check=True, capture_output=True, timeout=300)
    if out.exists() and out.stat().st_size <= max_bytes:
        return out

    subprocess.run(base + ["-c:v", "libx264", "-crf", str(TRANSCODE_CRF),
                           "-preset", "veryfast", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "96k",
                           "-movflags", "+faststart", str(out)],
                   check=True, capture_output=True, timeout=900)
    size = out.stat().st_size if out.exists() else 0
    if size > max_bytes:
        raise ClipTooLarge(
            f"{out.name} is {size / 1e6:.0f} MB after transcoding, over the "
            f"{max_bytes / 1e6:.0f} MB budget — shorten the window or lower "
            f"the resolution")
    return out


def _parse(raw: str, start_s: float, end_s: float) -> ClipVerdict:
    from pixcull.scoring.vlm_judge import parse_vlm_response

    v = ClipVerdict(start_s=start_s, end_s=end_s)
    d = parse_vlm_response(raw or "")
    if not isinstance(d, dict):
        v.error = "JSON parse failed"
        return v
    score = d.get("keep_score")
    try:
        if score is not None:
            v.keep_score = max(0.0, min(100.0, float(score)))
    except (TypeError, ValueError):
        v.keep_score = None
    v.happening = str(d.get("happening", ""))[:300]
    v.moment_type = str(d.get("moment_type", ""))[:40]
    v.has_speech = bool(d.get("has_speech"))
    v.reason = str(d.get("reason", ""))[:300]
    if v.keep_score is None and not v.happening:
        v.error = "no usable fields"
    return v


def score_clips(candidates: Sequence[dict], source_video: Path, judge: Any,
                *, out_dir: Path | None = None,
                fps: float = 1.0,
                max_clips: int | None = None) -> list[ClipVerdict]:
    """Judge each reel candidate on its actual content.

    Never raises.  A candidate that could not be cut, was too large, or
    came back malformed gets a :class:`ClipVerdict` carrying the reason —
    proxy-only ranking still works, and a partial content signal is worth
    more than an aborted run.
    """
    from pixcull.scoring.m3 import load_capabilities

    out: list[ClipVerdict] = []
    have_shape = bool(load_capabilities().get("video_part_shape"))
    todo = list(candidates)[:max_clips] if max_clips else list(candidates)

    for cand in todo:
        start = float(cand.get("start_s", 0.0))
        end = float(cand.get("end_s", 0.0))
        v = ClipVerdict(start_s=start, end_s=end)
        if not have_shape:
            # Named rather than silent: this whole feature being off is
            # one command away, and a stream of empty fields would look
            # like the model having no opinion.
            v.skipped = ("video input unverified on this machine — run "
                         "`pixcull m3 doctor --video <clip.mp4>` once")
            out.append(v)
            continue
        try:
            clip = clip_to_tempfile(Path(source_video), start, end,
                                    out_dir=out_dir)
        except Exception as exc:  # noqa: BLE001
            v.skipped = f"{type(exc).__name__}: {exc}"[:200]
            out.append(v)
            continue
        try:
            verdict = judge.score_video(clip, PROMPT, fps=fps)
        except Exception as exc:  # noqa: BLE001
            v.error = f"{type(exc).__name__}: {exc}"[:200]
            out.append(v)
            continue
        if getattr(verdict, "error", None):
            v.error = str(verdict.error)[:200]
            out.append(v)
            continue
        out.append(_parse(getattr(verdict, "raw_text", "") or "", start, end))
    return out


#: How much M3 is allowed to move a candidate.  Not 1.0: the proxy terms
#: still carry real information a content model has no access to — a
#: gorgeous moment shot through a shaking lens is still unusable, and
#: `mean_final` is the only thing that knows.
M3_WEIGHT = 0.6


def rerank(candidates: list[dict], verdicts: Sequence[ClipVerdict]) -> int:
    """Blend M3's content score into ``window_score_norm``.

    Returns how many candidates actually moved.  Candidates M3 could not
    judge keep their proxy score untouched, so a partial pass degrades
    smoothly to the v2.51 ordering rather than shuffling half the list
    against the other half.
    """
    moved = 0
    for cand, v in zip(candidates, verdicts):
        cand.update(v.as_dict())
        if v.keep_score is None:
            continue
        proxy = float(cand.get("window_score_norm") or 0.0)
        blended = (1 - M3_WEIGHT) * proxy + M3_WEIGHT * (v.keep_score / 100.0)
        if abs(blended - proxy) > 1e-9:
            moved += 1
        cand["window_score_norm_proxy"] = proxy
        cand["window_score_norm"] = blended
    candidates.sort(key=lambda c: -float(c.get("window_score_norm") or 0.0))
    return moved
