"""V23 — GPS clustering + per-location best picker.

Travel photographer's typical workflow: come home from a 2-week trip
with 2,000 photos across 30 distinct locations (each pagoda, beach,
old town, restaurant). Pre-V23 PixCull treats them as an undifferentiated
batch — the photographer manually scrolls and groups by visual memory.

V23 reads each photo's EXIF GPS coordinates, clusters photos by
location (~100 m radius — tight enough to separate adjacent landmarks,
loose enough to keep all "Eiffel Tower" shots in one bucket regardless
of which side the photographer was standing on), and surfaces a
"per-location best" filter: for each cluster, the highest score_final
photo gets a 🏆 marker.

Distance metric
===============
Great-circle distance via the haversine formula. For our 100 m radius
on a planet-scale dataset we could approximate with equirectangular
projection at the latitude of each cluster, but haversine is honest
about the spherical geometry and only ~3× slower (microseconds for
typical batch sizes).

Clustering choice
=================
DBSCAN with metric='haversine' (sklearn supports this directly when
inputs are in radians).
  * eps = 100m on Earth ≈ 100m / 6_371_000m = 1.57e-5 radians
  * min_samples = 1 — even a single photo at a location is its own
    "cluster", because we want every photo to have a cluster_id for
    the UI filter (no noise points). The "noise" semantics from face
    clustering (V22.0) don't apply here: a one-off location is still
    a valid location, just a tiny cluster.

Photos without GPS (no GPS module on the camera, GPS disabled, indoor
shots that didn't get a lock) get ``gps_cluster_id = None`` — the UI
groups them under "未知位置" (unknown location).

Output schema
=============
Per row:
    "gps_lat"        float | None
    "gps_lon"        float | None
    "gps_cluster_id" int | None

Whole-run summary surfaced via ``location_summary``:
    {cluster_id: {n_photos, center_lat, center_lon, sample_filenames}}
"""

from __future__ import annotations

import math
import sys
from typing import Any

import numpy as np


# Tuning constants. Easy to override via location_summary args if needed.
_EARTH_RADIUS_M = 6_371_000.0
_DEFAULT_RADIUS_M = 100.0          # cluster radius
_DEFAULT_MIN_SAMPLES = 1           # every GPS point is its own cluster if
                                   # no neighbours within radius


def _radius_m_to_radians(radius_m: float) -> float:
    """Convert a Earth-surface radius (meters) to radians for haversine
    DBSCAN. The factor is 1 / R_earth."""
    return radius_m / _EARTH_RADIUS_M


def cluster_locations_across_rows(
    rows: list[dict[str, Any]],
    *,
    radius_m: float = _DEFAULT_RADIUS_M,
    min_samples: int = _DEFAULT_MIN_SAMPLES,
) -> list[dict[str, Any]]:
    """Run DBSCAN (haversine, eps=radius_m) over rows that have GPS,
    writing ``gps_cluster_id`` back to each row.

    Rows without GPS get ``gps_cluster_id = None`` (not -1 — that's
    DBSCAN noise, which we don't use here since min_samples=1).

    Side effect: mutates rows in place. Returns rows for chaining.
    """
    # Pull GPS-bearing rows
    gps_idx: list[int] = []
    coords: list[tuple[float, float]] = []
    for i, r in enumerate(rows):
        lat = r.get("gps_lat")
        lon = r.get("gps_lon")
        # Default: no cluster
        r["gps_cluster_id"] = None
        if lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue
        gps_idx.append(i)
        coords.append((lat_f, lon_f))

    if not coords:
        return rows

    # haversine DBSCAN wants radians
    X = np.radians(np.array(coords, dtype=np.float64))
    try:
        from sklearn.cluster import DBSCAN
    except ImportError:
        print("[location_cluster] sklearn unavailable, skipping",
              file=sys.stderr)
        return rows

    labels = DBSCAN(
        eps=_radius_m_to_radians(radius_m),
        min_samples=min_samples,
        metric="haversine",
        n_jobs=-1,
    ).fit_predict(X)

    for i, lab in zip(gps_idx, labels):
        # min_samples=1 means we shouldn't get -1, but be defensive
        rows[i]["gps_cluster_id"] = int(lab) if lab >= 0 else None

    n_clusters = len({int(l) for l in labels if l >= 0})
    print(f"[location_cluster] {len(coords)} GPS points → "
          f"{n_clusters} location clusters (radius={radius_m}m)",
          file=sys.stderr)
    return rows


def location_summary(rows: list[dict[str, Any]]) -> dict[int, dict]:
    """Per-cluster summary: count + centroid + sample filenames.

    Centroid is the unweighted mean of all member coordinates — close
    enough for cluster labeling purposes (the user types "Notre Dame"
    or "Eiffel Tower"; we don't need sub-meter accuracy).
    """
    out: dict[int, dict] = {}
    for r in rows:
        cid = r.get("gps_cluster_id")
        if cid is None:
            continue
        d = out.setdefault(cid, {
            "id":                cid,
            "n_photos":          0,
            "lats":              [],
            "lons":              [],
            "sample_filenames":  [],
            "best_score":        -1.0,
            "best_filename":     "",
        })
        d["n_photos"] += 1
        d["lats"].append(float(r["gps_lat"]))
        d["lons"].append(float(r["gps_lon"]))
        if len(d["sample_filenames"]) < 5:
            fn = r.get("filename", "")
            if fn:
                d["sample_filenames"].append(fn)
        # Track the highest score_final per cluster → "best of location"
        sf = r.get("score_final")
        if sf is not None:
            try:
                sf_f = float(sf)
            except (TypeError, ValueError):
                sf_f = -1.0
            if sf_f > d["best_score"]:
                d["best_score"] = sf_f
                d["best_filename"] = r.get("filename", "")

    # Replace raw lat/lon lists with centroid (drop the long arrays from
    # the API surface — they're internal accumulators).
    for d in out.values():
        if d["lats"]:
            d["center_lat"] = sum(d["lats"]) / len(d["lats"])
            d["center_lon"] = sum(d["lons"]) / len(d["lons"])
        else:
            d["center_lat"] = None
            d["center_lon"] = None
        d.pop("lats", None)
        d.pop("lons", None)
    return out


__all__ = [
    "cluster_locations_across_rows",
    "location_summary",
]
