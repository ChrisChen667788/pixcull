"""V17.13 — Unsplash CC0 reference sample fetcher.

Why Unsplash, not 500px / 图虫
------------------------------
* Unsplash License explicitly permits ANY use (including ML training,
  redistribution, derivative works) without attribution.
  https://unsplash.com/license
* Free developer API: 50 req/hour, 5000 req/month — enough to seed
  ~25 samples per vertical at zero cost.
* Documented JSON REST endpoints. ``Authorization: Client-ID <key>``
  header is the only auth.
* Photographer credit is optional but we capture it as metadata so
  curious users can credit upstream.

Setup
-----
1. Make a free account: https://unsplash.com/
2. Register a free dev app:
     https://unsplash.com/oauth/applications
3. Copy the "Access Key" (also called Client ID).
4. Set it either as the env var ``UNSPLASH_ACCESS_KEY`` or in
   ``~/Library/Application Support/PixCull/config.json``:
     {"unsplash_access_key": "abc123..."}

Public API
----------
* ``search(query, per_page, orientation) → [SearchHit, ...]``
* ``download(hit) → bytes``
* ``populate_vertical(key, query, bucket, count, orientation) →
  {saved, skipped, attributions}``

All network errors are caught + surfaced as ValueError with a
human-friendly message; the V17.13 endpoint translates to a 400/500
the UI can show.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pixcull import verticals as vmod


UNSPLASH_API_BASE = "https://api.unsplash.com"
DEFAULT_TIMEOUT_S = 12
MAX_PER_PAGE = 30          # Unsplash hard cap
DOWNLOAD_TIMEOUT_S = 25


# -----------------------------------------------------------------------------
# Auth
# -----------------------------------------------------------------------------

def _access_key() -> str:
    """Resolve the Unsplash Access Key from env / config.

    Raises ``ValueError`` with a setup hint when missing so the
    /verticals endpoint can return a 400 with actionable guidance.
    """
    k = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    if k:
        return k
    # Same config.json the launcher writes
    import sys as _sys
    if _sys.platform == "darwin":
        cfg_p = Path.home() / "Library" / "Application Support" / "PixCull" / "config.json"
    else:
        cfg_p = Path.home() / ".pixcull" / "config.json"
    if cfg_p.exists():
        try:
            cfg = json.loads(cfg_p.read_text("utf-8"))
            k = str(cfg.get("unsplash_access_key", "") or "").strip()
            if k:
                return k
        except (OSError, json.JSONDecodeError):
            pass
    raise ValueError(
        "Unsplash access key not configured. Get a free one at "
        "https://unsplash.com/oauth/applications and add to config.json: "
        '{"unsplash_access_key": "<your-key>"}'
    )


# -----------------------------------------------------------------------------
# Suggested per-vertical default queries. The UI defaults each vertical
# to its mapping; user can override.
# -----------------------------------------------------------------------------

DEFAULT_QUERIES: dict[str, dict] = {
    "wedding":   {"query": "wedding bride groom",   "orientation": "portrait"},
    "bird":      {"query": "bird in flight nature", "orientation": "landscape"},
    "wildlife":  {"query": "wildlife animal nature","orientation": "landscape"},
    "kids":      {"query": "happy child portrait",  "orientation": "portrait"},
    "pet":       {"query": "dog cat portrait pet",  "orientation": "square"},
    "cosplay":   {"query": "cosplay anime costume", "orientation": "portrait"},
    "landscape": {"query": "landscape mountains",   "orientation": "landscape"},
    "travel":    {"query": "travel destination",    "orientation": "landscape"},
    "event":     {"query": "concert event crowd",   "orientation": "landscape"},
    "sports":    {"query": "sports action peak",    "orientation": "landscape"},
}


def default_query_for(vertical_key: str) -> dict:
    return DEFAULT_QUERIES.get(vertical_key,
                                  {"query": vertical_key,
                                   "orientation": "landscape"})


# -----------------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------------

@dataclass
class SearchHit:
    id:           str                # Unsplash photo id
    description:  str                # description / alt_description
    url_regular:  str                # ~1080px wide
    url_full:     str                # full-resolution (we don't download full)
    download_url: str                # the location/download tracking URL
    photographer: str
    photographer_url: str
    width:        int
    height:       int
    likes:        int
    color:        str                # average hex color


def search(query: str, *, per_page: int = 15,
            orientation: str = "landscape",
            access_key: str | None = None) -> list[SearchHit]:
    """Search Unsplash. Sorted by Unsplash's relevance — top-liked
    photos tend to rank high.

    ``orientation`` ∈ {landscape, portrait, squarish}. Anything else
    gets normalised to landscape.
    """
    access_key = access_key or _access_key()
    per_page = max(1, min(MAX_PER_PAGE, per_page))
    if orientation not in ("landscape", "portrait", "squarish"):
        if orientation == "square":
            orientation = "squarish"
        else:
            orientation = "landscape"

    qs = urllib.parse.urlencode({
        "query":       query,
        "per_page":    per_page,
        "orientation": orientation,
        "order_by":    "relevant",
    })
    req = urllib.request.Request(
        f"{UNSPLASH_API_BASE}/search/photos?{qs}",
        headers={
            "Authorization": f"Client-ID {access_key}",
            "Accept-Version": "v1",
            "User-Agent": "PixCull/17.13 (vertical-sample-fetcher)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")[:200]
        raise ValueError(
            f"Unsplash HTTP {exc.code}: {msg or exc.reason}"
        ) from exc
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unsplash request failed: {exc}") from exc

    hits = []
    for r in data.get("results", []):
        try:
            hits.append(SearchHit(
                id=str(r.get("id", "")),
                description=str(r.get("description") or r.get("alt_description") or ""),
                url_regular=str(r["urls"]["regular"]),
                url_full=str(r["urls"]["full"]),
                download_url=str((r.get("links") or {}).get("download_location") or ""),
                photographer=str((r.get("user") or {}).get("name", "")),
                photographer_url=str((r.get("user") or {}).get("links", {}).get("html", "")),
                width=int(r.get("width") or 0),
                height=int(r.get("height") or 0),
                likes=int(r.get("likes") or 0),
                color=str(r.get("color") or ""),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return hits


# -----------------------------------------------------------------------------
# Download
# -----------------------------------------------------------------------------

def download(hit: SearchHit) -> bytes:
    """Fetch the regular-size image bytes. The Unsplash terms ask us
    to ALSO hit the download_url (analytics ping) — we do that fire-
    and-forget so failure doesn't block the actual bytes fetch.
    """
    # Best-effort analytics ping to honour Unsplash API guidelines.
    if hit.download_url:
        try:
            access_key = _access_key()
            req = urllib.request.Request(
                hit.download_url,
                headers={
                    "Authorization": f"Client-ID {access_key}",
                    "Accept-Version": "v1",
                    "User-Agent": "PixCull/17.13",
                },
            )
            urllib.request.urlopen(req, timeout=4)
        except Exception:
            pass

    # Actual bytes
    try:
        req = urllib.request.Request(
            hit.url_regular,
            headers={"User-Agent": "PixCull/17.13"},
        )
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ValueError(f"image download failed: {exc}") from exc


# -----------------------------------------------------------------------------
# High-level populate-vertical
# -----------------------------------------------------------------------------

@dataclass
class PopulateResult:
    vertical:     str
    bucket:       str
    query:        str
    orientation:  str
    n_searched:   int
    saved:        list[dict] = field(default_factory=list)
    skipped:      list[dict] = field(default_factory=list)
    attributions: list[dict] = field(default_factory=list)


def populate_vertical(
    key: str,
    *,
    query: str | None = None,
    bucket: str = "good",
    count: int = 15,
    orientation: str = "landscape",
    access_key: str | None = None,
) -> PopulateResult:
    """Search → download `count` images → save into the vertical's
    sample bank. Returns a structured result the UI can render.

    Photographer attributions are written to a sidecar
    ``vertical_root(key)/unsplash_attributions.json`` (appended) so
    we keep a record of upstream credits — Unsplash License doesn't
    require attribution but it's polite.
    """
    v = vmod.get_vertical(key)
    if v is None:
        raise ValueError(f"unknown vertical: {key}")
    if bucket not in vmod.ALLOWED_BUCKETS:
        raise ValueError(f"bucket must be one of {vmod.ALLOWED_BUCKETS}")
    if not query:
        query = DEFAULT_QUERIES.get(key, {"query": key})["query"]

    # Bound count to a reasonable per-call window — Unsplash search
    # returns up to 30 per page, we don't paginate in v1.
    count = max(1, min(MAX_PER_PAGE, count))

    hits = search(query, per_page=count,
                    orientation=orientation, access_key=access_key)

    result = PopulateResult(
        vertical=key, bucket=bucket, query=query,
        orientation=orientation, n_searched=len(hits),
    )
    for h in hits[:count]:
        try:
            data = download(h)
            # Cap individual files at 16 MB — Unsplash regular is
            # usually 200KB-3MB so this is just defensive.
            if len(data) > 16 * 1024 * 1024:
                result.skipped.append({"id": h.id, "reason": "> 16 MB"})
                continue
            # Use Unsplash id in filename so re-running doesn't dupe.
            name = f"unsplash-{h.id}.jpg"
            info = vmod.save_sample(key, bucket, name, data)
            result.saved.append({
                "id":           h.id,
                "filename":     info["filename"],
                "photographer": h.photographer,
                "url":          h.photographer_url,
                "likes":        h.likes,
            })
            result.attributions.append({
                "id":           h.id,
                "photographer": h.photographer,
                "url":          h.photographer_url,
                "fetched_at":   time.time(),
                "vertical":     key,
                "bucket":       bucket,
            })
        except Exception as exc:  # noqa: BLE001
            result.skipped.append({
                "id":     h.id,
                "reason": f"{type(exc).__name__}: {exc}",
            })

    # Append attributions sidecar
    if result.attributions:
        att_path = vmod.vertical_root(key) / "unsplash_attributions.json"
        try:
            existing = []
            if att_path.exists():
                existing = json.loads(att_path.read_text("utf-8"))
                if not isinstance(existing, list):
                    existing = []
            existing.extend(result.attributions)
            att_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, json.JSONDecodeError):
            pass

    return result


__all__ = [
    "SearchHit", "PopulateResult",
    "DEFAULT_QUERIES", "default_query_for",
    "search", "download", "populate_vertical",
]
