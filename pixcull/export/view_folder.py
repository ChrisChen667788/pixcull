"""v2.99 — export a folder that is actually meant to be looked at.

The studio path is: photographer exports, opens the folder on an iPad or
a Mac, client sits beside them and points. `pixcull export` could only
write XMP sidecars or a ratings CSV — useful to Lightroom, useless to a
person with a client waiting — so the photographer either round-trips
through another application or copies files by hand.

And when they copy by hand, the two things PixCull knows that nobody
else does are destroyed at exactly the moment they matter:

  WHICH MOMENT a photograph belongs to — ceremony, toasts, portraits
  WHICH FRAMES ARE THE SAME MOMENT — and which of them is the best

The second one is the whole conversation. The client says "this one is
lovely but her eyes are closed — is there another?" and PixCull knows
there are five more from that half-second and which one is sharpest.
In a flat folder that is gone, and the photographer says "let me check
back at the computer".

So: chapters become folders, bursts become folders inside them, and the
peak sorts first. Nothing here is a new concept — it is the structure
already in the run, written down in the only vocabulary a file browser
speaks.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SCENE_ZH = {
    "landscape": "风光", "wildlife": "野生", "portrait": "人像",
    "wedding": "婚礼", "sports": "运动", "street": "街拍",
    "architecture": "建筑", "night": "夜景", "macro": "微距",
    "abstract": "抽象", "stilllife": "静物", "documentary": "纪实",
}
MOMENT_ZH = {
    "prep": "准备", "ceremony": "仪式", "vows": "誓言", "rings": "交戒",
    "kiss": "亲吻", "toast": "敬酒", "banquet": "宴席", "dance": "跳舞",
    "portrait": "外景", "family": "合影", "exit": "送别",
}
_UNSAFE = re.compile(r"[^\w一-鿿.-]+")


def safe_component(name: str, fallback: str = "其他") -> str:
    """A path component that cannot escape, collide with a device name,
    or arrive on a phone as something unopenable."""
    s = _UNSAFE.sub("_", str(name or "").strip()).strip("._")
    return (s or fallback)[:60]


def chapter_of(row: dict) -> str:
    """Which folder a photograph belongs in.

    Moment first, because "敬酒" tells a photographer more than "人像"
    when they are standing next to the client; scene second; and never
    an empty string, which would put files in the run's root and lose
    the grouping entirely.
    """
    m = str(row.get("wedding_moment") or "").strip()
    if m:
        return MOMENT_ZH.get(m, m)
    s = str(row.get("scene") or "").strip()
    if s:
        return SCENE_ZH.get(s, s)
    return "其他"


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


@dataclass
class Plan:
    chapters: dict           # chapter -> [(rel_path, source_row), ...]
    bursts: int = 0
    singles: int = 0
    total: int = 0


def plan_layout(rows: list[dict], *, only: str = "keep") -> Plan:
    """Decide where every photograph goes, without touching the disk."""
    chosen = [r for r in rows
              if not only or str(r.get("decision", "")) == only]
    # Shooting order where it is known; the CSV's own order otherwise.
    chosen.sort(key=lambda r: (str(r.get("datetime") or ""),
                               str(r.get("filename") or "")))

    by_cluster: dict[str, list[dict]] = defaultdict(list)
    for r in chosen:
        cid = str(r.get("cluster_id") or "")
        by_cluster[cid or f"__solo__{r.get('filename')}"].append(r)

    plan = Plan(chapters=defaultdict(list))
    seq = 0
    burst_no = 0
    for cid, members in by_cluster.items():
        chapter = safe_component(chapter_of(members[0]))
        if len(members) < 2:
            seq += 1
            plan.singles += 1
            r = members[0]
            plan.chapters[chapter].append(
                (f"{seq:04d}-{safe_component(_base(r))}{_ext(r)}", r))
            continue
        burst_no += 1
        seq += 1
        plan.bursts += 1
        # Peak first, then the rest in shooting order — the answer to
        # "is there another?" opens with the best one already on top.
        peak = [m for m in members if _truthy(m.get("is_burst_peak"))]
        rest = [m for m in members if not _truthy(m.get("is_burst_peak"))]
        ordered = peak + rest
        folder = f"{seq:04d}-连拍{burst_no:02d}({len(members)}张)"
        for i, m in enumerate(ordered):
            tag = "01-最佳" if (i == 0 and peak) else f"{i + 1:02d}"
            plan.chapters[chapter].append(
                (f"{folder}/{tag}-{safe_component(_base(m))}{_ext(m)}", m))
    plan.total = sum(len(v) for v in plan.chapters.values())
    plan.chapters = dict(plan.chapters)
    return plan


def _base(row: dict) -> str:
    name = str(row.get("orig_filename") or row.get("filename") or "photo")
    return Path(name).stem


def _ext(row: dict) -> str:
    p = str(row.get("path") or row.get("filename") or "")
    e = Path(p).suffix
    return e if e else ".jpg"


def write_view_folder(rows: list[dict], dest: Path, *, resolve,
                      only: str = "keep", max_width: int = 0) -> dict:
    """Materialise the plan. ``resolve(filename) -> Path | None``.

    Copies rather than links: this folder is going onto an iPad, into a
    Files app, onto a stick. A symlink survives none of those.

    A photograph whose original cannot be found is REPORTED. A folder
    quietly four frames short is discovered in front of the client.
    """
    plan = plan_layout(rows, only=only)
    written, missing = 0, []
    for chapter, entries in sorted(plan.chapters.items()):
        for rel, row in entries:
            src = resolve(str(row.get("filename") or ""))
            if not src or not Path(src).is_file():
                missing.append(str(row.get("filename") or "?"))
                continue
            out = dest / chapter / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                if max_width:
                    _copy_resized(Path(src), out, max_width)
                else:
                    shutil.copy2(src, out)
                written += 1
            except Exception as exc:  # noqa: BLE001
                missing.append(f"{row.get('filename')}: {type(exc).__name__}")

    (dest / "_目录.json").write_text(json.dumps({
        "schema": "pixcull.view_folder/v1",
        "chapters": {c: len(v) for c, v in sorted(plan.chapters.items())},
        "bursts": plan.bursts, "singles": plan.singles,
        "written": written, "missing": missing,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"written": written, "missing": missing,
            "chapters": len(plan.chapters), "bursts": plan.bursts,
            "singles": plan.singles, "dest": str(dest)}


def _copy_resized(src: Path, out: Path, max_width: int) -> None:
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        # Portrait frames carry an EXIF flag; skipping this sends every
        # vertical photograph to the iPad on its side.
        im = ImageOps.exif_transpose(im).convert("RGB")
        if im.width > max_width:
            h = round(im.height * max_width / im.width)
            im = im.resize((max_width, h), Image.LANCZOS)
        im.save(out, "JPEG", quality=92, optimize=True)
