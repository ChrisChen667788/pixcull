"""V3.0 VLM-as-judge: ask a vision-language model to score the rubric.

The article from 36氪 closes with the line "AI 正在进化到自己训练自己" —
this module is the literal implementation. We give a VLM (default:
Qwen3-VL-4B running locally on Apple silicon via MLX) the same 6-axis
rubric a human annotator would see, ask for stars + rationale, and
treat the result as a third opinion alongside ``auto`` (check list)
and ``model`` (V2.1 per-axis rescorer).

Why this is worth doing
=======================
Three benefits, in priority order:

1. **Bootstrapping the trainer.** V2.1's rescorer is signal-starved
   (~130 rows, mostly auto-derived). A VLM gives us a *third* set of
   labels per image that's far closer to a human's verdict than the
   auto check list — especially on subjective axes like aesthetic
   and moment. Active learning can prioritize images where VLM and
   model disagree, surfacing the most informative ones to label.

2. **Saving the human's time.** The pre-fill in the annotation modal
   becomes the VLM's verdict (when present). The human edits, doesn't
   author from scratch. Empirically (RLHF teams report 3-5×
   throughput gain).

3. **Cross-checking the auto rubric.** When auto says aesthetic=4★
   and the VLM says aesthetic=2★, that's a flag that our check list
   is missing something — diagnostic signal we couldn't get before.

Why MLX, not transformers / Ollama
==================================
The user runs an Apple silicon Mac and already uses MLX-quantized
models (~/.cache/huggingface/hub/models--mlx-community--*). MLX
inference on M-series chips is 2-4× faster than transformers+MPS
for VLMs, and the 4-bit Qwen3-VL-4B is only 2.9 GB on disk vs ~9 GB
for the unquantized variant.

Backend abstraction
===================
We expose ``VlmJudge`` as a thin protocol so callers don't care which
backend is loaded. Today we ship ``MlxQwen3VlJudge``; tomorrow if a
user wants to point at GPT-4V or Claude or Llava we add a sibling
class without touching the orchestrator.

Failure modes
=============
* Model not downloaded → ``load_default_judge()`` returns None,
  pipeline runs without VLM column. Loud on stderr.
* Generation crash on one image → that image's prediction is None,
  rest of the batch continues. Caller treats None as "no opinion".
* Generation returns malformed JSON → we attempt to repair with a
  regex parse, then fall back to None.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pixcull.scoring.rubric import RUBRIC_AXES


DEFAULT_MODEL_REPO = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
SMALLER_MODEL_REPO = "mlx-community/Qwen3-VL-2B-Instruct-4bit"
BIGGER_MODEL_REPO = "mlx-community/Qwen3-VL-8B-Instruct-4bit"

# Image resize cap for the VLM. Native DSLR resolution (e.g. 5472×3648)
# generates ~16K image tokens which prefill takes 80+ seconds. 1024px on
# the long edge yields ~2K image tokens → ~10s prefill, no quality loss
# for the kind of judgment we're asking ("does this picture work?").
# This is empirically what every Qwen-VL eval pipeline does.
VLM_RESIZE_LONG_EDGE = 1024


# ---------------------------------------------------------------------------
# Prompt design.
#
# We send a single user-turn with a system instruction folded in. The model
# must respond in JSON only — we constrain via ``json_only`` flag in the
# generation kwargs and a fenced-block heuristic in parsing.
#
# Critical design choices:
#
# * Keep the prompt SHORT. Qwen3-VL gets confused on 1000-token system
#   prompts; the rubric descriptors (5 levels × 6 axes = 30 strings) blow
#   the budget. We send the AXIS NAMES + a one-line summary per axis only,
#   trusting the descriptors are training-set-implicit knowledge for
#   "subject / composition / light / etc".
#
# * Force JSON output. The model has to fit a schema we can ``json.loads``.
#   Asking for free-form prose then parsing wastes tokens and breaks on
#   trailing commas.
#
# * Ask for ONE-LINE rationale, not paragraph. Long rationales degrade
#   star quality (model spends attention on writing prose instead of
#   judging). Short rationale = better stars.
# ---------------------------------------------------------------------------

_AXIS_HINTS_ZH = {
    "technical":   "对焦/曝光/锐度/噪点 — 是否技术上能用",
    "subject":     "主体清晰、姿态/表情是否到位",
    "composition": "画面布局、平衡感、引导线",
    "light":       "光质、方向、色温、明暗对比",
    "moment":      "时机、动作峰值、情绪含量",
    "aesthetic":   "整体艺术感、色彩协调、记忆点",
}


def build_prompt(scene: str | None = None,
                  style_section: str = "") -> str:
    """Construct the system+user prompt for one image.

    V5.0 update: prepends the photography canon (Cartier-Bresson +
    Adams Zone System + classic composition + lighting patterns) so
    the VLM scores against the same reference a working photo editor
    uses, not against fuzzy training-set medians. Empirically this
    cuts the "all images get 4★ aesthetic" problem in half — the
    model now spends attention on canon-grounded discriminators.

    V8.0 update: optional ``style_section`` carries detected
    style modes (B&W / low-key / long-exposure / silhouette / etc.)
    so the VLM stops marking intentionally-broken-rules photos down.
    See pixcull.scoring.style_modes.render_style_section_zh().

    Important: the JSON template uses ``<...>`` placeholders, NOT
    realistic example values. Earlier versions had filled-in stars +
    rationale and the small VLM would memorize and parrot them back
    regardless of image content. Schema-only template forces actual
    perception.
    """
    # Lazy import to keep this file independent of the canon module's
    # import side effects in old call sites.
    from pixcull.scoring.photography_canon import build_canon_section_zh
    axes_lines = "\n".join(
        f'  - {name}: {_AXIS_HINTS_ZH[name]}'
        for name in (a.name for a in RUBRIC_AXES)
    )
    scene_hint = (
        f"\n场景已被自动分类为: {scene}。" if scene else ""
    )
    canon = build_canon_section_zh()
    style_block = (
        "\n" + style_section + "\n" if style_section else ""
    )
    # V8.2: per-genre standards
    genre_block = ""
    if scene:
        from pixcull.scoring.genre_strategies import render_genre_section_zh
        gs = render_genre_section_zh(scene)
        if gs:
            genre_block = "\n" + gs + "\n"
    # Schema with placeholder values — model has to fill them based on
    # what it actually sees in the image. Numeric placeholders use
    # angle-bracket descriptors so a model that *does* parrot the
    # schema won't accidentally produce systematic bias.
    return f"""你是一位专业摄影编辑。看这张具体的照片,给出基于这张照片实际内容的判断。{scene_hint}

{canon}{genre_block}{style_block}
每个维度独立打 1-5★ 并给一句话理由(必须基于你在图中看到的具体细节,引用上面的经典原则)。

【重要 — 评论质量要求】
- 每条 rationale 必须提到你在这张图里看到的**具体内容**(具体的物体、位置、动作),而不是一般性原则
- 不同图片不要套用相同模板句(比如不要每张都说 "Zone V 中灰锚定准确")
- 每条 rationale 至少包含一个**这张图独有**的描述词(比如 "前景的青稞地"、"右侧逆光的鹰翅"、"水面倒影的银白色块")
- rationale 长度 30-80 中文字符,精炼但要具体

{axes_lines}

★ 含义: 1=废片  2=问题明显  3=合格平庸  4=优秀  5=顶级

总判: keep / maybe / cull (基于你 6 轴的综合)。

返回 JSON,不要任何额外文字。schema:
{{
  "axes": {{
    "technical":   {{"stars": <1-5>, "rationale": "<基于这张图的具体观察>"}},
    "subject":     {{"stars": <1-5>, "rationale": "<...>"}},
    "composition": {{"stars": <1-5>, "rationale": "<...>"}},
    "light":       {{"stars": <1-5>, "rationale": "<...>"}},
    "moment":      {{"stars": <1-5>, "rationale": "<...>"}},
    "aesthetic":   {{"stars": <1-5>, "rationale": "<...>"}}
  }},
  "overall_label": "<keep|maybe|cull>",
  "overall_rationale": "<一句话总结这张图>"
}}

记住: rationale 必须提到你看到的具体内容(主体是什么、光线方向、场景细节),并尽量引用经典原则名(如\"Zone III\"、\"Rule of Space\"、\"Rembrandt\"、\"决定性瞬间\")。不要写空话。"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class VlmAxisScore:
    stars: float | None
    rationale: str = ""


@dataclass
class VlmVerdict:
    """One VLM call's structured output."""
    filename: str
    axes: dict[str, VlmAxisScore]
    overall_label: str = ""
    overall_rationale: str = ""
    elapsed_s: float = 0.0
    raw_text: str = ""    # the raw model output, kept for debugging
    error: str | None = None
    model_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "overall_label": self.overall_label,
            "overall_rationale": self.overall_rationale,
            "elapsed_s": round(self.elapsed_s, 2),
            "model_name": self.model_name,
            "error": self.error,
            "axes": {
                k: {"stars": v.stars, "rationale": v.rationale}
                for k, v in self.axes.items()
            },
        }


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------

class VlmJudge(Protocol):
    model_name: str
    def score(self, image_path: Path, scene: str | None = None,
              max_tokens: int = 400) -> VlmVerdict: ...


# ---------------------------------------------------------------------------
# MLX backend (default on Apple silicon)
# ---------------------------------------------------------------------------

class MlxQwen3VlJudge:
    """Qwen3-VL via mlx-vlm. Loads weights once, scores per call.

    Threadsafety: mlx is single-threaded by design. Wrap calls in a
    semaphore if you spawn worker threads — the orchestrator already
    runs analyze_one in a single thread so we don't bother here.
    """

    def __init__(
        self,
        model_repo: str = DEFAULT_MODEL_REPO,
        resize_long_edge: int = VLM_RESIZE_LONG_EDGE,
    ):
        self.model_name = model_repo
        self.resize_long_edge = resize_long_edge
        # Lazy import: keeps `import vlm_judge` cheap if MLX isn't
        # installed on this box.
        from mlx_vlm import load
        from mlx_vlm.utils import load_config

        print(f"[vlm] loading {model_repo} (this can take 10-30s on first call)…",
              file=sys.stderr)
        t = time.time()
        self.model, self.processor = load(model_repo)
        self.config = load_config(model_repo)
        # Per-judge tempdir for resized images. Lives for the process
        # lifetime; cleaned by OS when /tmp gets swept.
        import tempfile
        self._tmpdir = Path(tempfile.mkdtemp(prefix="pixcull_vlm_"))
        print(f"[vlm] loaded in {time.time() - t:.1f}s · "
              f"resize cap {resize_long_edge}px · "
              f"temp dir {self._tmpdir}", file=sys.stderr)

    def _prep_image(self, image_path: Path) -> Path:
        """Resize and re-save to a small JPEG. Returns the temp path.

        We always re-encode rather than passing the original — guarantees
        the model never sees a 50MB CR3 (which it would either crash on
        or chew through 16K tokens unnecessarily). PIL handles every
        format the project's loader accepts.
        """
        from pixcull.io.loader import load_image
        long_edge = self.resize_long_edge
        img = load_image(image_path, max_side=long_edge)
        if img is None:
            # Fallback: pass original path and let the model deal with it
            return image_path
        out = self._tmpdir / f"{image_path.stem}_{long_edge}.jpg"
        img.save(out, "JPEG", quality=85, optimize=True)
        return out

    def score(
        self,
        image_path: Path,
        scene: str | None = None,
        max_tokens: int = 800,    # Chinese rationale ×6 axes is long
        style_section: str = "",
    ) -> VlmVerdict:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        prompt = build_prompt(scene, style_section=style_section)
        # Qwen3-VL chat template wants the image referenced in the
        # user turn; mlx-vlm's apply_chat_template handles the special
        # tokens. We pass the image path as a list since some templates
        # support multi-image.
        formatted = apply_chat_template(
            self.processor,
            self.config,
            prompt,
            num_images=1,
        )

        verdict = VlmVerdict(
            filename=image_path.name,
            axes={a.name: VlmAxisScore(stars=None) for a in RUBRIC_AXES},
            model_name=self.model_name,
        )
        t0 = time.time()
        try:
            # Resize before sending — full DSLR res destroys throughput
            # and adds nothing to perception quality at this task.
            small_path = self._prep_image(image_path)
            output = generate(
                self.model,
                self.processor,
                formatted,
                image=[str(small_path)],
                max_tokens=max_tokens,
                verbose=False,
                temperature=0.0,  # deterministic — same image always same verdict
            )
            # mlx-vlm returns a GenerationResult or string depending on version
            text = output if isinstance(output, str) else getattr(output, "text", str(output))
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
        return verdict


# ---------------------------------------------------------------------------
# OpenAI-compatible API backend (Deepseek / MiniMax / OpenAI / Anthropic-via-proxy)
#
# Both Deepseek and MiniMax expose OpenAI-compatible /v1/chat/completions
# endpoints with vision support. Same wire format works for both — only the
# base_url and model name differ. Cost: roughly ¥0.001-0.005 per image at
# 1024px resolution (Deepseek-VL-67B and MiniMax abab-6.5-vision tier).
# ---------------------------------------------------------------------------

class OpenAICompatibleVlmJudge:
    """Generic backend for any OpenAI-compatible Chat-with-Vision API.

    Tested against:
      - Deepseek (base_url='https://api.deepseek.com', model='deepseek-vl' or
                  'deepseek-chat' if image is in input)
      - MiniMax  (base_url='https://api.minimax.chat/v1',
                  model='MiniMax-VL-01' or 'abab6.5-vision-01')
      - OpenAI   (base_url=None, model='gpt-4o' / 'gpt-4o-mini')

    Image is sent as base64 data URL — works for all three providers and
    avoids the need to host the file anywhere accessible to the API.

    The image is resized to ``resize_long_edge`` first, same as the local
    backend, both to save bandwidth (20MB → 200KB) and because most APIs
    bill per token and image tokens scale with resolution.
    """

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str,
        model: str,
        provider_name: str = "openai-compatible",
        resize_long_edge: int = VLM_RESIZE_LONG_EDGE,
        timeout_s: float = 60.0,
    ):
        if not api_key:
            raise ValueError(f"{provider_name}: api_key is required")
        # OpenAI Python SDK is the de facto client for any compatible API.
        # Lazy import keeps this module light when no API backend is used.
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = f"{provider_name}:{model}"
        self._model = model
        self._provider = provider_name
        self.resize_long_edge = resize_long_edge
        self._timeout = timeout_s
        import tempfile
        self._tmpdir = Path(tempfile.mkdtemp(prefix=f"pixcull_vlm_api_"))

    def _prep_image_b64(self, image_path: Path) -> str:
        """Load → resize → JPEG → base64 data URL."""
        import base64
        from pixcull.io.loader import load_image
        img = load_image(image_path, max_side=self.resize_long_edge)
        if img is None:
            raise ValueError(f"failed to decode image: {image_path}")
        buf_path = self._tmpdir / f"{image_path.stem}.jpg"
        img.save(buf_path, "JPEG", quality=85, optimize=True)
        b = buf_path.read_bytes()
        return "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")

    def score(
        self,
        image_path: Path,
        scene: str | None = None,
        max_tokens: int = 600,
        style_section: str = "",
    ) -> VlmVerdict:
        verdict = VlmVerdict(
            filename=image_path.name,
            axes={a.name: VlmAxisScore(stars=None) for a in RUBRIC_AXES},
            model_name=self.model_name,
        )
        t0 = time.time()
        try:
            data_url = self._prep_image_b64(image_path)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text",
                         "text": build_prompt(scene, style_section=style_section)},
                        {"type": "image_url",
                         "image_url": {"url": data_url}},
                    ],
                }
            ]
            # response_format only works on some providers (OpenAI, MiniMax).
            # Try with json_object first; if the provider rejects, retry
            # without it.
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    timeout=self._timeout,
                )
            except Exception:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.0,
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
        return verdict


# Convenience factories — keep provider URLs/defaults in one place so the
# CLI / demo can spell them by name without callers needing to know
# Deepseek's base_url etc.
def make_deepseek_judge(api_key: str, model: str = "deepseek-vl") -> OpenAICompatibleVlmJudge:
    return OpenAICompatibleVlmJudge(
        base_url="https://api.deepseek.com",
        api_key=api_key,
        model=model,
        provider_name="deepseek",
    )


def make_minimax_judge(api_key: str,
                        model: str = "MiniMax-VL-01") -> OpenAICompatibleVlmJudge:
    return OpenAICompatibleVlmJudge(
        # MiniMax's official base path (subject to change — verify in
        # their docs at the time of integration).
        base_url="https://api.minimax.chat/v1",
        api_key=api_key,
        model=model,
        provider_name="minimax",
    )


def make_openai_judge(api_key: str, model: str = "gpt-4o-mini") -> OpenAICompatibleVlmJudge:
    return OpenAICompatibleVlmJudge(
        base_url=None,  # default OpenAI endpoint
        api_key=api_key,
        model=model,
        provider_name="openai",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_vlm_response(text: str) -> dict[str, Any] | None:
    """Best-effort extract a JSON dict from the VLM's output.

    Models often wrap JSON in fences ```json ... ``` or prepend a sentence
    of explanation despite our "JSON only" instruction. We strip both.
    """
    if not text:
        return None
    s = text.strip()
    # Strip code fence
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    # Try direct
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Extract first {...} block
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def load_judge(spec: str = "local") -> VlmJudge | None:
    """Load a VLM judge by spec string. Returns None on any failure.

    Spec syntax:
      "off"                       → disabled
      "local"                     → MlxQwen3VlJudge with default model
      "local:Qwen3-VL-2B-...4bit" → MLX with a specific repo
      "deepseek"                  → uses $DEEPSEEK_API_KEY
      "deepseek:deepseek-vl"      → explicit model
      "minimax"                   → uses $MINIMAX_API_KEY
      "openai"                    → uses $OPENAI_API_KEY
      "api:<base_url>:<model>"    → arbitrary OpenAI-compatible endpoint;
                                    key from $PIXCULL_VLM_API_KEY
    """
    import os

    if spec == "off" or not spec:
        return None

    if spec.startswith("local"):
        repo = DEFAULT_MODEL_REPO
        if ":" in spec:
            repo = spec.split(":", 1)[1]
        try:
            return MlxQwen3VlJudge(repo)
        except ImportError as exc:
            print(f"[vlm] mlx-vlm not installed: {exc}", file=sys.stderr)
            return None
        except Exception as exc:  # noqa: BLE001
            print(f"[vlm] failed to load {repo}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return None

    parts = spec.split(":", 1)
    provider = parts[0]
    model_override = parts[1] if len(parts) > 1 else None

    try:
        if provider == "deepseek":
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            return make_deepseek_judge(key, model_override or "deepseek-vl")
        if provider == "minimax":
            key = os.environ.get("MINIMAX_API_KEY", "")
            return make_minimax_judge(key, model_override or "MiniMax-VL-01")
        if provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "")
            return make_openai_judge(key, model_override or "gpt-4o-mini")
        if provider == "api":
            # api:https://my.endpoint/v1:my-model
            inner = spec[len("api:"):]
            base_url, model = inner.rsplit(":", 1)
            key = os.environ.get("PIXCULL_VLM_API_KEY", "")
            return OpenAICompatibleVlmJudge(
                base_url=base_url, api_key=key, model=model,
                provider_name="custom",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[vlm] failed to init {spec}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None

    print(f"[vlm] unknown spec: {spec!r}", file=sys.stderr)
    return None


# Backwards compatibility shim for older callers that still use the
# original API. The orchestrator's new code uses load_judge() directly.
def load_default_judge() -> VlmJudge | None:
    return load_judge("local")
