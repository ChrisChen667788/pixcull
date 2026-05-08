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


# 10 verticals as named by the user. Ordering = display order on the
# /verticals page (visually grouped by parent-genre cluster).
VERTICALS: tuple[Vertical, ...] = (
    Vertical(
        key="landscape",  zh="风光摄影", icon="🏔",
        description="自然山水/星空/晨昏/极地。重曝光层次 + 构图严谨,锐度需要顶级。",
        parent_genres=frozenset({"landscape", "astro"}),
        sample_target=25,
        primary_axes=("technical", "composition", "light", "aesthetic"),
    ),
    Vertical(
        key="wildlife",   zh="野生动物摄影", icon="🐅",
        description="哺乳/爬行/水生野生主体。抓姿态 + 焦点在眼睛 + 大光圈隔离背景。",
        parent_genres=frozenset({"wildlife"}),
        sample_target=20,
        primary_axes=("subject", "moment", "technical"),
    ),
    Vertical(
        key="bird",       zh="拍鸟", icon="🦅",
        description="飞鸟 / 栖鸟 / 涉禽。眼神光 + 飞行姿态 + 翅膀清晰是核心。",
        parent_genres=frozenset({"wildlife"}),
        sample_target=20,
        primary_axes=("subject", "moment", "technical"),
    ),
    Vertical(
        key="wedding",    zh="婚纱摄影", icon="💒",
        description="婚礼现场 / 婚纱预约。高调干净光、人物表情自然、瞬间到位。",
        parent_genres=frozenset({"portrait", "event", "fashion"}),
        sample_target=30,
        primary_axes=("subject", "light", "moment", "aesthetic"),
    ),
    Vertical(
        key="travel",     zh="旅拍写真", icon="🌅",
        description="海岛 / 古镇 / 异域旅拍。环境与人物比例,色彩氛围,服装与场景搭配。",
        parent_genres=frozenset({"portrait", "landscape", "street"}),
        sample_target=25,
        primary_axes=("composition", "light", "aesthetic"),
    ),
    Vertical(
        key="cosplay",    zh="cosplay", icon="🎭",
        description="角色扮演 + 道具服装。服装细节锐 + 角色姿态戏剧 + 场景氛围契合。",
        parent_genres=frozenset({"portrait", "fashion"}),
        sample_target=20,
        primary_axes=("subject", "composition", "aesthetic"),
    ),
    Vertical(
        key="kids",       zh="儿童摄影", icon="👶",
        description="日常 / 摄影棚 / 户外。表情真实 > 锐度;动作模糊若情绪到位仍可保留。",
        parent_genres=frozenset({"portrait"}),
        sample_target=25,
        primary_axes=("moment", "subject", "aesthetic"),
    ),
    Vertical(
        key="pet",        zh="宠物摄影", icon="🐶",
        description="家养 / 流浪 / 工作犬。眼神 + 神态 + 干净背景。",
        parent_genres=frozenset({"wildlife", "portrait"}),
        sample_target=20,
        primary_axes=("subject", "moment", "aesthetic"),
    ),
    Vertical(
        key="event",      zh="活动摄影", icon="🎪",
        description="发布会 / 演出 / 大型活动。多人场景的瞬间 + 信息密度构图。",
        parent_genres=frozenset({"event", "documentary"}),
        sample_target=25,
        primary_axes=("moment", "composition", "subject"),
    ),
    Vertical(
        key="sports",     zh="运动摄影", icon="⚽",
        description="赛场 / 训练 / 极限。峰值瞬间 + 高速锐度 + 动作姿态。",
        parent_genres=frozenset({"sports"}),
        sample_target=30,
        primary_axes=("moment", "technical", "subject"),
    ),
)


_BY_KEY: dict[str, Vertical] = {v.key: v for v in VERTICALS}


def get_vertical(key: str) -> Vertical | None:
    return _BY_KEY.get(key)


def list_verticals() -> tuple[Vertical, ...]:
    return VERTICALS


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
    """Return [{filename, size, mtime}, ...] for one bucket of one vertical."""
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
        }, ...]
    """
    out = []
    for v in VERTICALS:
        c = count_samples(v.key)
        # Progress is min(good, bad)/target — we want BOTH buckets full
        # so a vertical that has 50 good + 0 bad doesn't look complete.
        balanced = min(c["good"], c["bad"])
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
