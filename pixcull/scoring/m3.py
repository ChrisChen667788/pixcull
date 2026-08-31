"""v2.48 — MiniMax M3 as the primary judge, for photos *and* video.

Why this module exists separately from ``vlm_judge.py``
-------------------------------------------------------
``vlm_judge.OpenAICompatibleVlmJudge`` is a thin, provider-agnostic
wrapper: encode one image, POST, parse.  That was the right shape when a
VLM was an optional *fourth opinion* whose verdict landed in a parallel
CSV column and changed nothing.

M3 is being made the **primary** judge, which turns three previously
academic problems into shipping requirements:

1. **Correctness cannot be assumed.**  ``score()``'s outer
   ``except Exception`` converts every failure — wrong endpoint, wrong
   model string, expired key, malformed video part — into
   ``verdict.error`` and returns.  With the VLM as a bonus opinion that
   was graceful degradation.  With it as *the* judge, a 3000-photo run
   that produced 3000 nulls is indistinguishable from a good one until
   somebody opens the JSONL.  Hence :func:`probe_capabilities` and the
   ``pixcull m3 doctor`` command.

2. **Money and time are now real.**  The old path had no budget gate, no
   retry, no rate limiter and no cache.  At the published 200 RPM a
   3000-photo wedding is ~15 minutes; serial at 3 s/call it is ~105
   minutes, long enough that the run *will* be interrupted, and without a
   content-hash cache every interruption re-bills from zero.

3. **A VLM cannot measure.**  See :func:`build_evidence_block`.

Wire contract (verified against vendor docs 2026-08-12)
-------------------------------------------------------
* base_url — REGIONAL, see :data:`REGIONS`.  ``api.minimaxi.com`` (China)
  and ``api.minimax.io`` (international) are separate accounts; a key for
  one gets ``401 invalid api key`` from the other, which reads as a bad
  key rather than a wrong region.  ``api.minimax.chat`` is the pre-M3
  host and rejects the ``minimax-m3`` model entirely.
* model ``minimax-m3``
* image: content part ``{"type": "image_url", "image_url": {"url": …}}``,
  https URL or data URI, **≤ 10 MB**
* video: content part named ``video_url``, MP4/AVI/MOV/MKV, **≤ 50 MB**,
  ``fps`` in [0.2, 5.0] (default 1)
* whole request body ≤ 64 MB; 200 RPM / 10M TPM; audio is NOT accepted
  on chat completions

**The video content-part JSON is now CONFIRMED against the live API**
(2026-08-14, CN region): ``video_url_object`` —
``{"type": "video_url", "video_url": {"url": <data URI>, "fps": 1.0}}``.

It was not confirmable from documentation: the vendor's page was
unreachable and no third-party mirror carried the literal schema, only
the field name and the limits.  So rather than hard-code a guess into the
scoring path and let it fail as a silent null,
:data:`VIDEO_PART_SHAPES` lists the candidates and ``pixcull m3 doctor
--video`` probes them against the real endpoint, recording the winner in
:func:`capability_path`.  The first candidate turned out to be right —
but "my guess was right" and "I verified it" are different claims, and
only the second one is safe to build 3000 API calls on.
:meth:`MiniMaxM3Judge.score_video` still refuses to run until a probe has
recorded a shape.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.vlm_judge import (
    VLM_RESIZE_LONG_EDGE,
    VlmAxisScore,
    VlmVerdict,
    build_prompt,
    parse_vlm_response,
)

# ---------------------------------------------------------------------------
# Vendor contract
# ---------------------------------------------------------------------------

#: MiniMax runs two independent regions with SEPARATE accounts, and a key
#: issued for one is simply invalid on the other — the international host
#: answers a China key with `401 invalid api key (2049)`, which reads as
#: "your key is wrong" rather than "your key is for the other region".
#:
#: v2.52.2: this cost a real debugging session. I hardcoded the
#: international host from the English docs while this repo's own brand
#: scripts (scripts/brand/gen_empty_state_art.py, gen_mascot.mjs) had been
#: calling api.minimaxi.com for months. The evidence was in the tree.
#:
#: Order matters: the owner and most of this project's users are in China,
#: so probe that one first.
REGIONS: dict[str, str] = {
    "cn":     "https://api.minimaxi.com/v1",
    "global": "https://api.minimax.io/v1",
}
DEFAULT_REGION = "cn"

#: url → region name. A reverse map rather than a genexp over REGIONS,
#: so that "iterating REGIONS" means exactly one thing in this codebase:
#: an auth sweep. tests/test_m3.py asserts there is only one of those.
REGION_BY_URL: dict[str, str] = {v: k for k, v in REGIONS.items()}

BASE_URL = REGIONS[DEFAULT_REGION]
MODEL = "minimax-m3"


def resolve_base_url() -> str:
    """Endpoint to use: the probed one, else ``$MINIMAX_REGION``, else CN.

    Prefers what ``pixcull m3 doctor`` actually observed over anything
    guessed, because "which region is this key for" is not something the
    key's shape reveals.
    """
    caps = load_capabilities() or {}
    # Only a probe that AUTHENTICATED counts. The first version trusted
    # any recorded base_url, which meant a doctor run that got 401 from
    # the wrong region pinned the judge to that wrong region forever —
    # the probe's whole job is to find the endpoint that works, so
    # remembering one that did not is worse than remembering nothing.
    if caps.get("text") == "ok" and caps.get("base_url") in REGIONS.values():
        return caps["base_url"]
    env = os.environ.get("MINIMAX_REGION", "").strip().lower()
    return REGIONS.get(env, REGIONS[DEFAULT_REGION])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_BODY_BYTES = 64 * 1024 * 1024

# Published limits.  RPM is the binding one for us: at ~1.5k input tokens
# per photo, 200 RPM is only ~300k TPM, well inside the 10M TPM ceiling.
RPM_LIMIT = 200
TPM_LIMIT = 10_000_000

VIDEO_FPS_MIN, VIDEO_FPS_MAX = 0.2, 5.0
VIDEO_FPS_DEFAULT = 1.0

#: Candidate wire encodings for a video content part, most-likely first.
#: :func:`probe_capabilities` tries them in order against the live API.
#: Keep the *names* stable — they are persisted in the capability file.
VIDEO_PART_SHAPES: dict[str, Callable[[str, float], dict]] = {
    # The shape every OpenAI-compatible multimodal vendor that supports
    # video has converged on, and the one the field name `video_url`
    # implies.
    "video_url_object": lambda url, fps: {
        "type": "video_url",
        "video_url": {"url": url, "fps": fps},
    },
    # Same, without fps — in case the endpoint rejects unknown keys
    # rather than ignoring them.  (Silent-ignore is the norm, which is
    # exactly why `usage` echoing a request field is not proof it took
    # effect; see the api-param-check lesson.)
    "video_url_object_no_fps": lambda url, fps: {
        "type": "video_url",
        "video_url": {"url": url},
    },
    # Qwen-VL style: a bare string rather than an object.
    "video_url_string": lambda url, fps: {
        "type": "video_url",
        "video_url": url,
    },
}

_DEFAULT_VIDEO_SHAPE = "video_url_object"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window token bucket, shared across judge instances.

    A plain ``sleep(60/rpm)`` between calls wastes most of the budget:
    it paces to the *average* rate even when the last minute was idle.
    This tracks actual timestamps so a burst after a quiet period is
    allowed, which matters because the pipeline alternates between local
    detector phases (no API traffic at all) and API phases.
    """

    def __init__(self, rpm: int = RPM_LIMIT):
        self.rpm = max(1, int(rpm))
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a call may proceed.  Returns seconds waited."""
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < self.rpm:
                    self._calls.append(now)
                    return waited
                sleep_for = 60.0 - (now - self._calls[0]) + 0.01
            time.sleep(sleep_for)
            waited += sleep_for


_GLOBAL_LIMITER = RateLimiter()


# ---------------------------------------------------------------------------
# Resumable cache
# ---------------------------------------------------------------------------

def _content_hash(path: Path, extra: str = "") -> str:
    """Hash of file bytes + a prompt-affecting discriminator.

    Keyed on **content**, not filename: photographers rename and
    re-export constantly, and two runs of the same shoot from different
    folders must hit the same cache entry.  ``extra`` folds in anything
    that changes the request (model, prompt version, evidence block), so
    a prompt edit correctly invalidates rather than silently serving
    stale verdicts.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    h.update(extra.encode("utf-8"))
    return h.hexdigest()


class VerdictCache:
    """Append-only JSONL cache of verdicts, keyed by content hash.

    Append-only rather than rewrite-on-save: a run killed mid-write must
    not corrupt the entries already paid for.  A truncated final line is
    skipped on load.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._mem: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue        # torn tail from a killed run
                    key = rec.get("key")
                    if key:
                        self._mem[key] = rec.get("verdict") or {}
        except OSError:
            pass

    def get(self, key: str) -> dict | None:
        with self._lock:
            return self._mem.get(key)

    def put(self, key: str, verdict: dict) -> None:
        with self._lock:
            self._mem[key] = verdict
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"key": key, "verdict": verdict},
                                        ensure_ascii=False) + "\n")
            except OSError as exc:
                print(f"[m3] cache write failed: {exc}", file=sys.stderr)

    def __len__(self) -> int:
        return len(self._mem)


def default_cache_path() -> Path:
    return Path.home() / ".pixcull" / "cache" / "m3_verdicts.jsonl"


def capability_path() -> Path:
    """Where the doctor records what the live endpoint actually accepted."""
    return Path.home() / ".pixcull" / "m3_capabilities.json"


def load_capabilities() -> dict:
    p = capability_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_capabilities(caps: dict) -> None:
    p = capability_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    caps = dict(caps)
    caps["probed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    p.write_text(json.dumps(caps, ensure_ascii=False, indent=2),
                 encoding="utf-8")


# ---------------------------------------------------------------------------
# Evidence — the reason this is not just "POST the JPEG"
# ---------------------------------------------------------------------------

#: (csv column, label, formatter).  Deliberately small: every line costs
#: input tokens on every photo, and a wall of numbers dilutes the ones
#: that matter.  These are exactly the signals a VLM reads badly.
_EVIDENCE_FIELDS: tuple[tuple[str, str, Callable[[Any], str]], ...] = (
    ("laplacian_subject", "主体清晰度(拉普拉斯方差)",
     lambda v: f"{float(v):.0f}"),
    ("laplacian_global", "全图清晰度", lambda v: f"{float(v):.0f}"),
    ("highlight_clip_pct", "高光溢出",  lambda v: f"{float(v):.2f}%"),
    ("shadow_clip_pct", "暗部死黑",     lambda v: f"{float(v):.2f}%"),
    ("mean_luma", "平均亮度(0-255)",   lambda v: f"{float(v):.0f}"),
    ("face_count", "检出人脸数",        lambda v: str(int(v))),
    ("eyes_closed_count", "闭眼人数",   lambda v: str(int(v))),
    ("burst_size", "同组连拍张数",      lambda v: str(int(v))),
    ("dup_group_size", "近重复组大小",  lambda v: str(int(v))),
)

#: v2.66 — composition fields, for the A/B.
#:
#: Every field in _EVIDENCE_FIELDS is technical, and on the only
#: non-circular data this project has they measure 0.9x lift against the
#: photographer's own culls — worse than chance. The one signal that
#: separates a cull from a keep is composition (-0.82 sigma), which the
#: judge is currently told nothing about even though the local stack
#: computes eleven of them.
_COMPOSITION_FIELDS: tuple[tuple[str, str, Callable[[Any], str]], ...] = (
    ("rule_of_thirds_offset", "主体离三分点距离(0=正中三分点)",
     lambda v: f"{float(v):.3f}"),
    ("canon_lead_room", "视线/运动前方留白比",
     lambda v: f"{float(v):.2f}"),
    ("canon_figure_ground", "主体与背景分离度",
     lambda v: f"{float(v):.2f}"),
    ("canon_balance", "左右视觉重量平衡(0.5=均衡)",
     lambda v: f"{float(v):.2f}"),
    ("canon_diagonal_energy", "对角线张力",
     lambda v: f"{float(v):.2f}"),
    ("canon_symmetry", "对称度", lambda v: f"{float(v):.2f}"),
    ("subject_fraction", "主体占画面比例",
     lambda v: f"{float(v):.3f}"),
)

#: The three arms. `technical` is what ships today; the others exist to
#: find out whether the evidence block is helping or crowding out what
#: the judge could see for itself.
EVIDENCE_ARMS: dict[str, tuple] = {
    "technical": _EVIDENCE_FIELDS,
    "composition": _COMPOSITION_FIELDS,
    "both": _EVIDENCE_FIELDS + _COMPOSITION_FIELDS,
    "none": (),
}

_EVIDENCE_HEADER = """
## 客观测量(本机检测器实测,非你的观察)
以下数值由本地算法测出,精度高于目视判断。请把它们当作事实,
结合你在画面里看到的内容一起下判断;当你的观感与测量冲突时,
在 rationale 里说明冲突,不要假装没看到。
""".strip()


def build_evidence_block(row: dict[str, Any] | None,
                         arm: str = "technical") -> str:
    """Serialise local detector readings into a prompt section.

    This is the load-bearing idea of v2.48.  A VLM asked "is this sharp?"
    guesses from perceived micro-contrast, which is exactly what a
    shallow-depth-of-field portrait defeats.  A Laplacian variance is not
    a guess.  Same for clipped highlights (a histogram fact), closed eyes
    (a landmark ratio) and near-duplicate group size (a pairwise hash
    comparison over the whole shoot, which no single-image call can see).

    So the local stack is not deleted and it is not a competing opinion —
    it becomes the instrument panel the judge reads.

    Returns "" when nothing is measurable, so the caller can omit the
    section entirely rather than send an empty heading.
    """
    fields = EVIDENCE_ARMS.get(arm, _EVIDENCE_FIELDS)
    if not row or not fields:
        return ""
    lines: list[str] = []
    for col, label, fmt in fields:
        val = row.get(col)
        if val is None or val == "":
            continue
        try:
            lines.append(f"- {label}: {fmt(val)}")
        except (TypeError, ValueError):
            continue      # a NaN or a stray string is not worth a crash

    flags = row.get("flags")
    if isinstance(flags, str) and flags.strip():
        lines.append(f"- 规则引擎标记: {flags.strip()}")
    elif isinstance(flags, (list, tuple)) and flags:
        lines.append(f"- 规则引擎标记: {', '.join(str(f) for f in flags)}")

    if not lines:
        return ""
    return _EVIDENCE_HEADER + "\n" + "\n".join(lines)


#: Bump when the prompt changes in a way that should invalidate cached
#: verdicts.  Folded into the cache key.
PROMPT_VERSION = "v2.48.0"


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

@dataclass
class _Attempt:
    ok: bool
    detail: str = ""


class MiniMaxM3Judge:
    """MiniMax M3 over the OpenAI-compatible endpoint.

    Thread-safe: the OpenAI client is, the rate limiter and cache take
    their own locks.  Intended to be constructed once and shared by a
    ``ThreadPoolExecutor``.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = MODEL,
        base_url: str | None = None,
        resize_long_edge: int = VLM_RESIZE_LONG_EDGE,
        timeout_s: float = 90.0,
        max_retries: int = 5,
        cache: VerdictCache | None = None,
        limiter: RateLimiter | None = None,
        enforce_budget: bool = True,
        require_consent: bool = True,
    ):
        if not api_key:
            raise ValueError(
                "minimax-m3: api_key is required. Set MINIMAX_API_KEY, or "
                "store it via the app's key dialog. PixCull never reads a "
                "key from the repo.")
        from openai import OpenAI
        base_url = base_url or resolve_base_url()
        self._client = OpenAI(api_key=api_key, base_url=base_url,
                              max_retries=0)   # we do our own backoff
        self.base_url = base_url
        self._model = model
        self.model_name = f"minimax:{model}"
        self.resize_long_edge = resize_long_edge
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._cache = cache
        self._limiter = limiter or _GLOBAL_LIMITER
        self._enforce_budget = enforce_budget
        self._require_consent = require_consent
        import tempfile
        self._tmpdir = Path(tempfile.mkdtemp(prefix="pixcull_m3_"))

    # -- transport ------------------------------------------------------

    def _sleep_for_retry(self, attempt: int) -> float:
        """Exponential backoff, capped.  Deterministic — no jitter — so a
        test can assert the schedule; concurrency is already spread out by
        the rate limiter, which is what jitter would otherwise buy us."""
        return min(2.0 ** attempt, 60.0)

    def _complete(self, messages: list[dict], max_tokens: int) -> Any:
        """One chat completion, with rate limiting, retry and budget.

        Retries on rate-limit and transient server errors.  Does NOT
        retry on auth or request-shape errors — those never recover and
        retrying them just burns five backoff sleeps before reporting the
        same failure.
        """
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            RateLimitError,
        )

        if self._require_consent and not has_consent():
            raise ConsentRequired(
                "No cloud-upload consent on file. PixCull will not send "
                "photos to MiniMax until you say so:\n\n"
                "    pixcull m3 consent --grant\n\n"
                "Or run entirely on this machine with `--vlm-mode off`.")
        last: Exception | None = None
        for attempt in range(self._max_retries):
            self._limiter.acquire()
            try:
                return self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.0,
                    timeout=self._timeout,
                )
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                last = exc
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise            # 4xx: shape/auth — will never succeed
                last = exc
            if attempt < self._max_retries - 1:
                time.sleep(self._sleep_for_retry(attempt))
        assert last is not None
        raise last

    def _charge(self, resp: Any) -> None:
        """Record real token usage against the daily ledger."""
        try:
            from pixcull.llm_budget import record_call
            usage = getattr(resp, "usage", None)
            record_call(self._model,
                        int(getattr(usage, "prompt_tokens", 0) or 0),
                        int(getattr(usage, "completion_tokens", 0) or 0))
        except Exception:  # noqa: BLE001 — accounting must never kill a run
            pass

    def _budget_ok(self, estimate_yuan: float) -> bool:
        if not self._enforce_budget:
            return True
        try:
            from pixcull.llm_budget import check_budget
            return check_budget(estimate_yuan)
        except Exception:  # noqa: BLE001
            return True

    # -- encoding -------------------------------------------------------

    def _image_data_uri(self, image_path: Path) -> str:
        """Load → resize → JPEG → data URI, guaranteed under the 10 MB cap.

        Quality is stepped down rather than failing, because a 10 MB cap
        on a 1024px JPEG is only reachable with pathological content, and
        dropping the photo entirely would be a worse outcome than sending
        it at q60.
        """
        from pixcull.io.loader import load_image
        img = load_image(image_path, max_side=self.resize_long_edge)
        if img is None:
            raise ValueError(f"failed to decode image: {image_path}")
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = self._tmpdir / f"{image_path.stem}.jpg"
        for quality in (85, 70, 60, 45):
            img.save(buf, "JPEG", quality=quality, optimize=True)
            if buf.stat().st_size <= MAX_IMAGE_BYTES:
                break
        raw = buf.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(
                f"{image_path.name}: {len(raw)/1e6:.1f} MB exceeds M3's "
                f"{MAX_IMAGE_BYTES/1e6:.0f} MB image limit even at q45")
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _video_data_uri(video_path: Path) -> str:
        raw = Path(video_path).read_bytes()
        if len(raw) > MAX_VIDEO_BYTES:
            raise ValueError(
                f"{Path(video_path).name}: {len(raw)/1e6:.1f} MB exceeds "
                f"M3's {MAX_VIDEO_BYTES/1e6:.0f} MB video limit — transcode "
                f"the clip to H.264 first (4K ProRes clips are ~187 MB "
                f"for 3 s and will always trip this)")
        suffix = Path(video_path).suffix.lower().lstrip(".") or "mp4"
        mime = {"mp4": "mp4", "mov": "quicktime", "avi": "x-msvideo",
                "mkv": "x-matroska"}.get(suffix, "mp4")
        return (f"data:video/{mime};base64,"
                + base64.b64encode(raw).decode("ascii"))

    # -- scoring --------------------------------------------------------

    def score(
        self,
        image_path: Path,
        scene: str | None = None,
        # v2.52.5 — 600 was sized for a non-reasoning VLM. M3 thinks
        # first, and on a real rubric prompt the reasoning alone runs past
        # 2800 characters, leaving nothing for the answer. Measured, not
        # guessed: at 600 every one of 250 calls came back with no JSON.
        max_tokens: int = 3000,
        style_section: str = "",
        vertical: str | None = None,
        *,
        row: dict[str, Any] | None = None,
        prompt_override: str | None = None,
        # v2.66 — which evidence block to send. `technical` is what ships;
        # the other arms exist to find out whether the block helps or
        # crowds out what the judge could see for itself.
        evidence_arm: str = "technical",
    ) -> VlmVerdict:
        """Judge one photo, with local measurements supplied as evidence.

        ``row`` is the scoring CSV record for this photo.  Passing it is
        what makes this a *fused* judgement rather than a naive one — see
        :func:`build_evidence_block`.  It stays optional so the judge is
        still usable standalone (the doctor, ad-hoc scripts).
        """
        image_path = Path(image_path)
        verdict = VlmVerdict(
            filename=image_path.name,
            axes={a.name: VlmAxisScore(stars=None) for a in RUBRIC_AXES},
            model_name=self.model_name,
        )
        evidence = build_evidence_block(row, evidence_arm)
        if prompt_override is not None:
            # v2.51 — the advice writer asks a different question of the
            # same photo (prose about the frame, not axis stars), and it
            # builds its own evidence section, so this must not be
            # double-appended.
            prompt = prompt_override
        else:
            prompt = build_prompt(scene, style_section=style_section,
                                  vertical=vertical)
            if evidence:
                prompt = prompt + "\n\n" + evidence

        key = ""
        if self._cache is not None:
            try:
                key = _content_hash(
                    image_path,
                    f"{self._model}|{PROMPT_VERSION}|{scene}|{vertical}|"
                    # v2.66 — the ARM, not just the block's length. Two
                    # arms can produce blocks of equal length and mean
                    # entirely different things; keying on length alone
                    # would serve one arm's verdict to another and make
                    # the A/B compare a cache against itself.
                    f"{evidence_arm}|{len(evidence)}|"
                    # v2.51 — scoring and advice ask different questions
                    # of the same bytes. Without this the second caller
                    # would be served the first one's answer.
                    f"{hashlib.sha256((prompt_override or '').encode()).hexdigest()[:12]}")
            except OSError:
                key = ""
            if key:
                hit = self._cache.get(key)
                if hit is not None:
                    # v2.71 — entries written before raw_text was cached
                    # carry none, and a caller who parses raw_text would
                    # read an empty string as "the model said nothing".
                    # For those callers this is a miss, so the call is
                    # made once more and the entry heals itself.
                    if prompt_override and not (hit.get("raw_text") or ""):
                        hit = None
                if hit is not None:
                    return _verdict_from_dict(hit, image_path.name,
                                              self.model_name)

        t0 = time.time()
        try:
            if not self._budget_ok(0.03):
                verdict.error = ("LLM budget exhausted for today — raise "
                                 "PIXCULL_LLM_BUDGET_YUAN or wait for UTC "
                                 "midnight")
                verdict.elapsed_s = time.time() - t0
                return verdict
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": self._image_data_uri(image_path)}},
                ],
            }]
            resp = self._complete(messages, max_tokens)
            self._charge(resp)
            text = resp.choices[0].message.content or ""
            finish = getattr(resp.choices[0], "finish_reason", "")
        except Exception as exc:  # noqa: BLE001
            verdict.elapsed_s = time.time() - t0
            verdict.error = f"{type(exc).__name__}: {exc}"
            return verdict

        verdict.elapsed_s = time.time() - t0
        # v2.52.5 — say WHICH failure this is.
        #
        # M3 is a reasoning model: it emits <think>…</think> before the
        # answer, and at max_tokens=600 the whole budget went to thinking.
        # The reply closed the think block and stopped — not one `{` in
        # 2844 characters. That surfaced as "JSON parse failed", which
        # sent me to inspect the parser while 250 calls billed and were
        # discarded. A truncated reply is a budget problem and the message
        # has to say so.
        if finish == "length":
            verdict.raw_text = text
            verdict.error = (
                f"response truncated at max_tokens={max_tokens} — M3 spent "
                f"the budget on its <think> block and never reached the "
                f"JSON. Raise max_tokens; do not retry at this size.")
            return verdict
        _fill_verdict(verdict, text)
        if key and self._cache is not None and verdict.error is None:
            self._cache.put(key, verdict.to_dict())
        return verdict

    def score_video(
        self,
        video_path: Path,
        prompt: str,
        *,
        fps: float = VIDEO_FPS_DEFAULT,
        max_tokens: int = 600,
        shape: str | None = None,
    ) -> VlmVerdict:
        """Judge a whole clip using M3's native video input.

        This is the capability the pre-v2.48 stack simply does not have:
        reel ranking today is ``mean_final + max_temporal``, i.e. 100%
        proxy metrics, so a clip of the vows and a clip of someone
        adjusting a mic score identically when camera motion and face
        count match.

        ``shape`` selects the wire encoding.  It defaults to whatever
        ``pixcull m3 doctor`` recorded; if the doctor has never run this
        raises rather than guessing, because a wrong shape comes back as
        a generic 4xx that the caller would otherwise store as one more
        null verdict.
        """
        video_path = Path(video_path)
        verdict = VlmVerdict(
            filename=video_path.name,
            axes={a.name: VlmAxisScore(stars=None) for a in RUBRIC_AXES},
            model_name=self.model_name,
        )
        if shape is None:
            shape = load_capabilities().get("video_part_shape") or ""
        if not shape:
            raise RuntimeError(
                "M3 video input has not been verified on this machine. Run "
                "`pixcull m3 doctor --video <clip.mp4>` once — it probes "
                "which content-part encoding the live endpoint accepts and "
                "records it. Refusing to guess: a wrong shape returns a "
                "generic 4xx that would be stored as a null verdict.")
        if shape not in VIDEO_PART_SHAPES:
            raise ValueError(f"unknown video part shape: {shape!r}")

        fps = max(VIDEO_FPS_MIN, min(VIDEO_FPS_MAX, float(fps)))
        t0 = time.time()
        try:
            part = VIDEO_PART_SHAPES[shape](self._video_data_uri(video_path),
                                            fps)
            messages = [{
                "role": "user",
                "content": [{"type": "text", "text": prompt}, part],
            }]
            resp = self._complete(messages, max_tokens)
            self._charge(resp)
            text = resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            verdict.elapsed_s = time.time() - t0
            verdict.error = f"{type(exc).__name__}: {exc}"
            return verdict
        verdict.elapsed_s = time.time() - t0
        _fill_verdict(verdict, text)
        return verdict


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _fill_verdict(verdict: VlmVerdict, text: str) -> None:
    """Fill a verdict from the model's reply, and say so when it cannot.

    v2.82 — measured over 4,138 cached verdict calls, 209 (5.1%) came
    back with no rationale at all AND an empty `error` field. A failure
    that records no reason is the one shape this repository has learned
    to distrust: it is reported by every downstream consumer as "the
    model had nothing to say", which is a judgement, rather than "the
    model's reply could not be read", which is a defect.
    """
    from pixcull.fallback_ledger import LEDGER
    LEDGER.candidates("m3_verdict", 1)
    LEDGER.attempt("m3_verdict")
    verdict.raw_text = text
    parsed = parse_vlm_response(text)
    if parsed is None:
        verdict.error = "JSON parse failed"
        LEDGER.fell_back("m3_verdict", "parse_failed", (text or "")[:120] or "empty reply")
        return
    for axis_name in verdict.axes:
        ax = (parsed.get("axes") or {}).get(axis_name) or {}
        stars = ax.get("stars")
        try:
            if stars is not None:
                stars = max(1.0, min(5.0, float(stars)))
        except (TypeError, ValueError):
            stars = None
        verdict.axes[axis_name] = VlmAxisScore(
            stars=stars, rationale=str(ax.get("rationale", ""))[:300])
    verdict.overall_label = str(parsed.get("overall_label", "")).lower()
    verdict.overall_rationale = str(parsed.get("overall_rationale", ""))[:300]
    if verdict.overall_rationale.strip():
        LEDGER.ok("m3_verdict")
    else:
        # Parsed cleanly and still said nothing. Distinct from a parse
        # failure and, until v2.82, indistinguishable from success.
        LEDGER.fell_back("m3_verdict", "truncated", "parsed but no rationale")


def _verdict_from_dict(d: dict, filename: str, model_name: str) -> VlmVerdict:
    v = VlmVerdict(
        filename=filename,
        axes={a.name: VlmAxisScore(stars=None) for a in RUBRIC_AXES},
        model_name=model_name,
    )
    for name, ax in (d.get("axes") or {}).items():
        if name in v.axes:
            v.axes[name] = VlmAxisScore(stars=(ax or {}).get("stars"),
                                        rationale=(ax or {}).get("rationale", ""))
    v.overall_label = d.get("overall_label", "")
    v.overall_rationale = d.get("overall_rationale", "")
    v.raw_text = d.get("raw_text", "") or ""
    v.elapsed_s = 0.0        # a cache hit cost no wall-clock
    return v


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------

def api_key_from_env() -> str:
    """The key, from the environment only.

    Deliberately never reads the repo.  ``MINIMAX_API_KEY`` first, then
    the macOS keychain, which is where the app stores it so a GUI launch
    (no shell environment) can still find it.
    """
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if key:
        return key
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(
                ["security", "find-generic-password", "-s",
                 "MINIMAX_API_KEY", "-w"],
                capture_output=True, text=True, timeout=10)
            if out.returncode == 0:
                return out.stdout.strip()
        except Exception:  # noqa: BLE001
            pass
    return ""


def probe_capabilities(api_key: str,
                       image_path: Path | None = None,
                       video_path: Path | None = None,
                       *,
                       model: str = MODEL,
                       base_url: str = BASE_URL) -> dict:
    """Make real calls and report what the endpoint actually accepted.

    This exists because every failure mode in this integration is silent.
    A stale base_url, a stale model string, an expired key and a wrong
    video content-part all surface identically — as ``verdict.error`` on
    every row — and a run of 3000 nulls looks exactly like a run that
    worked until somebody opens the JSONL.

    Returns a dict of capability → result.  Never raises; a failed probe
    is data.
    """
    caps: dict[str, Any] = {
        "base_url": base_url,
        "model": model,
        "text": None,
        "image": None,
        "json_object": None,
        "video_part_shape": None,
        "video_attempts": {},
    }

    try:
        from openai import OpenAI
    except ImportError as exc:
        caps["text"] = f"openai SDK not installed: {exc}"
        return caps

    # v2.52.4 — one region sweep for the whole codebase.
    #
    # This block used to own a fourth hand-written copy of it. Three of
    # the four decided from the LAST region's error, which meant a key
    # that is merely out of credit (CN: 402) got reported as invalid
    # (global: 401) and sent the owner to reissue a working key. Twice.
    # The property that keeps being lost — the billing signal must win
    # regardless of which region produced it — belongs to the sweep as a
    # whole, so it lives in one function now.
    state, detail = probe_key(api_key, model=model)
    caps["key_state"] = state
    caps["text"] = "ok" if state == "ok" else detail
    if state == "ok":
        base_url = caps["base_url"] = detail
        caps["region"] = REGION_BY_URL.get(detail, DEFAULT_REGION)
    else:
        return caps

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

    def _try(fn) -> _Attempt:
        """Run one capability probe; a failure is data, not an exception.

        v2.52.5 — this and the client above were collateral damage when I
        replaced the hand-written region sweep with probe_key(): the
        deletion took the whole block between `_auth_ok` and the first
        capability, and these two lived inside it. Every later probe then
        referenced an undefined name, so the doctor crashed with a
        NameError at exactly the moment a working key finally reached it.
        """
        try:
            fn()
            return _Attempt(True, "ok")
        except Exception as exc:  # noqa: BLE001
            return _Attempt(False, f"{type(exc).__name__}: {exc}"[:300])

    # 2. structured output
    a = _try(lambda: client.chat.completions.create(
        model=model,
        messages=[{"role": "user",
                   "content": 'Reply with JSON {"ok":1} and nothing else.'}],
        max_tokens=16, response_format={"type": "json_object"}, timeout=30))
    caps["json_object"] = a.detail

    # 3. image content part
    if image_path is not None and Path(image_path).exists():
        judge = MiniMaxM3Judge(api_key, model=model, base_url=base_url,
                               enforce_budget=False)
        uri = judge._image_data_uri(Path(image_path))
        a = _try(lambda: client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "What is in this image? One word."},
                {"type": "image_url", "image_url": {"url": uri}}]}],
            max_tokens=16, timeout=60))
        caps["image"] = a.detail

    # 4. video content part — the shape we could not confirm from docs
    if video_path is not None and Path(video_path).exists():
        try:
            uri = MiniMaxM3Judge._video_data_uri(Path(video_path))
        except ValueError as exc:
            caps["video_attempts"]["_encode"] = str(exc)
            uri = ""
        if uri:
            for name, build in VIDEO_PART_SHAPES.items():
                part = build(uri, VIDEO_FPS_DEFAULT)
                a = _try(lambda p=part: client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": [
                        {"type": "text",
                         "text": "Describe this clip in one sentence."}, p]}],
                    max_tokens=48, timeout=120))
                caps["video_attempts"][name] = a.detail
                if a.ok:
                    caps["video_part_shape"] = name
                    break

    return caps


# ---------------------------------------------------------------------------
# Consent — v2.50
# ---------------------------------------------------------------------------
#
# Cloud judging ships on.  That is defensible only if the first upload is
# something the photographer chose, and it is a real constraint rather
# than a formality: wedding and commercial contracts routinely forbid
# third-party cloud processing of client images, and the person who signed
# one cannot discover the upload afterwards.
#
# So: an explicit, recorded, revocable grant, checked before the first
# call — not a pre-ticked box, and not a line in the release notes.

CONSENT_VERSION = 1


def consent_path() -> Path:
    return Path.home() / ".pixcull" / "cloud_consent.json"


def has_consent() -> bool:
    """True only for a grant of the CURRENT version.

    Versioned deliberately: if what we upload ever materially changes —
    video clips as well as stills, say — the old grant does not cover the
    new thing, and silently reusing it would be the trick this gate
    exists to prevent.
    """
    try:
        d = json.loads(consent_path().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(d.get("granted")) and int(d.get("version", 0)) == CONSENT_VERSION


def grant_consent(*, endpoint: str = BASE_URL) -> Path:
    p = consent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "granted": True,
        "version": CONSENT_VERSION,
        "endpoint": endpoint,
        "granted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2), encoding="utf-8")
    return p


def revoke_consent() -> bool:
    try:
        consent_path().unlink()
        return True
    except OSError:
        return False


CONSENT_NOTICE = """\
PixCull is about to send your photos to MiniMax (api.minimax.io) so M3
can judge them.

  · The image itself is uploaded, downscaled to 1024px, over HTTPS.
  · Locally measured numbers — sharpness, clipping, blink counts — are
    sent with it as evidence.
  · Faces, GPS and file paths are NOT stripped. The photo is the photo.
  · MiniMax's retention and training policy is theirs, not ours. Read it.

Many wedding and commercial contracts forbid third-party cloud
processing of client images. If yours does, decline — `--vlm-mode off`
runs the whole pipeline on this machine and is fully supported.
"""


#: MiniMax's own status codes, which do NOT always ride on the HTTP
#: status. The legacy `/v1/text/chatcompletion_v2` route answers
#: **HTTP 200** with the real failure buried in `base_resp.status_code`
#: — an HTTP-200 check there reads a hard failure as a success. We call
#: `/v1/chat/completions`, which returns a proper 402, so this is a note
#: for whoever adds the next route rather than a live hazard.
MINIMAX_STATUS = {
    1008: "insufficient balance",
    2049: "invalid api key",
}


def probe_key(api_key: str, *, model: str = MODEL) -> tuple[str, str]:
    """Try a key against every region. Returns ``(state, detail)``.

    ``state`` is one of ``ok`` / ``nobalance`` / ``badkey`` / ``missing``.

    This exists because I wrote the same loop by hand three times in one
    session and got it wrong the same way twice: reporting the LAST
    region's error. CN answers 402 (key good, no balance) and global
    answers 401 (wrong region), so whichever is tried last decides the
    diagnosis — and "your key is invalid" sends someone to reissue a key
    that was working. The billing signal has to win no matter which
    region produced it, which is a property of the whole sweep, not of
    one iteration. One function, one place to get it right.
    """
    if not api_key:
        return "missing", "no key stored"
    try:
        from openai import OpenAI
    except ImportError as exc:
        return "badkey", f"openai SDK missing: {exc}"
    errors: list[str] = []
    for url in REGIONS.values():
        try:
            OpenAI(api_key=api_key, base_url=url, max_retries=0
                   ).chat.completions.create(
                model=model, messages=[{"role": "user", "content": "ping"}],
                max_tokens=4, timeout=30)
            return "ok", url
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    joined = " ".join(errors)
    if "1008" in joined or "insufficient_balance" in joined or "402" in joined:
        return "nobalance", explain_api_error(Exception(joined))
    return "badkey", explain_api_error(Exception(joined)) or joined[:300]


def explain_api_error(exc: Exception) -> str:
    """Turn a MiniMax failure into the action that fixes it.

    Worth a function because the two common ones need OPPOSITE fixes and
    look similar in a stack trace. Getting this backwards cost a real
    session: a China key against the international host answers `401
    invalid api key`, which sent us hunting for a bad key that was fine.
    """
    msg = str(exc)
    if "1008" in msg or "insufficient_balance" in msg or "402" in msg:
        return ("MiniMax reports insufficient balance (1008). The key is "
                "GOOD — it authenticated. Top up the account; ~400 photos "
                "is about \u00a52. Nothing here can work around an empty "
                "account.")
    if "2049" in msg or "invalid api key" in msg:
        return ("MiniMax rejected the key (2049). Most often this is the "
                "WRONG REGION rather than a bad key: api.minimaxi.com (CN) "
                "and api.minimax.io (international) are separate accounts. "
                "`pixcull m3 doctor` tries both.")
    return ""


class ConsentRequired(RuntimeError):
    """Raised instead of uploading when no grant is on file."""
