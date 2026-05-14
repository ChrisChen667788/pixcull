"""V17.5 — auto-generate per-vertical phrase pools from the user's
own reference samples + DeepSeek V4-Flash.

Why this exists
---------------
V17.3 hand-wrote ``VERTICAL_STRENGTH_TEMPLATES`` from photographic
intuition: "婚纱 should praise '高调干净光,皮肤通透'". This is fine
as a default but it's MY voice, not the user's. A landscape
photographer who shoots minimalist moody work doesn't want
"云海/星轨/极地大片质感" — they want "极简留白 / 单色调氛围".

V17.5 lets each user / vertical generate a phrase pool that
reflects THEIR aesthetic, by:

  1. Walking the vertical's good samples (V17.0 sample bank).
  2. Pulling the per-axis metric distribution (avg / max / min for
     subject_fraction, canon_lead_room, score_moment, laion_aes ...).
  3. Identifying which axes the user's good shots score highest on.
  4. Detecting common scene + style modes.
  5. Sending DeepSeek V4-Flash a structured prompt — "this user's
     <vertical> reference shots typically score high on <axes>, are
     <scene> + <style>; generate 3 short Chinese phrases per axis
     in business-vertical-specific language".
  6. Validating the JSON response, persisting under
     ``vertical_root(key)/phrase_override.json``.
  7. ``photo_advice._pick_per_axis`` reads the override file via
     ``load_phrase_override`` BEFORE consulting the hand-written
     ``VERTICAL_STRENGTH_TEMPLATES``.

Privacy
-------
We send DeepSeek METRIC SUMMARIES (numbers + scene/style tokens),
NEVER image bytes. Photographer's actual photos stay on their
machine. The prompt is small (<2 KB), the response is small
(<3 KB), and one generation costs ≈¥0.001.

Failure modes
-------------
* No DeepSeek key → raises ValueError ("set DEEPSEEK_API_KEY or
  configure via launcher menu"). Caller surfaces to UI as a 400.
* DeepSeek timeout / 5xx → raises with original error wrapped.
* Malformed JSON response → returns None for phrases, caller
  surfaces. We don't try to repair LLM output silently.
* Empty sample bank → ValueError with helpful "upload samples
  first" message.

Output schema (phrase_override.json)
------------------------------------
{
  "schema":          "pixcull.phrase_override.v1",
  "vertical":        "<key>",
  "generated_at":    <unix timestamp>,
  "n_samples_seen":  <int>,
  "scene_mode":      "<most-common scene>",
  "style_modes":     ["<top style>", ...],
  "axes": {
    "subject":     {"phrases": ["短句1", "短句2", "短句3"]},
    "composition": {"phrases": [...]},
    "light":       {"phrases": [...]},
    "moment":      {"phrases": [...]},
    "aesthetic":   {"phrases": [...]},
    "technical":   {"phrases": [...]}
  },
  "model": "deepseek-chat",
  "prompt_tokens": <int>, "completion_tokens": <int>
}
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pixcull import verticals as vmod


# ---------------------------------------------------------------------------
# Sample analysis — reuses the V17.4 SamplePoint shape but extends with
# more metrics (since we need richer signals for the LLM prompt).
# ---------------------------------------------------------------------------

# Metrics that we surface to the LLM. Picked to give it enough
# substrate to reason about *what kind of photo* the user prefers
# without needing pixel-level access.
_METRICS_OF_INTEREST = (
    "subject_fraction",
    "canon_lead_room",
    "canon_thirds_concentration",
    "canon_figure_ground",
    "canon_balance",
    "canon_symmetry",
    "canon_zone_clip_pct",
    "canon_midgray_offset",
    "score_moment",
    "score_exposure",
    "score_sharpness",
    "laion_aes",
    "clipiqa",
    "laplacian_subject",
    "face_count",
)


@dataclass
class SampleProfile:
    """Distribution snapshot used to brief the LLM."""
    n_samples:    int
    scenes:       dict[str, int]              # {scene: count}
    styles:       dict[str, int]
    metric_means: dict[str, float]
    metric_p90:   dict[str, float]
    high_axes:    list[str]                   # axes where good samples score 4★+
    sample_filenames: list[str] = field(default_factory=list)


def _profile_samples(key: str) -> SampleProfile:
    """Walk the vertical's GOOD samples, run analyze_one + fuse_score,
    aggregate per-metric distributions + per-axis star averages."""
    if vmod.get_vertical(key) is None:
        raise ValueError(f"unknown vertical: {key}")
    from pixcull.pipeline.worker import analyze_one
    from pixcull.scoring.fusion import fuse_score
    from pixcull.scoring.style_modes import detect_style_modes
    from pixcull.scoring.rubric_decompose import decompose_row
    from pixcull.config import PixCullConfig

    config = PixCullConfig.load()
    good_dir = vmod.vertical_root(key) / "good"
    files = [p for p in sorted(good_dir.iterdir())
             if p.is_file()]
    if not files:
        raise ValueError(
            f"vertical '{key}' has 0 good samples — upload reference "
            "shots first via /verticals"
        )

    scenes: Counter[str] = Counter()
    styles: Counter[str] = Counter()
    metric_vals: dict[str, list[float]] = {m: [] for m in _METRICS_OF_INTEREST}
    axis_stars: dict[str, list[float]] = {}

    for p in files:
        try:
            row = analyze_one(p)
        except Exception:
            continue
        if row is None:
            continue
        scene = str(row.get("scene") or "")
        flags = list(row.get("flags") or [])
        scenes[scene] += 1
        # Style detection
        try:
            sp = detect_style_modes(row)
            for s in sp.modes:
                styles[s] += 1
        except Exception:
            pass
        # Metric pulls
        for m in _METRICS_OF_INTEREST:
            v = row.get(m)
            try:
                fv = float(v)
                if fv != fv:  # NaN
                    continue
                metric_vals[m].append(fv)
            except (TypeError, ValueError):
                continue
        # Per-axis star estimates from the auto rubric. Need
        # fuse_score to populate the dims, then rubric_decompose
        # to get per-axis stars.
        try:
            dims = fuse_score(row, flags, scene, config)
            row_with_scores = {
                **row,
                "score_final":      dims["final"],
                "score_sharpness":  dims["sharpness"],
                "score_composition": dims["composition"],
                "score_exposure":   dims["exposure"],
                "score_aesthetic":  dims["aesthetic"],
            }
            # decompose_row returns RubricScore with axes={name: AxisScore}
            rs = decompose_row(row_with_scores)
            for axis_name, ax_score in rs.axes.items():
                if ax_score.stars is not None:
                    axis_stars.setdefault(axis_name, []).append(float(ax_score.stars))
        except Exception:
            continue

    if not metric_vals or all(not v for v in metric_vals.values()):
        raise ValueError(
            f"vertical '{key}' samples couldn't be analyzed — check "
            "the per-launch log for errors"
        )

    # high_axes = axes where ≥30% of samples score ≥4★
    high_axes = []
    for axis, stars_list in axis_stars.items():
        if not stars_list:
            continue
        share_high = sum(1 for s in stars_list if s >= 4.0) / len(stars_list)
        if share_high >= 0.30:
            high_axes.append(axis)

    def _mean(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 3) if xs else 0.0

    def _p90(xs: list[float]) -> float:
        if not xs:
            return 0.0
        srt = sorted(xs)
        idx = max(0, int(0.9 * (len(srt) - 1)))
        return round(srt[idx], 3)

    return SampleProfile(
        n_samples=len(files),
        scenes=dict(scenes),
        styles=dict(styles),
        metric_means={m: _mean(v) for m, v in metric_vals.items() if v},
        metric_p90={m: _p90(v) for m, v in metric_vals.items() if v},
        high_axes=sorted(high_axes),
        sample_filenames=[p.name for p in files[:5]],
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "你是为摄影评分系统生成专属点评话术的专家。"
    "用户上传了一批他们认为'好'的参考样片(某个具体业务垂类),"
    "你需要根据这些样片的统计特征,为该垂类生成 6 个评分轴的点评短语,"
    "替代系统默认的通用话术,让评分体感更贴合这个用户/这个垂类的审美。\n\n"
    "约束:\n"
    "- 每个轴 3 条短语,每条 ≤ 20 字,中文,业务向(用真摄影师讲的话术)\n"
    "- 不能用通用语,要带上垂类特征(婚纱/拍鸟/儿童/风光 等业务术语)\n"
    "- 句末不带句号,不带表情符号,不写'值得保留'之类的元评价\n"
    "- 只输出 JSON,不要解释\n"
)


def _build_prompt(vertical: vmod.Vertical, profile: SampleProfile) -> str:
    """Compact, structured prompt — DeepSeek V4-Flash gets ~1.5KB
    of context which is plenty for short-phrase generation."""
    top_scenes = sorted(profile.scenes.items(), key=lambda x: -x[1])[:3]
    top_styles = sorted(profile.styles.items(), key=lambda x: -x[1])[:3]
    return json.dumps({
        "task":       "为某垂类生成 6 个评分轴的专属点评短语",
        "vertical":   {
            "key":          vertical.key,
            "zh":           vertical.zh,
            "description":  vertical.description,
            "primary_axes": list(vertical.primary_axes),
        },
        "user_samples": {
            "n":            profile.n_samples,
            "common_scenes": [{"scene": s, "n": n} for s, n in top_scenes],
            "common_styles": [{"style": s, "n": n} for s, n in top_styles],
            "high_scoring_axes": profile.high_axes,
            "metric_means":  profile.metric_means,
            "metric_p90":    profile.metric_p90,
        },
        "output_schema": {
            "axes": {
                "subject":     {"phrases": ["...", "...", "..."]},
                "composition": {"phrases": ["...", "...", "..."]},
                "light":       {"phrases": ["...", "...", "..."]},
                "moment":      {"phrases": ["...", "...", "..."]},
                "aesthetic":   {"phrases": ["...", "...", "..."]},
                "technical":   {"phrases": ["...", "...", "..."]},
            }
        },
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# DeepSeek call + validation
# ---------------------------------------------------------------------------

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"   # V4-Flash, non-thinking
_REQUIRED_AXES = ("subject", "composition", "light", "moment",
                   "aesthetic", "technical")


def _call_deepseek(prompt: str, *, api_key: str | None = None,
                    model: str = DEFAULT_MODEL,
                    timeout_s: float = 30.0) -> tuple[str, dict]:
    """Returns (raw_content, usage_dict)."""
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise ValueError(
            "DeepSeek API key not configured — set DEEPSEEK_API_KEY "
            "env var or use the launcher menu '配置 DeepSeek API key'"
        )
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=1500,
        temperature=0.4,        # some creativity for phrase variation
        response_format={"type": "json_object"},
        timeout=timeout_s,
    )
    choice = resp.choices[0] if resp.choices else None
    content = (choice.message.content if choice else "") or ""
    usage = {}
    if resp.usage:
        usage = {
            "prompt_tokens":     getattr(resp.usage, "prompt_tokens", 0),
            "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
        }
    return content, usage


def _validate_phrases(payload: dict) -> dict[str, list[str]]:
    """Return {axis: [phrases]} sanitized + bounded; raise on broken shape.

    V17.17: accept BOTH shapes DeepSeek emits depending on its mood:
        {"axes": {"subject": {"phrases": [...]}, ...}}   (prompt-shape)
        {"axes": {"subject": [...], ...}}                (lazy-shape)
    Picking the right block: dict.get("phrases") if dict, else use as-is.
    """
    axes_raw = payload.get("axes")
    if not isinstance(axes_raw, dict):
        raise ValueError("LLM payload missing 'axes' object")
    out: dict[str, list[str]] = {}
    for axis in _REQUIRED_AXES:
        block = axes_raw.get(axis)
        # V17.17 — accept both {phrases: [...]} and bare [...]
        if isinstance(block, dict):
            phrases_raw = block.get("phrases")
        elif isinstance(block, list):
            phrases_raw = block
        else:
            continue
        if not isinstance(phrases_raw, list):
            continue
        cleaned: list[str] = []
        for p in phrases_raw[:5]:           # cap at 5 per axis
            if not isinstance(p, str):
                continue
            s = p.strip().strip("。.!").strip()
            if not s or len(s) > 30:        # reject very long lines
                continue
            cleaned.append(s)
        if cleaned:
            out[axis] = cleaned[:3]         # use top 3
    if not out:
        raise ValueError("LLM produced no valid phrases for any axis")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class GenerateResult:
    vertical:        str
    n_samples_seen:  int
    scene_mode:      str
    style_modes:     list[str]
    high_axes:       list[str]
    axes:            dict[str, list[str]]
    model:           str
    prompt_tokens:   int
    completion_tokens: int
    elapsed_s:       float
    timestamp:       float = field(default_factory=time.time)


def phrase_override_path(key: str) -> Path:
    return vmod.vertical_root(key) / "phrase_override.json"


def load_phrase_override(key: str) -> dict | None:
    p = phrase_override_path(key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_phrase_override(key: str, result: GenerateResult) -> None:
    payload = {
        "schema":           "pixcull.phrase_override.v1",
        "vertical":         key,
        "generated_at":     result.timestamp,
        "n_samples_seen":   result.n_samples_seen,
        "scene_mode":       result.scene_mode,
        "style_modes":      result.style_modes,
        "high_axes":        result.high_axes,
        "axes":             {a: {"phrases": ph}
                              for a, ph in result.axes.items()},
        "model":            result.model,
        "prompt_tokens":    result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }
    phrase_override_path(key).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def delete_phrase_override(key: str) -> bool:
    p = phrase_override_path(key)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


def generate_phrases(key: str, *, api_key: str | None = None,
                      model: str = DEFAULT_MODEL) -> GenerateResult:
    """End-to-end: profile samples → DeepSeek → validate → return.

    Caller should ``save_phrase_override`` to persist + immediately
    activate the override.
    """
    v = vmod.get_vertical(key)
    if v is None:
        raise ValueError(f"unknown vertical: {key}")
    t0 = time.time()
    profile = _profile_samples(key)
    prompt = _build_prompt(v, profile)
    raw, usage = _call_deepseek(prompt, api_key=api_key, model=model)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned non-JSON ({exc}) — try again or report the bug"
        ) from exc
    axes = _validate_phrases(payload)

    top_scene = ""
    if profile.scenes:
        top_scene = max(profile.scenes.items(), key=lambda x: x[1])[0]
    top_styles = sorted(profile.styles.items(),
                          key=lambda x: -x[1])[:3]

    return GenerateResult(
        vertical=key,
        n_samples_seen=profile.n_samples,
        scene_mode=top_scene,
        style_modes=[s for s, _ in top_styles],
        high_axes=profile.high_axes,
        axes=axes,
        model=model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        elapsed_s=round(time.time() - t0, 2),
    )


__all__ = [
    "GenerateResult",
    "SampleProfile",
    "_REQUIRED_AXES",
    "_validate_phrases",
    "_profile_samples",
    "_build_prompt",
    "phrase_override_path",
    "load_phrase_override",
    "save_phrase_override",
    "delete_phrase_override",
    "generate_phrases",
]
