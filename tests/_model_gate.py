"""v2.40 — a skip must mean "can't run here", never "quietly didn't run".

The tests that exercise real models used to guard themselves with a
blanket ``except Exception: pytest.skip(...)``.  That conflates two very
different situations:

* the model genuinely isn't on this machine (fresh clone, offline CI) —
  skipping is right;
* the model IS sitting in the local cache and the load failed anyway —
  skipping is *wrong*, because a genuine regression then reports itself
  as a skip and the gate stays green.

That is not hypothetical.  During the v2.39 gate the skip count floated
between 5 and 8 runs apart: the Hugging Face Hub rate-limits
unauthenticated requests, so repeated loads inside one pytest session
started failing, and three real-model tests silently stopped running —
including the one pinning v2.34's ``image_embeds ≡ get_image_features``
equivalence, which is the sole guard on every cached CLIP vector the
pipeline writes.

So: **if the weights are on disk, the test runs.**  The load is done
with ``HF_HUB_OFFLINE=1`` so a cached model can never be turned into a
failure by the network, and any exception after that is a real failure.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Repos the real-model tests need, by the id the production code passes
# to from_pretrained().  Keep in sync with pixcull/detectors/scene.py and
# pixcull/scoring/reel_caption.py.
CLIP_REPO = "openai/clip-vit-base-patch32"
VLM_REPO = os.environ.get("PIXCULL_VLM_MODEL",
                          "Salesforce/blip-image-captioning-base")


def _hub_cache_dirs() -> list[Path]:
    """Every directory a HF snapshot might live in, most specific first."""
    out = []
    for env in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        v = os.environ.get(env)
        if v:
            out.append(Path(v))
    home = os.environ.get("HF_HOME")
    if home:
        out.append(Path(home) / "hub")
    out.append(Path.home() / ".cache" / "huggingface" / "hub")
    return out


def is_cached(repo_id: str) -> bool:
    """True when ``repo_id`` has a non-empty snapshot on this machine.

    Deliberately structural rather than calling into huggingface_hub:
    this must answer "are the weights here" without touching the network,
    which is the whole point.
    """
    slug = "models--" + repo_id.replace("/", "--")
    for base in _hub_cache_dirs():
        snaps = base / slug / "snapshots"
        if not snaps.is_dir():
            continue
        for rev in snaps.iterdir():
            if rev.is_dir() and any(rev.iterdir()):
                return True
    return False


def require_model(repo_id: str, loader, *, what: str):
    """Load a model for a test, or skip *only* if it isn't here.

    ``loader`` is called with no arguments and should return whatever the
    test needs.  Returns that value.

    Skips when the weights aren't cached.  When they ARE cached the load
    happens offline and must succeed — an exception propagates as a test
    failure, because a model that is on disk failing to load is a defect,
    not an environment excuse.
    """
    if not is_cached(repo_id):
        pytest.skip(
            f"{what} weights not cached locally ({repo_id}); "
            f"run the feature once to populate ~/.cache/huggingface")

    prev = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        return loader()
    except Exception as exc:  # noqa: BLE001 — deliberately NOT a skip
        raise AssertionError(
            f"{what} is cached at {repo_id} but failed to load offline: "
            f"{type(exc).__name__}: {exc}\n"
            f"This is a real failure. Before v2.40 it was swallowed as a "
            f"skip, which let regressions hide behind a green gate."
        ) from exc
    finally:
        if prev is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prev


def require_clip():
    """The CLIP tower used by scene detection, semantic search and the
    v2.34 free-ride vector cache."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("PIL")
    from pixcull.detectors.scene import _clip
    return require_model(CLIP_REPO, _clip, what="CLIP")


# ── ModelScope (FunASR / Paraformer) ─────────────────────────────────
#
# v2.43.2.  FunASR pulls its weights from ModelScope, not the HF hub, so
# the layout above doesn't apply: models land in
# ``$MODELSCOPE_CACHE/models/<namespace>/<name>/``.
#
# Every bug this version fixed — the lazy-import lie, the missing
# `sentence_info`, the per-call model rebuild — was invisible to tests
# that never started the engine.  Hence a real-engine lane, under the
# same rule as CLIP: **if the weights are here, it runs.**
PARAFORMER_REPOS = (
    "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
)


def _modelscope_cache_dirs() -> list[Path]:
    out = []
    v = os.environ.get("MODELSCOPE_CACHE")
    if v:
        out.append(Path(v))
    out.append(Path.home() / ".cache" / "modelscope")
    return out


def is_modelscope_cached(repo_id: str) -> bool:
    """True when a ModelScope repo has real weights on this machine.

    Checks for ``model.pt`` specifically rather than a non-empty
    directory: an interrupted download leaves the config and README
    behind, and treating that as "cached" would turn a partial download
    into a confusing test failure instead of a skip.
    """
    for base in _modelscope_cache_dirs():
        d = base / "models" / repo_id
        if (d / "model.pt").is_file():
            return True
    return False


def require_paraformer():
    """The FunASR stack: ASR + VAD + punctuation, all three needed.

    Returns the loaded model. Skips only when the engine or its weights
    are genuinely absent — on a machine that has them, a failure to load
    is a defect, exactly as with CLIP.
    """
    pytest.importorskip("funasr")
    pytest.importorskip("torchaudio",
                        reason="funasr imports torchaudio but does not "
                               "declare it — see pixcull[asr]")
    missing = [r for r in PARAFORMER_REPOS if not is_modelscope_cached(r)]
    if missing:
        pytest.skip("Paraformer weights not cached locally "
                    f"({len(missing)}/{len(PARAFORMER_REPOS)} missing); "
                    "run `pixcull transcribe -e paraformer` once, or set "
                    "MODELSCOPE_CACHE to the drive holding them")
    from pixcull.scoring.transcribe import _paraformer_model
    try:
        return _paraformer_model()
    except Exception as exc:  # noqa: BLE001 — deliberately NOT a skip
        raise AssertionError(
            f"Paraformer weights are cached but the model failed to "
            f"build: {type(exc).__name__}: {exc}") from exc
