"""V3.1 Meta-judge: text-only LLM consolidates all upstream signals.

DeepSeek V4-Pro (and other strong text models) don't accept image input
yet. But they are extraordinarily good at structured reasoning over
mixed signals — exactly what a "consolidate all the rubric votes into
one final answer" task needs. This module is the "judge of judges"
stage that runs after the vision VLM.

Architecture:

    ┌──────── pipeline runs ────────┐
    │                               │
    │  detectors → flags + scores   │
    │  rule fuse  → score_final     │
    │  rule decide → keep/maybe/cull│
    │  V2.0 rubric_decompose → axes │
    │  V2.1 axis_rescorer    → axes │
    │  V3.0 vlm_judge        → axes │ ← sees pixels (Qwen3-VL local)
    │                               │
    └───────────────┬───────────────┘
                    │
                    ▼
        ┌─── meta_judge (V3.1) ───┐
        │  DeepSeek V4-Pro       │ ← text-only, sees STRUCTURED packet
        │  reads all the above   │   (no image bytes)
        │  produces:             │
        │   - final 6 axis stars │
        │   - cross-check flags  │
        │   - polished rationale │
        │   - confidence         │
        └─────────────────────────┘

Why this beats running VLM directly
====================================
1. **Calibration.** Local 4B VLM has known biases (overrates if scene
   is "nice", underrates if face missing). The meta judge sees BOTH
   the VLM verdict AND the underlying signals (laion_aes / clipiqa /
   composition_score) and can sanity-check. ("VLM says 5★ aesthetic
   but laion_aes is 3.2 — flag as inconsistent.")

2. **Better rationale.** Qwen3-VL-4B writes mediocre Chinese; V4-Pro
   writes editorial-quality Chinese. The meta judge inherits this.

3. **Costs nearly nothing.** Input is ~1.5K tokens of structured data,
   output ~500 tokens. At V4-Pro 60%-off pricing (¥0.75/M in, ¥1.5/M
   out), that's ~¥0.002 per image. 100-image batch ≈ ¥0.2.

4. **Independent evidence chain.** The meta judge can disagree with
   the VLM. When they disagree on a high-stakes axis, that's a strong
   signal to surface the image for human review (active learning).

Failure modes
=============
* No API key → returns None per row, pipeline runs as if meta-judge off.
* API timeout / rate limit → that row's verdict is None, batch continues.
* Malformed JSON → caught by parse_vlm_response (shared with vlm_judge).

The interface is identical to ``vlm_judge.score`` so the orchestrator
can swap in the meta judge without restructuring its loop.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.vlm_judge import (
    VlmAxisScore,
    VlmVerdict,
    parse_vlm_response,
)


DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"  # non-thinking, fast, cheap
PRO_DEEPSEEK_MODEL = "deepseek-v4-pro"        # thinking-mode; needs ≥1500 tokens
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


# ---------------------------------------------------------------------------
# Prompt: send a structured JSON packet of all upstream signals + ask the
# meta-judge to consolidate. We keep the schema flat and small — V4-Pro is
# strong at JSON-mode; no need for chain-of-thought prompting tricks.
# ---------------------------------------------------------------------------

def build_meta_prompt(packet: dict[str, Any]) -> str:
    """Render the per-image signal packet as the user-turn prompt.

    V5.0 update: prepends the photography canon so the meta-judge
    explicitly cross-checks each upstream verdict against canonical
    standards (Zone System exposure, Rule of Thirds, Cartier-Bresson
    moment, etc.). Inconsistencies are now graded by canon-citation
    quality — a "VLM gave aesthetic 5★ but the image has Zone IX
    clipping" is a stronger flag than just "scores diverge".

    Packet shape (everything optional; we fill what we have):
      filename: str
      scene: str
      flags: list[str]
      decision_rule: str   ('keep'|'maybe'|'cull')
      score_final: float   (0..1)
      detector_metrics: dict   (laion_aes, clipiqa, laplacian_*, etc.)
      rubric_auto: dict[axis_name, stars]
      rubric_model: dict[axis_name, stars]
      vlm_verdict: dict (full output of upstream VLM, may be None)
    """
    from pixcull.scoring.photography_canon import build_canon_section_zh
    axes_lines = "\n".join(
        f'  - {a.name}: {_axis_brief(a.name)}'
        for a in RUBRIC_AXES
    )
    canon = build_canon_section_zh()
    return f"""你是资深摄影编辑,需要基于多个评分系统的结果给出最终判断。

{canon}

下方是同一张照片的所有可用信号(JSON):

```json
{json.dumps(packet, ensure_ascii=False, indent=2)}
```

任务:综合上述信号,产出最终的 6 轴评分 + 一致性检查 + 简短理由。

6 轴说明:
{axes_lines}

★ 含义: 1=废片  2=问题明显  3=合格平庸  4=优秀  5=顶级

注意事项:
- 当 vlm_verdict、rubric_auto、rubric_model 之间分歧大时,**优先信任与 detector_metrics 一致的那个**(laion_aes 高 ↔ aesthetic 高;laplacian 高 ↔ technical 高)。
- 当所有信号都低分时,大胆给 1-2★ 不要平均化。
- 当 flags 含 closed_eyes / motion_blur_on_face 等致命瑕疵时,subject 或 moment 应 ≤ 2★。
- 在 inconsistencies 数组中列出你发现的可疑分歧(可以为空)。
- rationale 必须基于上面 packet 中实际可见的数据,不要编造。

只返回 JSON,不要任何额外文字:

{{
  "axes": {{
    "technical":   {{"stars": <1-5>, "rationale": "<基于 packet 的判断>"}},
    "subject":     {{"stars": <1-5>, "rationale": "<...>"}},
    "composition": {{"stars": <1-5>, "rationale": "<...>"}},
    "light":       {{"stars": <1-5>, "rationale": "<...>"}},
    "moment":      {{"stars": <1-5>, "rationale": "<...>"}},
    "aesthetic":   {{"stars": <1-5>, "rationale": "<...>"}}
  }},
  "overall_label": "<keep|maybe|cull>",
  "overall_rationale": "<一句话总结这张图的去留判断>",
  "inconsistencies": ["<可疑分歧 1>", "<...>"],
  "confidence": <0.0-1.0>
}}"""


_AXIS_BRIEF = {
    "technical":   "对焦/曝光/锐度/噪点 — 技术层面",
    "subject":     "主体清晰、姿态/表情",
    "composition": "构图、平衡、引导线",
    "light":       "光质/方向/色温/对比",
    "moment":      "时机/动作峰值/情绪",
    "aesthetic":   "整体艺术感/色彩/记忆点",
}


def _axis_brief(name: str) -> str:
    return _AXIS_BRIEF.get(name, "")


# ---------------------------------------------------------------------------
# Result type — extends VlmVerdict with consolidation-specific fields.
# ---------------------------------------------------------------------------

@dataclass
class MetaVerdict(VlmVerdict):
    """A meta-judge consolidation. Inherits VlmVerdict's per-axis fields
    so downstream code that iterates ``verdict.axes`` doesn't care
    whether it came from a VLM or a meta-judge.
    """
    inconsistencies: list[str] | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["inconsistencies"] = self.inconsistencies or []
        d["confidence"] = self.confidence
        return d


# ---------------------------------------------------------------------------
# DeepSeek meta-judge
# ---------------------------------------------------------------------------

class DeepseekMetaJudge:
    """V4-Pro-backed meta judge. Text-only.

    Reuses the OpenAI Python client (DeepSeek is OpenAI-compat). Model is
    constructor-overridable so we can switch to V4-Flash for speed/cost
    when production calls for it.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        timeout_s: float = 60.0,
    ):
        api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise ValueError(
                "DeepseekMetaJudge needs an api_key (or DEEPSEEK_API_KEY env)"
            )
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        self._model = model
        self._timeout = timeout_s
        self.model_name = f"deepseek:{model}"

    def consolidate(
        self,
        packet: dict[str, Any],
        max_tokens: int | None = None,
    ) -> MetaVerdict:
        """Run V4-Flash (or other model) on a per-image signal packet.

        ``max_tokens`` defaults sized to the model: V4-Flash (non-thinking)
        gets 800; V4-Pro (thinking) gets 4000 because the budget is split
        between hidden reasoning and visible content. Empty content with
        ``finish_reason='length'`` means the budget was eaten by reasoning
        — bumping max_tokens fixes it.
        """
        if max_tokens is None:
            # V4-Flash output for our 6-axis schema averages ~700 tokens
            # (Chinese rationales × 6 + overall + 2-3 inconsistencies).
            # 1500 leaves headroom; cost is ~¥0.003 per call.
            # V4-Pro burns 60-80% of budget on hidden reasoning, so it
            # needs ~4× the visible-output budget to land the JSON.
            max_tokens = 5000 if self._model == PRO_DEEPSEEK_MODEL else 1500
        verdict = MetaVerdict(
            filename=str(packet.get("filename", "")),
            axes={a.name: VlmAxisScore(stars=None) for a in RUBRIC_AXES},
            model_name=self.model_name,
        )
        t0 = time.time()
        try:
            # V4-Pro defaults to thinking mode which empties the
            # `content` field and returns reasoning in `reasoning_content`.
            # For structured-output tasks we want non-thinking mode (the
            # docs say the legacy `deepseek-chat` maps to V4-Flash
            # non-thinking; V4-Pro likely supports the same toggle via
            # response_format=json_object which forces final-answer mode).
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": build_meta_prompt(packet)}],
                    max_tokens=max_tokens,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    timeout=self._timeout,
                )
            except Exception:
                # Fallback without response_format (some endpoints reject)
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": build_meta_prompt(packet)}],
                    max_tokens=max_tokens,
                    temperature=0.1,
                    timeout=self._timeout,
                )
            text = resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            verdict.elapsed_s = time.time() - t0
            verdict.error = f"{type(exc).__name__}: {exc}"
            return verdict
        verdict.elapsed_s = time.time() - t0
        verdict.raw_text = text

        parsed = parse_vlm_response(text)
        if parsed is None:
            verdict.error = "JSON parse failed"
            return verdict

        for axis_name in verdict.axes.keys():
            ax = (parsed.get("axes") or {}).get(axis_name) or {}
            stars = ax.get("stars")
            try:
                if stars is not None:
                    stars = max(1.0, min(5.0, float(stars)))
            except (TypeError, ValueError):
                stars = None
            verdict.axes[axis_name] = VlmAxisScore(
                stars=stars,
                rationale=str(ax.get("rationale", ""))[:300],
            )
        verdict.overall_label = str(parsed.get("overall_label", "")).lower()
        verdict.overall_rationale = str(parsed.get("overall_rationale", ""))[:300]
        inc = parsed.get("inconsistencies") or []
        verdict.inconsistencies = [str(x)[:200] for x in inc if x][:10]
        try:
            conf = parsed.get("confidence")
            verdict.confidence = max(0.0, min(1.0, float(conf))) if conf is not None else None
        except (TypeError, ValueError):
            verdict.confidence = None
        return verdict


# ---------------------------------------------------------------------------
# Packet builder — gathers all signals from a pipeline row dict + (optional)
# upstream VLM verdict. Kept as a module function so the orchestrator can
# reuse it without instantiating the judge.
# ---------------------------------------------------------------------------

def build_packet(row: dict[str, Any],
                 vlm_verdict: VlmVerdict | None) -> dict[str, Any]:
    """V8.0: detected style modes are added to the packet so the meta
    judge knows when to relax canon-of-generic rules in favor of
    canon-of-this-style. See pixcull.scoring.style_modes."""
    """Project a pipeline row + optional VLM verdict into a JSON-friendly
    packet for the meta judge.

    Strips numpy / pandas types (the JSON encoder chokes on np.float64).
    Drops huge fields like embeddings (the meta judge can't use them).
    """
    def f(v: Any) -> Any:
        if v is None:
            return None
        try:
            x = float(v)
            if x != x:  # NaN
                return None
            return round(x, 4)
        except (TypeError, ValueError):
            try:
                return str(v)
            except Exception:
                return None

    flags = row.get("flags") or ""
    if isinstance(flags, str):
        flags = [s.strip() for s in flags.split(",") if s.strip()]

    detector_metrics = {
        k: f(row.get(k))
        for k in (
            "laplacian_global", "laplacian_subject", "face_region_lap_var",
            "mean_luma", "highlight_clip_pct", "shadow_clip_pct",
            "laion_aes", "clipiqa",
            "scene_confidence", "horizon_tilt_deg", "rule_of_thirds_offset",
            "composition_score", "subject_fraction",
            "face_count", "face_max_blink", "face_min_ear",
        )
        if row.get(k) is not None
    }
    rubric_auto = {
        a.name: f(row.get(f"rubric_{a.name}_stars"))
        for a in RUBRIC_AXES
    }
    rubric_model = {
        a.name: f(row.get(f"model_{a.name}_stars"))
        for a in RUBRIC_AXES
    }

    packet: dict[str, Any] = {
        "filename": str(row.get("filename", "")),
        "scene": str(row.get("scene", "") or ""),
        "decision_rule": str(row.get("decision", "") or ""),
        "score_final": f(row.get("score_final")),
        "flags": flags,
        "detector_metrics": detector_metrics,
        "rubric_auto": rubric_auto,
        "rubric_model": rubric_model,
    }
    if vlm_verdict is not None:
        packet["vlm_verdict"] = {
            "axes": {
                k: {"stars": v.stars, "rationale": v.rationale[:200]}
                for k, v in vlm_verdict.axes.items()
            },
            "overall_label": vlm_verdict.overall_label,
            "overall_rationale": vlm_verdict.overall_rationale[:200],
            "model": vlm_verdict.model_name,
        }
    # V8.0: style modes drive how aggressively to honor classical
    # canon vs. style-of-style canon.
    from pixcull.scoring.style_modes import detect_style_modes
    profile = detect_style_modes(row)
    if profile.modes:
        packet["detected_style_modes"] = sorted(profile.modes)
        packet["style_hints"] = profile.prompt_hints
    return packet


def load_meta_judge(spec: str = "deepseek") -> DeepseekMetaJudge | None:
    """Load a meta judge by spec.

    Spec syntax:
      "off"                       → disabled
      "deepseek"                  → V4-Pro via $DEEPSEEK_API_KEY
      "deepseek:deepseek-v4-flash" → cheap fast variant
    """
    if spec in ("off", "", None):
        return None
    if spec.startswith("deepseek"):
        model = DEFAULT_DEEPSEEK_MODEL
        if ":" in spec:
            model = spec.split(":", 1)[1]
        try:
            return DeepseekMetaJudge(model=model)
        except Exception as exc:  # noqa: BLE001
            print(f"[meta] failed to init DeepSeek meta judge: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return None
    print(f"[meta] unknown spec: {spec!r}", file=sys.stderr)
    return None
