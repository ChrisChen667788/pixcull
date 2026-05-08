"""V17.0 — vertical registry + per-vertical sample bank.

Verticals vs genres
-------------------
The pipeline already detects 14 internal *genres* (portrait, wildlife,
landscape, etc.) — those are about what's IN the photo.

Verticals are about who's BUYING the photo:
    婚纱摄影  → expects high-key clean backgrounds + 干净光质
    拍鸟      → wants subject focus on the eye + flight pose
    儿童摄影  → tolerates motion blur if expression is alive
    cosplay   → cares about costume detail + character pose

A single genre maps to multiple verticals; a single vertical may
draw on multiple genres. The registry lives in this module so:
    * the eval framework can slice metrics per vertical
    * scan / upload can carry a vertical override (V17.0)
    * future tuning (V17.1+) can adjust thresholds per vertical
      using collected reference samples

Sample bank
-----------
Photographers seed each vertical with reference shots they
themselves consider "good" or "bad". Stored under:

    ~/Library/Application Support/PixCull/verticals/<key>/
        metadata.json
        good/<hash>.jpg
        bad/<hash>.jpg

The hash-named files prevent name collisions when the same person
uploads "DSC_0042.jpg" from different shoots. Storage stays local —
this is the user's private style reference, not a contributed pool.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class VerticalPolicy:
    """V17.2 — scoring overrides applied when a run is tagged with a
    vertical (via the scan dropdown / scan_local body).

    Three knobs, deliberately small:

    * ``keep_min_delta`` shifts ``decide()``'s ``keep_min`` threshold.
      Negative = lower bar to keep (tolerant verticals — kids,
      sports). Positive = raise the bar (风光 expects technical
      perfection).
    * ``cull_max_delta`` shifts the ``cull_max`` threshold the same
      way. Negative = harder to outright cull (creative liberty
      verticals — travel). Positive = harsher cull line.
    * ``tolerated_flags`` are detector flags demoted from hard-cull
      to advisory just for this vertical. ``severely_blurry`` for
      风光 (intentional ICM / long-exposure), ``motion_blur_on_face``
      for kids (capture the laugh, not the still).
    * ``notes`` is a short rationale string surfaced in the results
      page so users see WHY their vertical override changed things.

    All deltas are in score units (0..1 scale, same as ``decide()``'s
    internal thresholds — NOT 0..10 like the YAML). A 0.05 delta is
    "half a star" worth of difference in the rule-keep gate.
    """
    keep_min_delta:  float = 0.0
    cull_max_delta:  float = 0.0
    tolerated_flags: frozenset[str] = frozenset()
    notes:           str = ""


@dataclass(frozen=True)
class Vertical:
    """One business-facing photography vertical."""
    key:           str
    zh:            str
    icon:          str
    description:   str
    # Which of the 14 internal genres are most likely to fire on this
    # vertical's typical batch. Used for vertical-aware genre weighting.
    parent_genres: frozenset[str]
    # Recommended number of samples per bucket (good + bad each).
    # 20 is the smallest count that gives statistically meaningful
    # threshold tuning; below ~10 the noise dominates.
    sample_target: int = 20
    # Axes the vertical historically cares about most. Used as a hint
    # in the per-vertical eval HTML report; not yet wired into scoring.
    primary_axes:  tuple[str, ...] = ()
    # V17.2 — per-vertical scoring policy. Empty default = no override.
    policy:        VerticalPolicy = field(default_factory=VerticalPolicy)


# 10 verticals as named by the user. Ordering = display order on the
# /verticals page (visually grouped by parent-genre cluster).
#
# V17.2 — each vertical gets a hand-tuned ``policy``. Tuning rationale
# encoded in the ``notes`` field so users see why their selection
# changed thresholds. These are *defaults*; V17.3 will let users
# override per-vertical from the admin panel.
VERTICALS: tuple[Vertical, ...] = (
    Vertical(
        key="landscape",  zh="风光摄影", icon="🏔",
        description="自然山水/星空/晨昏/极地。重曝光层次 + 构图严谨,锐度需要顶级。",
        parent_genres=frozenset({"landscape", "astro"}),
        sample_target=25,
        primary_axes=("technical", "composition", "light", "aesthetic"),
        policy=VerticalPolicy(
            keep_min_delta=+0.03,    # 风光 judged stricter on tech quality
            tolerated_flags=frozenset({"severely_blurry"}),
                                     # ICM / long-exposure water/cloud are valid
            notes="风光提高 keep 门槛 +3pp,容忍 long-exposure 软糊",
        ),
    ),
    Vertical(
        key="wildlife",   zh="野生动物摄影", icon="🐅",
        description="哺乳/爬行/水生野生主体。抓姿态 + 焦点在眼睛 + 大光圈隔离背景。",
        parent_genres=frozenset({"wildlife"}),
        sample_target=20,
        primary_axes=("subject", "moment", "technical"),
        policy=VerticalPolicy(
            keep_min_delta=-0.04,    # animals are hard, give some slack
            tolerated_flags=frozenset({"motion_blur_on_face"}),
                                     # face detector trips on muzzle/eye area
            notes="野生降低 keep 门槛 -4pp,容忍人脸检测器误判动物面部",
        ),
    ),
    Vertical(
        key="bird",       zh="拍鸟", icon="🦅",
        description="飞鸟 / 栖鸟 / 涉禽。眼神光 + 飞行姿态 + 翅膀清晰是核心。",
        parent_genres=frozenset({"wildlife"}),
        sample_target=20,
        primary_axes=("subject", "moment", "technical"),
        policy=VerticalPolicy(
            cull_max_delta=-0.03,    # bird shots are usually clearly good or clearly bad
            tolerated_flags=frozenset({"motion_blur_on_face"}),
            notes="拍鸟略提高 cull 门槛 -3pp,允许人脸检测器误判鸟头",
        ),
    ),
    Vertical(
        key="wedding",    zh="婚纱摄影", icon="💒",
        description="婚礼现场 / 婚纱预约。高调干净光、人物表情自然、瞬间到位。",
        parent_genres=frozenset({"portrait", "event", "fashion"}),
        sample_target=30,
        primary_axes=("subject", "light", "moment", "aesthetic"),
        policy=VerticalPolicy(
            keep_min_delta=-0.02,    # candid moments slightly more forgiving
            tolerated_flags=frozenset({"shadows_clipped"}),
                                     # low-key candid often crushes shadows on purpose
            notes="婚纱降低 keep 门槛 -2pp,容忍低调阴影剪切",
        ),
    ),
    Vertical(
        key="travel",     zh="旅拍写真", icon="🌅",
        description="海岛 / 古镇 / 异域旅拍。环境与人物比例,色彩氛围,服装与场景搭配。",
        parent_genres=frozenset({"portrait", "landscape", "street"}),
        sample_target=25,
        primary_axes=("composition", "light", "aesthetic"),
        policy=VerticalPolicy(
            keep_min_delta=-0.03,    # creative liberty
            cull_max_delta=-0.05,    # rarely outright cull
            notes="旅拍整体宽容 keep -3pp / cull -5pp,留更多氛围片",
        ),
    ),
    Vertical(
        key="cosplay",    zh="cosplay", icon="🎭",
        description="角色扮演 + 道具服装。服装细节锐 + 角色姿态戏剧 + 场景氛围契合。",
        parent_genres=frozenset({"portrait", "fashion"}),
        sample_target=20,
        primary_axes=("subject", "composition", "aesthetic"),
        policy=VerticalPolicy(
            keep_min_delta=-0.02,
            tolerated_flags=frozenset({"shadows_clipped",
                                         "severely_underexposed"}),
                                     # 暗调氛围 is the genre
            notes="cosplay 容忍低调 / 欠曝(角色氛围),keep -2pp",
        ),
    ),
    Vertical(
        key="kids",       zh="儿童摄影", icon="👶",
        description="日常 / 摄影棚 / 户外。表情真实 > 锐度;动作模糊若情绪到位仍可保留。",
        parent_genres=frozenset({"portrait"}),
        sample_target=25,
        primary_axes=("moment", "subject", "aesthetic"),
        policy=VerticalPolicy(
            keep_min_delta=-0.05,    # most tolerant — expression > sharpness
            cull_max_delta=-0.05,
            tolerated_flags=frozenset({"motion_blur_on_face",
                                         "subject_blur"}),
            notes="儿童最宽容:keep -5pp / cull -5pp,容忍主体微糊 + 脸部动态",
        ),
    ),
    Vertical(
        key="pet",        zh="宠物摄影", icon="🐶",
        description="家养 / 流浪 / 工作犬。眼神 + 神态 + 干净背景。",
        parent_genres=frozenset({"wildlife", "portrait"}),
        sample_target=20,
        primary_axes=("subject", "moment", "aesthetic"),
        policy=VerticalPolicy(
            keep_min_delta=-0.04,
            tolerated_flags=frozenset({"motion_blur_on_face",
                                         "subject_blur"}),
            notes="宠物 keep -4pp,容忍人脸检测误判 + 主体微糊",
        ),
    ),
    Vertical(
        key="event",      zh="活动摄影", icon="🎪",
        description="发布会 / 演出 / 大型活动。多人场景的瞬间 + 信息密度构图。",
        parent_genres=frozenset({"event", "documentary"}),
        sample_target=25,
        primary_axes=("moment", "composition", "subject"),
        policy=VerticalPolicy(
            keep_min_delta=-0.03,
            tolerated_flags=frozenset({"closed_eyes"}),
                                     # 20-人合影总有人在眨眼
            notes="活动 keep -3pp,容忍多人合影中的闭眼",
        ),
    ),
    Vertical(
        key="sports",     zh="运动摄影", icon="⚽",
        description="赛场 / 训练 / 极限。峰值瞬间 + 高速锐度 + 动作姿态。",
        parent_genres=frozenset({"sports"}),
        sample_target=30,
        primary_axes=("moment", "technical", "subject"),
        policy=VerticalPolicy(
            keep_min_delta=-0.05,    # capture peak even with imperfections
            tolerated_flags=frozenset({"closed_eyes"}),
            notes="运动 keep -5pp,峰值动作优先于完美状态",
        ),
    ),
)


_BY_KEY: dict[str, Vertical] = {v.key: v for v in VERTICALS}


def get_vertical(key: str) -> Vertical | None:
    return _BY_KEY.get(key)


def list_verticals() -> tuple[Vertical, ...]:
    return VERTICALS


def get_effective_policy(key: str) -> VerticalPolicy | None:
    """V17.4 — return the active policy for a vertical, layering any
    auto-tuned override on top of the curated default.

    Lookup order:
      1. ``vertical_root(key)/policy_override.json`` — written by the
         policy tuner (V17.4 admin button); supplies the auto-fitted
         deltas.
      2. ``Vertical.policy`` from the registry — the V17.2 curated
         hand-tuned defaults.

    Override layering is *partial*: missing fields fall through to
    the registry default. Tolerated_flags from the override fully
    replace the default if specified (else inherit). Notes come from
    the override when present, else the registry.

    Unknown vertical → None (caller should treat as "no policy",
    matching ``get_vertical`` behavior).
    """
    v = get_vertical(key)
    if v is None:
        return None
    # Lazy import — keep policy_tuner optional from this module's
    # perspective. policy_tuner imports verticals; making this lazy
    # avoids the import cycle without complicating either module.
    try:
        from pixcull.policy_tuner import load_override
    except Exception:
        return v.policy
    ov = load_override(key)
    if not ov:
        return v.policy
    # Partial override merge — fall through to registry defaults for
    # any field the override didn't set.
    return VerticalPolicy(
        keep_min_delta=float(ov.get("keep_min_delta", v.policy.keep_min_delta)),
        cull_max_delta=float(ov.get("cull_max_delta", v.policy.cull_max_delta)),
        tolerated_flags=frozenset(ov.get("tolerated_flags",
                                          v.policy.tolerated_flags)),
        notes=str(ov.get("notes") or v.policy.notes),
    )


# -----------------------------------------------------------------------------
# Storage paths
# -----------------------------------------------------------------------------

def _data_root() -> Path:
    """Mirror of launcher.app_data_dir() — kept here so this module
    has no app/launcher dependency. See app/launcher.py docstring."""
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        p = Path.home() / ".pixcull"
    p.mkdir(parents=True, exist_ok=True)
    return p


def vertical_root(key: str) -> Path:
    """Per-vertical storage root. Created lazily."""
    p = _data_root() / "verticals" / key
    (p / "good").mkdir(parents=True, exist_ok=True)
    (p / "bad").mkdir(parents=True, exist_ok=True)
    return p


def metadata_path(key: str) -> Path:
    return vertical_root(key) / "metadata.json"


def load_metadata(key: str) -> dict:
    p = metadata_path(key)
    if not p.exists():
        return {"key": key, "created_at": time.time(),
                "good_count": 0, "bad_count": 0, "last_upload_at": None}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"key": key, "created_at": time.time(),
                "good_count": 0, "bad_count": 0, "last_upload_at": None}


def save_metadata(key: str, meta: dict) -> None:
    metadata_path(key).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# -----------------------------------------------------------------------------
# Sample I/O
# -----------------------------------------------------------------------------

ALLOWED_BUCKETS = ("good", "bad")


def _bucket_dir(key: str, bucket: str) -> Path:
    if bucket not in ALLOWED_BUCKETS:
        raise ValueError(f"bucket must be one of {ALLOWED_BUCKETS}")
    return vertical_root(key) / bucket


def list_samples(key: str, bucket: str) -> list[dict]:
    """Return [{filename, size, mtime}, ...] for one bucket of one vertical.

    V17.1 — raises ValueError on unknown vertical, matching the
    behavior of save_sample. Empty bucket → empty list.
    """
    if key not in _BY_KEY:
        raise ValueError(f"unknown vertical: {key}")
    d = _bucket_dir(key, bucket)
    out = []
    for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not f.is_file():
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        out.append({"filename": f.name, "size": st.st_size,
                    "mtime": st.st_mtime})
    return out


def count_samples(key: str) -> dict[str, int]:
    """Cheap (good, bad, total) counter — used by the listing endpoint."""
    if key not in _BY_KEY:
        return {"good": 0, "bad": 0, "total": 0}
    g = sum(1 for f in _bucket_dir(key, "good").iterdir() if f.is_file())
    b = sum(1 for f in _bucket_dir(key, "bad").iterdir() if f.is_file())
    return {"good": g, "bad": b, "total": g + b}


def hashed_filename(original_name: str, content: bytes) -> str:
    """Stable, collision-free name for the bucket. Keeps the original
    extension so PIL / browser can sniff the type, but replaces the
    stem with a content hash so two ``DSC_0042.jpg`` from different
    shoots don't clobber each other."""
    ext = "".join(Path(original_name).suffixes).lower() or ".jpg"
    h = hashlib.sha256(content).hexdigest()[:16]
    return h + ext


def save_sample(key: str, bucket: str, original_name: str,
                  content: bytes) -> dict:
    """Persist one sample. Returns {filename, size, bucket}."""
    if key not in _BY_KEY:
        raise ValueError(f"unknown vertical: {key}")
    if bucket not in ALLOWED_BUCKETS:
        raise ValueError(f"bucket must be one of {ALLOWED_BUCKETS}")
    name = hashed_filename(original_name, content)
    dest = _bucket_dir(key, bucket) / name
    dest.write_bytes(content)
    # Update metadata snapshot
    counts = count_samples(key)
    meta = load_metadata(key)
    meta.update({
        "good_count":     counts["good"],
        "bad_count":      counts["bad"],
        "last_upload_at": time.time(),
    })
    save_metadata(key, meta)
    return {"filename": name, "size": len(content), "bucket": bucket}


def delete_sample(key: str, bucket: str, filename: str) -> bool:
    if key not in _BY_KEY:
        return False
    if bucket not in ALLOWED_BUCKETS:
        return False
    p = _bucket_dir(key, bucket) / filename
    if not p.exists() or not p.is_file():
        return False
    try:
        p.unlink()
    except OSError:
        return False
    counts = count_samples(key)
    meta = load_metadata(key)
    meta.update({"good_count": counts["good"], "bad_count": counts["bad"]})
    save_metadata(key, meta)
    return True


def sample_path(key: str, bucket: str, filename: str) -> Path | None:
    """Resolve a sample to a real path, or None if it doesn't exist
    or contains traversal characters."""
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    p = _bucket_dir(key, bucket) / filename
    return p if p.is_file() else None


# -----------------------------------------------------------------------------
# Public registry export — used by the /verticals JSON endpoint.
# -----------------------------------------------------------------------------

def registry_with_progress() -> list[dict]:
    """Snapshot of every vertical + how full each sample bank is.

    Shape:
        [{
            key, zh, icon, description, parent_genres,
            sample_target, primary_axes,
            counts: {good, bad, total},
            progress: 0..1 (capped, clamps to 1 when bank exceeds target),
            policy: {keep_min_delta, cull_max_delta, tolerated_flags, notes,
                     is_override, baseline_f1?, tuned_f1?},
        }, ...]

    V17.4 — ``policy`` now reflects the EFFECTIVE policy (override
    layered on top of the registry default). ``is_override`` flags
    whether an auto-tuned override is in effect; the UI shows a
    "🎯 已自动调参" badge based on that.
    """
    # Lazy import — avoid cycle at module load.
    try:
        from pixcull.policy_tuner import load_override
    except Exception:
        load_override = lambda _k: None  # noqa: E731
    out = []
    for v in VERTICALS:
        c = count_samples(v.key)
        balanced = min(c["good"], c["bad"])
        ov = load_override(v.key)
        eff = get_effective_policy(v.key) or v.policy
        out.append({
            "key":           v.key,
            "zh":            v.zh,
            "icon":          v.icon,
            "description":   v.description,
            "parent_genres": sorted(v.parent_genres),
            "sample_target": v.sample_target,
            "primary_axes":  list(v.primary_axes),
            "counts":        c,
            "progress":      min(1.0, balanced / max(1, v.sample_target)),
            "policy": {
                "keep_min_delta":  eff.keep_min_delta,
                "cull_max_delta":  eff.cull_max_delta,
                "tolerated_flags": sorted(eff.tolerated_flags),
                "notes":           eff.notes,
                "is_override":     ov is not None,
                "baseline_f1":     (ov or {}).get("baseline_f1"),
                "tuned_f1":        (ov or {}).get("tuned_f1"),
                "tuned_at":        (ov or {}).get("generated_at"),
            },
        })
    return out


__all__ = [
    "Vertical",
    "VERTICALS",
    "ALLOWED_BUCKETS",
    "get_vertical",
    "list_verticals",
    "vertical_root",
    "load_metadata",
    "save_metadata",
    "list_samples",
    "count_samples",
    "save_sample",
    "delete_sample",
    "sample_path",
    "hashed_filename",
    "registry_with_progress",
]
