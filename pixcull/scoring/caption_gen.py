"""P2.5 — auto-generate IPTC Caption-Abstract per photo.

V29 + V29.1 added the OUTPUT side (caption fields surface in XMP
sidecars and exiftool-embedded IPTC). But the caption itself was
just the V20 advice's strengths/weaknesses joined — useful for the
photographer's internal review, weak as a wire-service caption.

Photojournalism / commercial pipelines want a caption that reads
like a description: "Bride and groom exchange vows at Notre Dame
Cathedral; photographer captured the moment as 47 keepers from
this set." P2.5 composes that from the structured data PixCull
already has:

  * scene / decision / score
  * face cluster labels (V22.1 — "Bride", "Groom", named guests)
  * location label (V23.1 — "Notre Dame")
  * burst peak status (V27 — "the peak of a 30-frame sequence")
  * per-image advice (V20 — strengths surfaced as "with sharp focus
    on the subject and dynamic-range preservation in the highlights")

Two modes:

1. **Compose mode** (default, free, offline) — assembles a
   templated sentence from structured signals. Zero API cost.
   Output looks like:

     "Photo of Bride at Notre Dame · keep · 综合分 0.94 · 连拍峰值"

   Translates well across LR/C1 search/filter; readable as is.

2. **Polish mode** (opt-in, INFRA-4-budgeted) — runs the composed
   caption through DeepSeek V4-Flash with a "rewrite as a single
   coherent journalistic-style caption" prompt. Better prose,
   costs ~¥0.003/photo. Gated by ``check_budget`` so a 5000-photo
   run can't overrun the daily cap.

Output schema per row:
    {filename: str, caption: str, source: "compose" | "polish",
     cost_yuan: float | None}

Stored at ``<output_dir>/auto_captions.json`` so the V29/V29.1
exporters can pick them up.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Caption composer — zero-API path
# ---------------------------------------------------------------------------

# Per-scene caption fragments. Two flavors per scene:
#   ``with_people`` — used when a face-cluster label is appended
#                     (e.g. "Portrait photo of Bride and Groom").
#   ``no_people``   — standalone, no dangling preposition
#                     (e.g. "Landscape image" not "Landscape image of").
_SCENE_PHRASING: dict[str, dict[str, str]] = {
    "portrait":     {"with_people": "portrait photo of",
                       "no_people":   "portrait photograph"},
    "wildlife":     {"with_people": "wildlife photo featuring",
                       "no_people":   "wildlife photograph"},
    "event":        {"with_people": "event photo capturing",
                       "no_people":   "event photograph"},
    "landscape":    {"with_people": "landscape image including",
                       "no_people":   "landscape image"},
    "stilllife":    {"with_people": "studio composition of",
                       "no_people":   "studio composition"},
    "street":       {"with_people": "street photograph showing",
                       "no_people":   "street photograph"},
    "architecture": {"with_people": "architectural photograph with",
                       "no_people":   "architectural photograph"},
    "documentary":  {"with_people": "documentary photograph of",
                       "no_people":   "documentary photograph"},
    "fashion":      {"with_people": "fashion editorial featuring",
                       "no_people":   "fashion editorial"},
    "macro":        {"with_people": "macro photograph of",
                       "no_people":   "macro photograph"},
    "food":         {"with_people": "food photography with",
                       "no_people":   "food photograph"},
    "sports":       {"with_people": "sports action shot of",
                       "no_people":   "sports photograph"},
    "astro":        {"with_people": "astrophotograph with",
                       "no_people":   "astrophotograph"},
    "abstract":     {"with_people": "abstract composition with",
                       "no_people":   "abstract composition"},
}


def compose_caption(row: dict[str, Any],
                       *,
                       face_labels: dict[int, str] | None = None,
                       location_labels: dict[int, str] | None = None,
                       max_strength_quote: int = 1) -> str:
    """Free / offline caption composer.

    Builds a single-line caption like:

        "Portrait of Bride at Notre Dame · 综合分 0.94 · 连拍峰值"

    Pieces are joined with " · " separators so the caption parses
    as a single LR/C1 field but reads as enumerable sub-claims.
    """
    scene = str(row.get("scene") or "")
    decision = str(row.get("decision") or "")
    score = row.get("score_final")

    # Subject fragment — combine scene phrasing with face labels.
    # "Portrait of Bride and Groom" reads better than "Portrait photo
    # of subject · Bride · Groom".
    people: list[str] = []
    fc = row.get("face_clusters") or []
    if face_labels:
        seen: set[str] = set()
        for cid in fc:
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            lbl = (face_labels.get(cid_int) or "").strip()
            if lbl and lbl not in seen:
                people.append(lbl)
                seen.add(lbl)

    scene_dict = _SCENE_PHRASING.get(scene) or {}
    if people and scene_dict.get("with_people"):
        subject = f"{scene_dict['with_people'].capitalize()} {' and '.join(people)}"
    elif people:
        subject = f"Photograph of {' and '.join(people)}"
    elif scene_dict.get("no_people"):
        subject = scene_dict["no_people"].capitalize()
    elif scene:
        subject = f"Photograph (scene: {scene})"
    else:
        subject = "Photograph"

    parts: list[str] = [subject]

    # Location fragment — when present.
    if location_labels and row.get("gps_cluster_id") is not None:
        try:
            cid = int(row["gps_cluster_id"])
            loc = (location_labels.get(cid) or "").strip()
        except (TypeError, ValueError):
            loc = ""
        if loc:
            # Append to subject naturally
            parts[0] = parts[0] + f" at {loc}"

    # Decision + score fragment.
    if score is not None:
        try:
            score_f = float(score)
            parts.append(f"综合分 {score_f:.2f}")
        except (TypeError, ValueError):
            pass
    if decision in ("keep", "maybe", "cull"):
        # Use the Chinese decision label since PixCull is zh-default
        parts.append({"keep": "保留", "maybe": "待定", "cull": "建议剔除"}[decision])

    # V27 — burst peak status. Only meaningful when the photo
    # actually IS the peak (not just any row with a singleton cluster).
    if row.get("is_burst_peak") is True:
        # Check that the cluster has >1 member — singletons don't
        # count, but we can't know cluster size from row alone, so
        # rely on the V27 marking being correct for size≥2.
        parts.append("连拍峰值")

    # Top strength fragment from V20 advice — keeps caption rich
    # without dumping the full strengths list.
    advice = row.get("advice") or {}
    strengths = advice.get("strengths") or []
    if strengths:
        # Strip the "(value)" suffix V20 adds for measurements —
        # captions read cleaner without them.
        first = strengths[0]
        # Drop everything inside parens
        import re as _re
        first = _re.sub(r"\s*[((].*?[))]", "", first).strip()
        if first:
            parts.append(first)

    return " · ".join(parts)


# ---------------------------------------------------------------------------
# LLM polish — opt-in, INFRA-4-budgeted
# ---------------------------------------------------------------------------

_POLISH_PROMPT = (
    "Rewrite the following photo caption as a single coherent "
    "journalistic-style sentence in Chinese. Keep proper nouns "
    "(person names, location names) verbatim. Aim for 25-50 chars. "
    "Don't add facts not in the input. Return ONLY the rewritten "
    "sentence, no quotes or labels.\n\n"
    "Input: {composed}\n"
    "Output:"
)


def polish_caption(composed: str, *,
                       model: str = "deepseek-v4-flash") -> dict[str, Any]:
    """Send a composed caption through DeepSeek for prose polish.

    Returns ``{caption, cost_yuan, error?}``. The cost is checked
    against today's LLM budget BEFORE the call — if the budget is
    exhausted, returns the composed caption unchanged with
    ``error="budget_exhausted"``.
    """
    try:
        from pixcull.llm_budget import (
            check_budget, estimate_cost, record_call,
        )
    except ImportError:
        return {"caption": composed, "cost_yuan": None,
                "error": "llm_budget module unavailable"}

    # Pre-call cost estimate. Typical prompt ~80 tokens + 60 output.
    est = estimate_cost(model, 80, 60)
    if not check_budget(est):
        return {"caption": composed, "cost_yuan": 0.0,
                "error": "budget_exhausted"}

    try:
        import os
        from openai import OpenAI
        api_key = os.environ.get("DEEPSEEK_API_KEY") or ""
        if not api_key:
            return {"caption": composed, "cost_yuan": None,
                    "error": "DEEPSEEK_API_KEY unset"}
        client = OpenAI(api_key=api_key,
                          base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user",
                       "content": _POLISH_PROMPT.format(composed=composed)}],
            max_tokens=128,
            temperature=0.3,
            timeout=15,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Strip any wrapping quotes the model might add despite the
        # "no quotes" instruction.
        text = text.strip('"').strip('"').strip('"').strip()
        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        info = record_call(model, pt, ct)
        return {"caption": text or composed,
                "cost_yuan": info["cost_yuan"],
                "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"caption": composed, "cost_yuan": None,
                "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Batch processor — driven by /api/v1/runs/<id>/auto_caption
# ---------------------------------------------------------------------------

def captions_path(output_dir: Path) -> Path:
    return Path(output_dir) / "auto_captions.json"


def load_captions(output_dir: Path) -> dict[str, str]:
    """Load any pre-computed captions for the run. Returns
    ``{filename: caption}``. Empty when the file doesn't exist."""
    p = captions_path(output_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for item in data.get("captions") or []:
        fn = item.get("filename")
        cap = item.get("caption")
        if fn and cap:
            out[str(fn)] = str(cap)
    return out


def generate_for_run(rows: list[dict],
                        output_dir: Path,
                        *,
                        face_labels: dict[int, str] | None = None,
                        location_labels: dict[int, str] | None = None,
                        polish: bool = False,
                        decisions: tuple[str, ...] = ("keep",),
                        ) -> dict[str, Any]:
    """P2.5 main entry point — produce a caption for every photo
    in ``rows`` whose decision is in ``decisions`` (default: keep
    only). Persists to ``<output_dir>/auto_captions.json`` so the
    /export path picks them up.

    Returns ``{written, skipped, cost_yuan, polish_errors}``.
    """
    keep_decisions = set(decisions)
    captions: list[dict] = []
    total_cost = 0.0
    polish_errors = 0
    skipped = 0
    for r in rows:
        if r.get("decision") not in keep_decisions:
            skipped += 1
            continue
        composed = compose_caption(
            r,
            face_labels=face_labels,
            location_labels=location_labels,
        )
        if polish:
            p = polish_caption(composed)
            if p.get("error") == "budget_exhausted":
                # Fall back to composed for this AND remaining
                # photos — no point retrying once we know the cap
                # is hit.
                polish = False
                polish_errors += 1
                caption = composed
                cost = 0.0
                err = "budget_exhausted"
            elif p.get("error"):
                polish_errors += 1
                caption = composed
                cost = p.get("cost_yuan") or 0.0
                err = p["error"]
            else:
                caption = p["caption"]
                cost = p.get("cost_yuan") or 0.0
                err = None
        else:
            caption = composed
            cost = 0.0
            err = None
        total_cost += cost
        captions.append({
            "filename":  r["filename"],
            "caption":   caption,
            "source":    "polish" if (polish and err is None) else "compose",
            "cost_yuan": cost,
        })

    payload = {
        "schema":      "pixcull.auto_captions.v1",
        "generated_at": time.time(),
        "n_total":     len(captions),
        "n_polished":  sum(1 for c in captions if c["source"] == "polish"),
        "total_cost_yuan": total_cost,
        "captions":    captions,
    }
    p = captions_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    except OSError as exc:
        print(f"[caption_gen] save failed: {exc}", file=sys.stderr)

    return {
        "written":        len(captions),
        "skipped":        skipped,
        "n_polished":     payload["n_polished"],
        "cost_yuan":      total_cost,
        "polish_errors":  polish_errors,
        "captions_path":  str(p),
    }


__all__ = [
    "compose_caption",
    "polish_caption",
    "captions_path",
    "load_captions",
    "generate_for_run",
]
